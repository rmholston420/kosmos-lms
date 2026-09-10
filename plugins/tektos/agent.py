"""Tektos coding agent (Stage 3.1, ADR-036).

Pattern-vendored from ``OpenHands/software-agent-sdk`` (MIT) — the
:class:`Agent` / :class:`Conversation` surface is preserved in shape
(``send_message`` + ``run``) but rewritten to consume Kosmos ports
exclusively. No upstream source is copied into the tree; only the
API shape.

Stage 3.1 scope:
- One iteration per turn (one ``send_message`` + one ``run``).
- Reads prior context from :meth:`MemoryPort.query_temporal`.
- Calls :meth:`LLMPort.generate_text` once.
- Writes the response back through :meth:`MemoryPort.write_event`
  with fixed provenance ``"tektos_agent"`` and caller-supplied
  confidence (default 0.75, ADR-036).

Deferred to later 3.x steps:
- Multi-iteration loops (3.5 Reflexion + Voyager).
- Tool calls (3.2 MCP + Playwright).
- Task decomposition + auto-context-compression (3.6 OpenSpec).
- FrontendContractPort ``PluginDescriptor`` registration (3.7 spec-kit).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ports.approval import ApprovalGatewayPort, ChangeApprovalTier
from ports.llm import LLMPort
from ports.mcp import MCPPort, MCPToolResult
from ports.memory import MemoryPort
from ports.trace_feed import TraceEvent, TraceFeedPort

from plugins.tektos.errors import (
    TektosAgentAlreadyRunError,
    TektosAgentNotStartedError,
    TektosInvalidConfidenceError,
    TektosToolCallPending,
)
from plugins.tektos.mcp.tool_policy import (
    TEKTOS_TOOL_PREDICATE,
    resolve_tier,
)
from plugins.tektos.models import (
    TEKTOS_AGENT_PROVENANCE,
    TektosMessage,
    TektosMessageRole,
    TektosStep,
)
from plugins.tektos.tools.registry import (
    TektosToolRegistry,
    ToolApprovalDenied,
)

__all__ = ["TektosAgent", "TEKTOS_MEMORY_PREDICATE"]


TEKTOS_MEMORY_PREDICATE: str = "tektos.turn.completed"
"""Canonical predicate every completed Tektos turn writes to memory.

Downstream stages MAY introduce additional predicates (``tektos.tool.invoked``
at 3.2, ``tektos.reflection.applied`` at 3.5). This one is locked at ADR-036.
"""


_DEFAULT_CONFIDENCE: float = 0.75
"""Locked at ADR-036. Reflexion (Stage 3.5) grows a real confidence
signal from self-critique; until then Tektos writes fixed 0.75, which
sits above the standard AMG lower bound of 0.6."""


@dataclass(slots=True)
class TektosAgent:
    """Minimal coding-agent loop over Kosmos ports.

    Construction:
        >>> agent = TektosAgent(llm=my_llm_port, memory=my_memory_port)

    Usage (one turn):
        >>> agent.send_message("Explain what this project does.")
        >>> step = await agent.run()

    Multi-turn is not supported at Stage 3.1 — call ``send_message``
    again for a new turn.
    """

    llm: LLMPort
    memory: MemoryPort
    subject: str = "tektos_user"
    model: str | None = None
    system_prompt: str | None = None
    confidence: float = _DEFAULT_CONFIDENCE
    context_limit: int = 5
    mcp: MCPPort | None = None
    apex: ApprovalGatewayPort | None = None
    trace_feed: TraceFeedPort | None = None
    # Stage 4.8 · ADR-094 §D1 — optional delegation onto the unified
    # Stage-4.7 tool substrate. When set, ``call_tool`` delegates to
    # ``tool_registry.invoke`` (which routes through SandboxPort +
    # runs pre-approval detectors). When ``None`` (the Stage-3.2
    # construction path), the legacy inline flow is preserved unchanged.
    tool_registry: TektosToolRegistry | None = None

    _pending: TektosMessage | None = field(default=None, init=False, repr=False)
    _turn_id: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not (0.0 < self.confidence <= 1.0):
            raise TektosInvalidConfidenceError(
                f"confidence must be in (0.0, 1.0]; got {self.confidence!r}"
            )
        if self.context_limit < 0:
            raise ValueError(
                f"context_limit must be >= 0; got {self.context_limit!r}"
            )

    # ── Public API ─────────────────────────────────────────────────────────

    def send_message(self, content: str) -> str:
        """Queue a user turn. Returns the turn id.

        Overwrites any pending turn that has not yet been ``run``.
        """
        if not isinstance(content, str) or not content.strip():
            raise ValueError("send_message content must be a non-empty string")
        self._pending = TektosMessage.user(content)
        self._turn_id = f"tektos-turn-{uuid4()}"
        return self._turn_id

    async def run(self) -> TektosStep:
        """Execute one iteration of the agent loop.

        Raises:
            TektosAgentNotStartedError: no pending turn (call
                ``send_message`` first).
            TektosAgentAlreadyRunError: the pending turn was already
                run in this instance's lifetime.
        """
        pending = self._pending
        turn_id = self._turn_id
        if pending is None or turn_id is None:
            raise TektosAgentNotStartedError(
                "run() called with no pending turn; call send_message() first"
            )

        # Consume the pending turn atomically — a second run() on the
        # same turn raises rather than double-firing the LLM/memory paths.
        self._pending = None
        self._turn_id = None

        prompt = await self._build_prompt(pending)
        response_text = await self.llm.generate_text(
            prompt=prompt,
            model=self.model,
            system=self.system_prompt,
        )

        event_id = await self.memory.write_event(
            subject=self.subject,
            predicate=TEKTOS_MEMORY_PREDICATE,
            object=response_text,
            provenance=TEKTOS_AGENT_PROVENANCE,
            confidence=self.confidence,
            attributes={
                "turn_id": turn_id,
                "role": TektosMessageRole.ASSISTANT.value,
                "prompt_len": len(prompt),
                "response_len": len(response_text),
            },
        )

        return TektosStep(
            turn_id=turn_id,
            prompt=prompt,
            response=response_text,
            memory_event_id=event_id.id,
            confidence=self.confidence,
            llm_model=self.model,
        )

    # ── Internal ───────────────────────────────────────────────────────────

    async def _build_prompt(self, pending: TektosMessage) -> str:
        """Assemble the LLM prompt from prior memory context + the pending message.

        Reads up to ``context_limit`` prior Tektos turns from
        :meth:`MemoryPort.query_temporal` and prepends them as
        ``[prior]`` lines. If the query returns nothing (fresh agent,
        empty memory), the prompt is just the pending message.
        """
        if self.context_limit == 0:
            return pending.content

        hits = await self.memory.query_temporal(
            TEKTOS_MEMORY_PREDICATE,
            limit=self.context_limit,
        )
        if not hits:
            if self._had_double_run(turn_content=pending.content):
                # Defensive: never reached at Stage 3.1; sentinel for
                # future multi-iteration loops (3.5 Reflexion) that will
                # re-enter ``_build_prompt`` inside a single run().
                raise TektosAgentAlreadyRunError(
                    "double-run guard tripped; multi-iteration deferred to 3.5"
                )
            return pending.content

        prior_lines = [f"[prior] {self._render_hit(hit)}" for hit in hits]
        return "\n".join(prior_lines + [pending.content])

    @staticmethod
    def _render_hit(hit: object) -> str:
        """Extract a printable string from a :class:`MemoryHit`.

        MemoryPort returns :class:`MemoryHit(id, payload, score, as_of)`
        where the payload dict carries whatever the adapter stored. The
        canonical Tektos write path sets ``payload["object"]`` to the
        assistant response text, but we tolerate any of {``object``,
        ``content``, ``response``} to stay robust to adapter drift.
        """
        payload = getattr(hit, "payload", None)
        if isinstance(payload, dict):
            for key in ("object", "content", "response"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value
            return str(payload)
        return str(hit)

    def _had_double_run(self, *, turn_content: str) -> bool:
        """Stage 3.1 always returns False — the guard exists so future
        3.5 multi-iteration code can flip it without changing the public
        surface."""
        _ = turn_content
        return False

    # ── Stage 3.2 · MCP tool-call surface (ADR-037) ────────────────────────

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        turn_id: str | None = None,
    ) -> TektosStep:
        """Invoke a single MCP tool through the Praxis approval gate.

        Flow (Stage 3.2, ADR-037):

        1. Resolve tier via :func:`resolve_tier` (fail-closed HUMAN_REQUIRED).
        2. Emit a :class:`TraceEvent` on the ``trace_feed`` (if injected)
           **before** the APEX gate so Phrouros observes every attempt.
        3. Call :meth:`ChangeApprovalProtocol.propose` with the mapped tier.
           On ``AUTONOMOUS``, APEX returns an APPROVED record and this
           method proceeds. On ``HUMAN_REVIEW``/``HUMAN_REQUIRED`` the
           record is PENDING; this method raises
           :class:`TektosToolCallPending`.
        4. Invoke :meth:`MCPPort.call_tool`.
        5. Write the outcome via :meth:`MemoryPort.write_event` with
           ``predicate=TEKTOS_TOOL_PREDICATE`` and
           ``provenance=TEKTOS_AGENT_PROVENANCE``.

        Args:
            name: MCP tool identifier.
            arguments: Tool-specific arguments (JSON-serializable dict).
            turn_id: Optional turn correlation id. Autogenerated when omitted.

        Returns:
            :class:`TektosStep` describing the tool call outcome.

        Raises:
            RuntimeError: if ``mcp`` or ``apex`` was not injected.
            TektosToolCallPending: if the mapped tier requires human review.
        """
        # Stage 4.8 · ADR-094 §D1 — delegation path.
        if self.tool_registry is not None:
            return await self._call_tool_via_registry(
                name=name,
                arguments=arguments,
                turn_id=turn_id,
            )
        if self.mcp is None:
            raise RuntimeError(
                "TektosAgent.call_tool requires an MCPPort; "
                "construct with mcp=<adapter>"
            )
        if self.apex is None:
            raise RuntimeError(
                "TektosAgent.call_tool requires an ApprovalGatewayPort; "
                "construct with apex=<adapter>"
            )
        if not isinstance(name, str) or not name.strip():
            raise ValueError("call_tool: name must be a non-empty string")
        if not isinstance(arguments, dict):
            raise TypeError("call_tool: arguments must be a dict")

        effective_turn_id = turn_id or f"tektos-tool-{uuid4()}"
        tier = resolve_tier(name)

        # 2. Emit trace-first so Phrouros observes every attempt
        #    (including ones that will be rejected downstream).
        if self.trace_feed is not None:
            await self.trace_feed.publish(
                TraceEvent(
                    event_id=uuid4().hex,
                    occurred_at=datetime.now(timezone.utc),
                    plugin="tektos",
                    tool_name=name,
                    trace_id=effective_turn_id,
                    span_id=uuid4().hex,
                    attributes={
                        "tier": tier.value,
                        "arguments": dict(arguments),
                    },
                )
            )

        # 3. Praxis approval gate.
        approval_id = await self.apex.propose(
            intention_id=f"tektos.tool:{effective_turn_id}:{name}",
            delta={"tool": name, "arguments": dict(arguments)},
            tier=tier,
            proposing_domain="tektos",
            diff_preview={"tool": name},
        )
        if tier is not ChangeApprovalTier.AUTONOMOUS:
            raise TektosToolCallPending(
                f"tool {name!r} requires human approval (tier={tier.value}); "
                f"approval_id={approval_id}",
                approval_id=approval_id,
                tool_name=name,
            )

        # 4. Invoke tool.
        result: MCPToolResult = await self.mcp.call_tool(
            name=name, arguments=dict(arguments)
        )

        # 5. Memory write (zero-trust: provenance + confidence).
        event_id = await self.memory.write_event(
            subject=self.subject,
            predicate=TEKTOS_TOOL_PREDICATE,
            object=result.tool_name,
            provenance=TEKTOS_AGENT_PROVENANCE,
            confidence=self.confidence,
            attributes={
                "turn_id": effective_turn_id,
                "tool_name": name,
                "tool_arguments": dict(arguments),
                "is_error": result.is_error,
                "content_blocks": len(result.content),
                "approval_id": approval_id,
                "tier": tier.value,
            },
        )

        return TektosStep(
            turn_id=effective_turn_id,
            prompt="",  # tool call, not an LLM turn
            response="",
            memory_event_id=event_id.id,
            confidence=self.confidence,
            llm_model=None,
            llm_raw=None,
            tool_name=name,
            tool_arguments=dict(arguments),
            tool_result=result,
            approval_id=approval_id,
        )

    # ── Stage 4.8 · ADR-094 §D1 delegation helper ────────────────────

    async def _call_tool_via_registry(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        turn_id: str | None,
    ) -> TektosStep:
        """Delegate ``call_tool`` to the Stage-4.7 TektosToolRegistry.

        Preserves the ``TektosStep`` return shape so downstream callers
        (and Stage 3.2 tests) see the same envelope. The registry emits
        its own ``tektos.tool.invoked`` / ``tektos.tool.completed``
        envelopes; this method still writes a MemoryPort event with the
        Stage-3.2 ``TEKTOS_TOOL_PREDICATE`` so continuity with the
        legacy inline flow is intact.
        """
        assert self.tool_registry is not None  # gated by caller
        effective_turn_id = turn_id or f"tektos-turn-{uuid4()}"
        try:
            sandbox_result = await self.tool_registry.invoke(
                name,
                arguments,
                intention_id=effective_turn_id,
                proposing_domain="tektos",
            )
        except ToolApprovalDenied as exc:
            # Preserve the Stage-3.2 semantic surface: surface denials
            # from the registry (approval-gate REJECTED / REVIEW_MISSED,
            # or a pre-approval detector block) as the same class
            # legacy callers already handle.
            raise TektosToolCallPending(
                (
                    f"tool {name!r} denied by tool_registry "
                    f"(status={exc.status.value}, reason={exc.reason or 'n/a'})"
                ),
                approval_id=exc.approval_id or "",
                tool_name=name,
            ) from exc

        # Wrap the SandboxResult into an MCPToolResult-shaped payload so
        # TektosStep.tool_result stays a stable duck-typed object.
        tool_result = _sandbox_result_to_tool_result(
            tool_name=name, result=sandbox_result
        )

        event_id = await self.memory.write_event(
            subject=self.subject,
            predicate=TEKTOS_TOOL_PREDICATE,
            object=name,
            provenance=TEKTOS_AGENT_PROVENANCE,
            confidence=self.confidence,
            attributes={
                "turn_id": effective_turn_id,
                "tool_name": name,
                "tool_arguments": dict(arguments),
                "is_error": bool(sandbox_result.exit_code),
                "exit_code": sandbox_result.exit_code,
                "delegated_to": "tektos_tool_registry",
            },
        )

        return TektosStep(
            turn_id=effective_turn_id,
            prompt="",
            response="",
            memory_event_id=event_id.id,
            confidence=self.confidence,
            llm_model=None,
            llm_raw=None,
            tool_name=name,
            tool_arguments=dict(arguments),
            tool_result=tool_result,
            approval_id="",  # registry-owned; envelope carries invocation_id
        )


def _sandbox_result_to_tool_result(
    *, tool_name: str, result: Any
) -> MCPToolResult:
    """Adapt SandboxResult → MCPToolResult for TektosStep continuity."""
    return MCPToolResult(
        tool_name=tool_name,
        content=(
            {
                "type": "text",
                "text": (getattr(result, "stdout", "") or ""),
            },
        ),
        is_error=bool(getattr(result, "exit_code", 0)),
    )
