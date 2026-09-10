"""Stage 3.1 DoD contract tests for :class:`plugins.tektos.agent.TektosAgent`.

DoD literal (spec §18 3.1, ADR-036 Q3=A):

    "OpenHands agent can read/write via Kosmos ports only."

Landing anchor:
    :func:`test_tektos_agent_reads_and_writes_via_kosmos_ports_only_build_sequence_3_1_dod`

All fakes below implement the Kosmos port Protocols in full for the surface
Tektos consumes at Stage 3.1. They are runtime-checkable against the
:class:`~ports.llm.LLMPort` and :class:`~ports.memory.MemoryPort` Protocols
via ``isinstance()``.
"""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from ports.llm import LLMPort
from ports.memory import MemoryEventId, MemoryHit, MemoryPort, validate_zero_trust_write

from plugins.tektos import (
    TEKTOS_AGENT_PROVENANCE,
    TEKTOS_MEMORY_PREDICATE,
    TektosAgent,
    TektosAgentAlreadyRunError,
    TektosAgentNotStartedError,
    TektosInvalidConfidenceError,
    TektosMessage,
    TektosMessageRole,
    TektosStep,
)


# ── Fakes ──────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _FakeLLMPort:
    """Minimal :class:`LLMPort` implementation for Stage 3.1 tests.

    Records every ``generate_text`` call and returns a canned response.
    Every other verb raises :class:`NotImplementedError` — this fake is
    deliberately narrow to prove Tektos consumes only the port surface
    it declares at Stage 3.1.
    """

    canned_response: str = "canned-tektos-response"
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def generate(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("Stage 3.1 must not call LLMPort.generate")

    async def generate_text(
        self,
        *,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        **options: Any,
    ) -> str:
        self.calls.append(
            {"prompt": prompt, "model": model, "system": system, "options": dict(options)}
        )
        return self.canned_response

    async def chat(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("Stage 3.1 must not call LLMPort.chat")

    def generate_stream(self, **kwargs: Any) -> AsyncIterator[str]:
        raise NotImplementedError("Stage 3.1 must not call LLMPort.generate_stream")

    async def embed(self, **kwargs: Any) -> Any:
        raise NotImplementedError("Stage 3.1 must not call LLMPort.embed")

    async def list_models(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def pull_model(self, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError

    async def delete_model(self, **kwargs: Any) -> None:
        raise NotImplementedError

    async def is_healthy(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@dataclass(slots=True)
class _FakeMemoryPort:
    """Minimal :class:`MemoryPort` implementation for Stage 3.1 tests.

    Records every ``write_event`` and every ``query_temporal`` call.
    Priming :attr:`_hits` seeds the temporal query for context-read
    scenarios. Every ``write_event`` call is validated through
    :func:`ports.memory.validate_zero_trust_write` before being recorded
    — the port-level guard is non-bypassable and this fake honours it.
    """

    writes: list[dict[str, Any]] = field(default_factory=list)
    queries: list[dict[str, Any]] = field(default_factory=list)
    _hits: list[MemoryHit] = field(default_factory=list)
    _next_event_seq: int = 0

    def seed(self, hits: list[MemoryHit]) -> None:
        self._hits = list(hits)

    async def write_event(
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        provenance: str,
        confidence: float,
        source_citation: str | None = None,
        pii_tier: str = "Public",
        attributes: dict[str, Any] | None = None,
    ) -> MemoryEventId:
        validate_zero_trust_write(provenance=provenance, confidence=confidence)
        self._next_event_seq += 1
        record = {
            "subject": subject,
            "predicate": predicate,
            "object": object,
            "provenance": provenance,
            "confidence": confidence,
            "source_citation": source_citation,
            "pii_tier": pii_tier,
            "attributes": dict(attributes or {}),
        }
        self.writes.append(record)
        return MemoryEventId(
            id=f"mem-{self._next_event_seq}",
            written_at=datetime.now(timezone.utc),
        )

    async def query_temporal(
        self,
        cypher_or_query: str,
        *,
        as_of: datetime | None = None,
        limit: int = 20,
    ) -> list[MemoryHit]:
        self.queries.append(
            {"query": cypher_or_query, "as_of": as_of, "limit": limit}
        )
        return list(self._hits[: max(0, limit)])

    async def link_entities(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Stage 3.1 must not call MemoryPort.link_entities")

    async def quarantine_write(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Stage 3.1 must not call MemoryPort.quarantine_write")

    async def search_semantic(self, *args: Any, **kwargs: Any) -> list:
        # ADR-074 D1 added search_semantic to MemoryPort; fake degrades to [].
        return []

    async def search_hybrid(self, *args: Any, **kwargs: Any) -> list:
        # ADR-085 / ADR-099 added search_hybrid to MemoryPort. Stage 3.1 must
        # not call it — raise so silent misuse surfaces immediately.
        raise NotImplementedError(
            "Stage 3.1 must not call MemoryPort.search_hybrid"
        )

    def is_healthy(self) -> bool:
        return True

    async def close(self) -> None:
        return None


# ── Protocol conformance ───────────────────────────────────────────────────


def test_fake_llm_port_is_runtime_llmport() -> None:
    assert isinstance(_FakeLLMPort(), LLMPort)


def test_fake_memory_port_is_runtime_memoryport() -> None:
    assert isinstance(_FakeMemoryPort(), MemoryPort)


# ── Construction guards ────────────────────────────────────────────────────


def test_agent_rejects_zero_confidence() -> None:
    with pytest.raises(TektosInvalidConfidenceError):
        TektosAgent(llm=_FakeLLMPort(), memory=_FakeMemoryPort(), confidence=0.0)


def test_agent_rejects_over_one_confidence() -> None:
    with pytest.raises(TektosInvalidConfidenceError):
        TektosAgent(llm=_FakeLLMPort(), memory=_FakeMemoryPort(), confidence=1.5)


def test_agent_rejects_negative_context_limit() -> None:
    with pytest.raises(ValueError, match="context_limit"):
        TektosAgent(llm=_FakeLLMPort(), memory=_FakeMemoryPort(), context_limit=-1)


def test_send_message_rejects_empty() -> None:
    agent = TektosAgent(llm=_FakeLLMPort(), memory=_FakeMemoryPort())
    with pytest.raises(ValueError):
        agent.send_message("")
    with pytest.raises(ValueError):
        agent.send_message("   ")


# ── Run without pending turn ───────────────────────────────────────────────


async def test_run_without_send_message_raises() -> None:
    agent = TektosAgent(llm=_FakeLLMPort(), memory=_FakeMemoryPort())
    with pytest.raises(TektosAgentNotStartedError):
        await agent.run()


# ── send_message returns a turn id ─────────────────────────────────────────


def test_send_message_returns_turn_id() -> None:
    agent = TektosAgent(llm=_FakeLLMPort(), memory=_FakeMemoryPort())
    turn_id = agent.send_message("hello tektos")
    assert isinstance(turn_id, str)
    assert turn_id.startswith("tektos-turn-")


# ── DoD literal ────────────────────────────────────────────────────────────


async def test_tektos_agent_reads_and_writes_via_kosmos_ports_only_build_sequence_3_1_dod() -> None:
    """Stage 3.1 DoD literal (spec §18 3.1, ADR-036 Q3=A).

    Asserts, in one iteration:
      1. Agent read prior context from ``MemoryPort.query_temporal``.
      2. LLM was called exactly once with a prompt that includes both
         the seeded prior turn text and the pending user message.
      3. Response was written back through ``MemoryPort.write_event``
         with provenance ``"tektos_agent"`` and confidence in ``(0, 1]``.
      4. The ``TektosStep`` returned by ``run()`` records the turn id,
         LLM response, memory event id, and confidence.
    """
    llm = _FakeLLMPort(canned_response="I read your project docs.")
    memory = _FakeMemoryPort()
    memory.seed(
        [
            MemoryHit(
                id="prior-1",
                payload={"object": "Prior Tektos turn: user asked about layout."},
                score=1.0,
            ),
        ]
    )

    agent = TektosAgent(
        llm=llm,
        memory=memory,
        model="gpt-5-fake",
        system_prompt="You are Tektos.",
        confidence=0.85,
    )
    turn_id = agent.send_message("Explain what this project does.")
    step = await agent.run()

    # 1. Context read
    assert len(memory.queries) == 1
    assert memory.queries[0]["query"] == TEKTOS_MEMORY_PREDICATE
    assert memory.queries[0]["limit"] == agent.context_limit

    # 2. LLM called with prompt containing prior + pending
    assert len(llm.calls) == 1
    prompt = llm.calls[0]["prompt"]
    assert "Prior Tektos turn: user asked about layout." in prompt
    assert "Explain what this project does." in prompt
    assert llm.calls[0]["model"] == "gpt-5-fake"
    assert llm.calls[0]["system"] == "You are Tektos."

    # 3. MemoryPort write with locked provenance + confidence
    assert len(memory.writes) == 1
    write = memory.writes[0]
    assert write["subject"] == "tektos_user"
    assert write["predicate"] == TEKTOS_MEMORY_PREDICATE
    assert write["object"] == "I read your project docs."
    assert write["provenance"] == TEKTOS_AGENT_PROVENANCE
    assert write["provenance"] == "tektos_agent"
    assert 0.0 < write["confidence"] <= 1.0
    assert write["confidence"] == 0.85
    assert write["attributes"]["turn_id"] == turn_id
    assert write["attributes"]["role"] == TektosMessageRole.ASSISTANT.value

    # 4. TektosStep records the turn
    assert isinstance(step, TektosStep)
    assert step.turn_id == turn_id
    assert step.response == "I read your project docs."
    assert step.confidence == 0.85
    assert step.memory_event_id.startswith("mem-")
    assert step.llm_model == "gpt-5-fake"


# ── Empty-memory path ──────────────────────────────────────────────────────


async def test_run_with_empty_memory_uses_only_pending_content() -> None:
    llm = _FakeLLMPort(canned_response="ok")
    memory = _FakeMemoryPort()  # no seed

    agent = TektosAgent(llm=llm, memory=memory)
    agent.send_message("first turn")
    await agent.run()

    assert llm.calls[0]["prompt"] == "first turn"


async def test_run_with_context_limit_zero_skips_memory_query() -> None:
    llm = _FakeLLMPort(canned_response="ok")
    memory = _FakeMemoryPort()
    memory.seed(
        [
            MemoryHit(id="p", payload={"object": "should not appear"}, score=1.0),
        ]
    )

    agent = TektosAgent(llm=llm, memory=memory, context_limit=0)
    agent.send_message("pending")
    await agent.run()

    assert memory.queries == []
    assert llm.calls[0]["prompt"] == "pending"


# ── Second run() on same turn refuses ──────────────────────────────────────


async def test_second_run_on_same_turn_raises() -> None:
    agent = TektosAgent(llm=_FakeLLMPort(), memory=_FakeMemoryPort())
    agent.send_message("only turn")
    await agent.run()
    with pytest.raises(TektosAgentNotStartedError):
        await agent.run()


# ── Multi-turn (send_message twice) works with fresh iteration ─────────────


async def test_second_send_message_creates_fresh_turn() -> None:
    llm = _FakeLLMPort(canned_response="ok")
    memory = _FakeMemoryPort()
    agent = TektosAgent(llm=llm, memory=memory)

    id1 = agent.send_message("turn 1")
    await agent.run()
    id2 = agent.send_message("turn 2")
    await agent.run()

    assert id1 != id2
    assert len(llm.calls) == 2
    assert len(memory.writes) == 2
    assert memory.writes[0]["attributes"]["turn_id"] == id1
    assert memory.writes[1]["attributes"]["turn_id"] == id2


# ── Zero-trust guard passthrough ───────────────────────────────────────────


async def test_default_provenance_and_confidence_pass_port_guard() -> None:
    """Every Tektos MemoryPort write carries valid provenance + confidence per ADR-008."""
    llm = _FakeLLMPort(canned_response="ok")
    memory = _FakeMemoryPort()
    agent = TektosAgent(llm=llm, memory=memory)  # default confidence 0.75
    agent.send_message("guard-check")
    await agent.run()

    # If the guard rejected our defaults, the fake's write_event would
    # have raised before recording; the fact that we have a write proves
    # the guard accepted them.
    assert len(memory.writes) == 1
    validate_zero_trust_write(
        provenance=memory.writes[0]["provenance"],
        confidence=memory.writes[0]["confidence"],
    )


# ── Locked constants ───────────────────────────────────────────────────────


def test_locked_provenance_string() -> None:
    """Locked at ADR-036: every Tektos memory write uses this exact provenance."""
    assert TEKTOS_AGENT_PROVENANCE == "tektos_agent"


def test_locked_memory_predicate() -> None:
    """Locked at ADR-036: every completed Tektos turn writes this predicate."""
    assert TEKTOS_MEMORY_PREDICATE == "tektos.turn.completed"


def test_tektos_message_helpers() -> None:
    msg_u = TektosMessage.user("hi")
    msg_a = TektosMessage.assistant("hello")
    assert msg_u.role is TektosMessageRole.USER
    assert msg_a.role is TektosMessageRole.ASSISTANT
    assert msg_u.content == "hi"
    assert msg_a.content == "hello"


# ── ADR-007: Tektos imports no other plugin ────────────────────────────────


def test_tektos_agent_imports_no_other_plugins_adr_007() -> None:
    """ADR-007: cross-plugin coupling flows through the event bus or a formal port.

    Statically inspect every ``import`` and ``from ... import`` in
    ``plugins/tektos/agent.py`` and assert none touch another plugin's
    package namespace.
    """
    agent_path = Path(__file__).resolve().parent.parent / "agent.py"
    tree = ast.parse(agent_path.read_text(encoding="utf-8"))

    forbidden_prefixes = ("plugins.phrouros", "plugins.praxis")
    offending: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if any(module.startswith(pref) for pref in forbidden_prefixes):
                offending.append(module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if any(alias.name.startswith(pref) for pref in forbidden_prefixes):
                    offending.append(alias.name)
    assert offending == [], (
        f"ADR-007 violation: Tektos agent imports other plugin packages: {offending}"
    )
