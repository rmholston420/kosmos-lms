"""plugins.tektos.tools.registry — approval-gated Tektos tool registry.

ADR-093 §4. Layers approval-tier + network-policy metadata over the
Tektos-Ultima donor ``ToolDefinition`` shape (vendored at
``adapters.sandbox.tektos.vendor.tool_registry_donor``) and routes every
invocation through:

1. ``ApprovalGatewayPort.propose`` — synchronous for ``AUTONOMOUS``,
   blocking on ``ApprovalResolverPort.get_by_id`` for
   ``HUMAN_REVIEW`` / ``HUMAN_REQUIRED``.
2. ``SandboxPort.run`` — every tool execution flows through the
   sandbox port; no direct handler invocation escapes the isolation
   boundary.
3. ``EventBusPort.publish`` — ``tektos.tool.{invoked,approved,denied,
   completed}`` envelopes with ``provenance="tektos_tool"`` and
   ``confidence=1.0`` per Stage 4.7 DoD.

The registry accepts ports at construction; the real kernel wires
Praxis APEX + the Tektos sandbox adapter + the Valkey event bus.
Contract tests inject stubs.
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from adapters.sandbox.tektos.vendor.tool_registry_donor import (
    JsonSchemaValidationError,
    validate_arguments,
)
from ports.approval import (
    ApprovalGatewayPort,
    ApprovalResolverPort,
    ApprovalStatus,
    ChangeApprovalTier,
)
from ports.event_envelope import EventEnvelope
from ports.immune import Detector, ImmuneScanRequest
from ports.memory import MemoryPort
from ports.sandbox import (
    SandboxLimits,
    SandboxNetworkPolicy,
    SandboxPort,
    SandboxRequest,
    SandboxResult,
)

logger = logging.getLogger(__name__)

__all__ = [
    "TektosToolRegistry",
    "ToolApprovalDenied",
    "ToolDescriptor",
    "ToolNotFound",
]


class ToolNotFound(KeyError):
    """Raised when ``invoke`` is called with an unregistered tool name."""


class ToolApprovalDenied(RuntimeError):
    """Raised when an ``ApprovalPort`` decision terminates with denial.

    Carries the ``approval_id`` and terminal :class:`ApprovalStatus`
    (``REJECTED`` or ``REVIEW_MISSED``) so callers can propagate a
    structured error to the turn planner.
    """

    def __init__(self, approval_id: str, status: ApprovalStatus, reason: str | None) -> None:
        super().__init__(f"tool approval denied ({status.value}): {reason or 'no reason'}")
        self.approval_id = approval_id
        self.status = status
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """Immutable declaration of one registered tool.

    Extends the upstream ``ToolDefinition`` shape with the two fields
    the upstream registry lacked and Stage 4.7 requires:

    - ``approval_tier`` — :class:`ChangeApprovalTier` gate applied on
      every :meth:`TektosToolRegistry.invoke` call.
    - ``network`` — :class:`SandboxNetworkPolicy` propagated into
      :class:`SandboxLimits` for the sandbox run.
    """

    name: str
    description: str
    parameters: Mapping[str, Any]
    approval_tier: ChangeApprovalTier
    network: SandboxNetworkPolicy = "none"
    timeout_seconds: int = 30
    max_memory_mb: int = 256
    max_cpu_percent: int = 100
    enabled: bool = True
    # Stage 4.8 · ADR-094 §D3: optional immune-scan kind. When set, the
    # ``TektosToolRegistry.invoke`` pre-approval detector loop passes
    # ``ImmuneScanRequest.kind = scan_kind`` so detectors can filter by
    # tool category (e.g. ``"tektos.tool.filesystem"``). None disables
    # detector routing for that descriptor (detectors still run but only
    # respond to their default kind).
    scan_kind: str | None = None


class _EventBusLike(Protocol):
    async def publish(self, envelope: EventEnvelope) -> str: ...


class TektosToolRegistry:
    """Approval-gated tool registry with sandbox-mediated execution."""

    _PRODUCER = "tektos_tools"
    _POLL_INTERVAL_SECONDS = 0.1
    _POLL_JITTER_SECONDS = 0.05
    _POLL_MAX_INTERVAL_SECONDS = 1.0
    _DEFAULT_APPROVAL_TIMEOUT_SECONDS = 300

    def __init__(
        self,
        *,
        approval_gateway: ApprovalGatewayPort,
        approval_resolver: ApprovalResolverPort,
        sandbox: SandboxPort,
        event_bus: _EventBusLike | None = None,
        approval_timeout_seconds: int | None = None,
        pre_approval_detectors: tuple[Detector, ...] = (),
        memory: MemoryPort | None = None,
        detector_scan_source: str = "tektos",
    ) -> None:
        self._approval_gateway = approval_gateway
        self._approval_resolver = approval_resolver
        self._sandbox = sandbox
        self._event_bus = event_bus
        self._descriptors: dict[str, ToolDescriptor] = {}
        self._approval_timeout_seconds = (
            approval_timeout_seconds
            if approval_timeout_seconds is not None
            else self._DEFAULT_APPROVAL_TIMEOUT_SECONDS
        )
        # Stage 4.8 · ADR-094 §D3: pre-approval detectors run before
        # ApprovalGatewayPort.propose. Any severity="block" hit publishes
        # immune.verdict.block + writes MemoryPort + publishes
        # tektos.tool.denied, then raises. ``memory`` is required only
        # when detectors are registered (immune-verdict writes need it
        # per ADR-079 rule 2).
        self._pre_approval_detectors: tuple[Detector, ...] = tuple(
            pre_approval_detectors
        )
        self._memory = memory
        self._detector_scan_source = detector_scan_source
        if self._pre_approval_detectors and self._memory is None:
            raise ValueError(
                "TektosToolRegistry: pre_approval_detectors require a "
                "MemoryPort (ADR-079 rule 2 — block verdicts MUST write "
                "MemoryPort with provenance='immune_verdict' + confidence=1.0)."
            )

    # ── Registration ──────────────────────────────────────────────────

    def register(self, descriptor: ToolDescriptor) -> None:
        if descriptor.name in self._descriptors:
            raise ValueError(f"tool already registered: {descriptor.name!r}")
        self._descriptors[descriptor.name] = descriptor

    def unregister(self, name: str) -> None:
        self._descriptors.pop(name, None)

    def list_tools(self) -> tuple[ToolDescriptor, ...]:
        return tuple(self._descriptors.values())

    def get(self, name: str) -> ToolDescriptor:
        try:
            return self._descriptors[name]
        except KeyError as exc:
            raise ToolNotFound(name) from exc

    # ── Invocation ────────────────────────────────────────────────────

    async def invoke(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        intention_id: str,
        proposing_domain: str = "tektos",
    ) -> SandboxResult:
        descriptor = self.get(tool_name)
        if not descriptor.enabled:
            raise ToolApprovalDenied(
                approval_id="", status=ApprovalStatus.REJECTED, reason="tool disabled"
            )

        # 1. Validate arguments against the tool's JSON schema.
        try:
            validate_arguments(dict(descriptor.parameters), dict(arguments))
        except JsonSchemaValidationError as exc:
            raise ValueError(f"invalid arguments for tool {tool_name!r}: {exc}") from exc

        invocation_id = f"toolcall-{uuid.uuid4().hex[:12]}"

        # 1.5. Stage 4.8 · ADR-094 §D3 — pre-approval detectors.
        #      Runs BEFORE the ApprovalGatewayPort.propose so a malicious
        #      input never reaches the approval queue. Detector kind is
        #      the descriptor's declared ``scan_kind`` when set, else the
        #      generic ``"tektos.tool.invocation"`` (backwards-compatible
        #      with any Stage 4.7 tests that constructed the registry
        #      without detectors).
        if self._pre_approval_detectors:
            await self._run_pre_approval_detectors(
                descriptor=descriptor,
                arguments=arguments,
                invocation_id=invocation_id,
                intention_id=intention_id,
                proposing_domain=proposing_domain,
            )

        # 2. Publish `tektos.tool.invoked` before the approval gate.
        await self._publish(
            "tektos.tool.invoked",
            correlation_id=invocation_id,
            payload={
                "tool_name": tool_name,
                "intention_id": intention_id,
                "proposing_domain": proposing_domain,
                "tier": descriptor.approval_tier.value,
                "network": descriptor.network,
            },
        )

        # 3. Route through ApprovalGatewayPort.
        approval_id = await self._approval_gateway.propose(
            intention_id=intention_id,
            delta={
                "tool_name": tool_name,
                "arguments": dict(arguments),
                "network": descriptor.network,
            },
            tier=descriptor.approval_tier,
            proposing_domain=proposing_domain,
            diff_preview={
                "action": f"invoke_tool:{tool_name}",
                "network": descriptor.network,
            },
        )

        # 4. AUTONOMOUS returns synchronously; blocking tiers poll the resolver.
        if descriptor.approval_tier is not ChangeApprovalTier.AUTONOMOUS:
            record = await self._await_resolution(approval_id)
            if record.status in (ApprovalStatus.REJECTED, ApprovalStatus.REVIEW_MISSED):
                await self._publish(
                    "tektos.tool.denied",
                    correlation_id=invocation_id,
                    payload={
                        "tool_name": tool_name,
                        "approval_id": approval_id,
                        "status": record.status.value,
                        "reason": record.reason,
                    },
                )
                raise ToolApprovalDenied(
                    approval_id=approval_id,
                    status=record.status,
                    reason=record.reason,
                )
            await self._publish(
                "tektos.tool.approved",
                correlation_id=invocation_id,
                payload={
                    "tool_name": tool_name,
                    "approval_id": approval_id,
                    "status": record.status.value,
                },
            )

        # 5. Execute via SandboxPort.
        sandbox_request = self._build_sandbox_request(descriptor, arguments)
        try:
            result = await self._sandbox.run(sandbox_request)
        except Exception as exc:  # noqa: BLE001
            await self._publish(
                "tektos.tool.completed",
                correlation_id=invocation_id,
                payload={
                    "tool_name": tool_name,
                    "approval_id": approval_id,
                    "error": str(exc),
                    "provenance": "tektos_tool",
                    "confidence": 1.0,
                },
            )
            raise

        await self._publish(
            "tektos.tool.completed",
            correlation_id=invocation_id,
            payload={
                "tool_name": tool_name,
                "approval_id": approval_id,
                "run_id": result.run_id,
                "exit_code": result.exit_code,
                "killed_by": result.killed_by,
                "wall_seconds": result.wall_seconds,
                "provenance": "tektos_tool",
                "confidence": 1.0,
            },
        )
        return result

    # ── Internal ──────────────────────────────────────────────────────

    def _build_sandbox_request(
        self,
        descriptor: ToolDescriptor,
        arguments: Mapping[str, Any],
    ) -> SandboxRequest:
        # Registry tools declare their own argv via the ``argv`` argument
        # slot in ``parameters``. The upstream registry passed a whole
        # ``command`` string to ``shell=True``; ADR-093 §2 replaces that
        # with an explicit ``argv`` tuple so nothing goes through a shell.
        raw_argv = arguments.get("argv") or arguments.get("command")
        if isinstance(raw_argv, str):
            # Compatibility: some callers pass a single-string command;
            # the sandbox adapter still refuses ``shell=True`` — the
            # caller-supplied string becomes argv[0] and its own words
            # remain literal.
            argv: tuple[str, ...] = (raw_argv,)
        elif isinstance(raw_argv, (list, tuple)):
            argv = tuple(str(item) for item in raw_argv)
        else:
            raise ValueError(
                f"tool {descriptor.name!r} requires an 'argv' (list) or 'command' (str) argument"
            )
        if not argv:
            raise ValueError(f"tool {descriptor.name!r} argv must be non-empty")

        return SandboxRequest(
            command=descriptor.name,
            argv=argv,
            cwd=str(arguments.get("cwd", "/tmp")),
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                **{
                    str(k): str(v)
                    for k, v in (arguments.get("env") or {}).items()
                },
            },
            limits=SandboxLimits(
                max_wall_seconds=int(arguments.get("timeout_seconds", descriptor.timeout_seconds)),
                max_memory_mb=descriptor.max_memory_mb,
                max_cpu_percent=descriptor.max_cpu_percent,
                network=descriptor.network,
            ),
            stdin=(
                str(arguments["stdin"])
                if arguments.get("stdin") is not None
                else None
            ),
        )

    async def _await_resolution(self, approval_id: str):
        """Poll the resolver with jittered backoff until terminal or timeout."""

        deadline = asyncio.get_event_loop().time() + self._approval_timeout_seconds
        interval = self._POLL_INTERVAL_SECONDS
        while True:
            record = await self._approval_resolver.get_by_id(approval_id)
            if record.status is not ApprovalStatus.PENDING:
                return record
            now = asyncio.get_event_loop().time()
            if now >= deadline:
                raise ToolApprovalDenied(
                    approval_id=approval_id,
                    status=ApprovalStatus.REVIEW_MISSED,
                    reason="approval polling timed out",
                )
            sleep_for = min(interval, deadline - now)
            sleep_for = max(0.0, sleep_for + random.uniform(0, self._POLL_JITTER_SECONDS))
            await asyncio.sleep(sleep_for)
            interval = min(interval * 1.5, self._POLL_MAX_INTERVAL_SECONDS)

    async def _run_pre_approval_detectors(
        self,
        *,
        descriptor: ToolDescriptor,
        arguments: Mapping[str, Any],
        invocation_id: str,
        intention_id: str,
        proposing_domain: str,
    ) -> None:
        """Scan the invocation via every registered detector.

        On any ``severity="block"`` hit:
        - Publishes ``immune.verdict.block`` envelope (ADR-079 rule 1).
        - Writes ``MemoryPort`` with ``provenance='immune_verdict'`` +
          ``confidence=1.0`` (ADR-079 rule 2).
        - Publishes ``tektos.tool.denied`` with ``denial_reason``.
        - Raises ``ToolApprovalDenied`` (or the detector-specific
          subclass callers may register in the future).
        """
        scan_kind = descriptor.scan_kind or "tektos.tool.invocation"
        scan_payload: dict[str, Any] = {
            "tool_name": descriptor.name,
            "arguments": dict(arguments),
            "intention_id": intention_id,
            "proposing_domain": proposing_domain,
        }
        request = ImmuneScanRequest(
            payload=scan_payload,
            kind=scan_kind,
            source_plugin=self._detector_scan_source,
        )

        for detector in self._pre_approval_detectors:
            hits = await detector.evaluate(request)
            for hit in hits:
                if hit.severity != "block":
                    continue
                # ADR-079 rule 1: publish immune.verdict.block.
                await self._publish(
                    "immune.verdict.block",
                    correlation_id=invocation_id,
                    payload={
                        "detector": hit.detector_name,
                        "evidence": hit.evidence,
                        "tool_name": descriptor.name,
                        "scan_kind": scan_kind,
                        "source_plugin": self._detector_scan_source,
                    },
                )
                # ADR-079 rule 2: write MemoryPort with immune provenance.
                assert self._memory is not None  # guarded in __init__
                await self._memory.write_event(
                    subject=f"tektos.tool:{descriptor.name}",
                    predicate="immune.verdict.block",
                    object=hit.detector_name,
                    provenance="immune_verdict",
                    confidence=1.0,
                    attributes={
                        "evidence": hit.evidence,
                        "scan_kind": scan_kind,
                        "invocation_id": invocation_id,
                        "intention_id": intention_id,
                    },
                )
                # Publish tektos.tool.denied too so the tool-call log
                # stays consistent with approval-gate denials.
                await self._publish(
                    "tektos.tool.denied",
                    correlation_id=invocation_id,
                    payload={
                        "tool_name": descriptor.name,
                        "approval_id": "",
                        "status": ApprovalStatus.REJECTED.value,
                        "reason": f"detector_block:{hit.detector_name}",
                        "denial_reason": hit.detector_name,
                        "evidence": hit.evidence,
                    },
                )
                # Late-import to keep the registry loadable when the
                # detectors package is not present (Stage 4.7 tests).
                try:
                    from plugins.tektos.tools.detectors.path_traversal import (
                        PathTraversalDetected,
                    )
                except ImportError:  # pragma: no cover
                    PathTraversalDetected = None  # type: ignore[assignment]
                if (
                    PathTraversalDetected is not None
                    and hit.detector_name == "path_traversal"
                ):
                    offending_path = str(scan_payload["arguments"].get("path", ""))
                    # Parse the reason tag out of the evidence string
                    # ('reason=<tag> path=... namespace_root=... tool=...').
                    reason_tag = "unknown"
                    for token in hit.evidence.split():
                        if token.startswith("reason="):
                            reason_tag = token.split("=", 1)[1]
                            break
                    raise PathTraversalDetected(
                        offending_path=offending_path,
                        reason=reason_tag,
                    )
                raise ToolApprovalDenied(
                    approval_id="",
                    status=ApprovalStatus.REJECTED,
                    reason=f"detector_block:{hit.detector_name}:{hit.evidence}",
                )

    async def _publish(
        self,
        event_type: str,
        *,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> None:
        if self._event_bus is None:
            return
        try:
            enriched: dict[str, Any] = {
                "source": self._PRODUCER,
                "correlation_id": correlation_id,
                "provenance": "tektos_tool",
                "confidence": 1.0,
            }
            enriched.update(payload)
            await self._event_bus.publish(
                EventEnvelope(
                    event_type=event_type,
                    producer_plugin=self._PRODUCER,
                    payload=enriched,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("tool registry publish failed for %s", event_type)
