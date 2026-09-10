"""plugins.tektos.planner.turn_planner — Kosmos-native planner seed (ADR-093).

Stage 4.7 seed:

* Hand-authored 3-node plan `(read → analyze → summarize)` derived from
  the prompt with **no LLM call**. This satisfies the Stage 4.7 DoD verb
  ("a scripted plan node round-trips through EventBusPort") without
  pulling in ``LLMPort`` role-routing (deferred to ADR-087 Colossus
  benchmark).
* Every ``plan()`` publishes ``tektos.plan.started``, one
  ``tektos.plan.node`` envelope per node, and ``tektos.plan.completed``
  on ``EventBusPort`` per ADR-086.

Full donor absorption of the 8-module planner (translator + disambiguator
+ spec_generator + orchestrator + template_selector + repo_map) lands
after ``LLMPort`` gains role-routing (Stage 4.7+1).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ports.event_envelope import EventEnvelope

logger = logging.getLogger(__name__)

__all__ = ["Plan", "PlanNode", "PlanNodeKind", "TektosTurnPlanner"]


PlanNodeKind = Literal["read", "analyze", "tool_call", "summarize"]


@dataclass(frozen=True, slots=True)
class PlanNode:
    """One node in a Tektos plan graph.

    ``depends_on`` is a tuple of ``node_id`` values that must complete
    before this node runs. The seed planner only emits a linear chain,
    but the shape supports diamond/DAG plans without a migration.
    """

    node_id: str
    kind: PlanNodeKind
    description: str
    tool_name: str | None = None
    depends_on: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class Plan:
    """Immutable Tektos plan — a frozen tuple of ``PlanNode`` entries."""

    plan_id: str
    prompt: str
    nodes: tuple[PlanNode, ...]

    def __len__(self) -> int:
        return len(self.nodes)

    def __iter__(self):  # type: ignore[override]
        return iter(self.nodes)


class _EventBusLike(Protocol):
    async def publish(self, envelope: EventEnvelope) -> str: ...


class TektosTurnPlanner:
    """Hand-authored planner that emits ``tektos.plan.*`` envelopes.

    Constructor takes an optional ``EventBusPort``-like publisher so
    contract tests can inject a stub. The real kernel wires the Valkey
    event bus adapter.
    """

    _PRODUCER = "tektos_planner"

    def __init__(self, *, event_bus: _EventBusLike | None = None) -> None:
        self._event_bus = event_bus

    async def plan(self, prompt: str) -> Plan:
        """Return a scripted 3-node plan and publish lifecycle envelopes.

        The plan is always ``read → analyze → summarize``. The prompt is
        threaded through the node descriptions so downstream consumers
        can see which prompt each node was generated for.
        """

        prompt = prompt.strip()
        if not prompt:
            raise ValueError("TektosTurnPlanner.plan requires a non-empty prompt")

        plan_id = f"plan-{uuid.uuid4().hex[:12]}"
        nodes = self._scripted_plan(plan_id, prompt)
        plan = Plan(plan_id=plan_id, prompt=prompt, nodes=nodes)

        await self._publish(
            "tektos.plan.started",
            plan_id=plan_id,
            payload={
                "prompt": prompt,
                "node_count": len(nodes),
            },
        )
        for node in nodes:
            await self._publish(
                "tektos.plan.node",
                plan_id=plan_id,
                payload={
                    "node_id": node.node_id,
                    "kind": node.kind,
                    "description": node.description,
                    "tool_name": node.tool_name,
                    "depends_on": list(node.depends_on),
                },
            )
        await self._publish(
            "tektos.plan.completed",
            plan_id=plan_id,
            payload={"node_count": len(nodes)},
        )
        return plan

    # ── Internal ──────────────────────────────────────────────────────

    def _scripted_plan(self, plan_id: str, prompt: str) -> tuple[PlanNode, ...]:
        read_id = f"{plan_id}:read"
        analyze_id = f"{plan_id}:analyze"
        summarize_id = f"{plan_id}:summarize"
        return (
            PlanNode(
                node_id=read_id,
                kind="read",
                description=f"Read context relevant to: {prompt}",
            ),
            PlanNode(
                node_id=analyze_id,
                kind="analyze",
                description=f"Analyze the read context against the prompt: {prompt}",
                depends_on=(read_id,),
            ),
            PlanNode(
                node_id=summarize_id,
                kind="summarize",
                description=f"Summarize the analysis and return a turn reply for: {prompt}",
                depends_on=(analyze_id,),
            ),
        )

    async def _publish(
        self,
        event_type: str,
        *,
        plan_id: str,
        payload: dict[str, Any],
    ) -> None:
        if self._event_bus is None:
            return
        try:
            enriched: dict[str, Any] = {
                "source": self._PRODUCER,
                "plan_id": plan_id,
                "correlation_id": plan_id,
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
            logger.exception("planner publish failed for %s", event_type)
