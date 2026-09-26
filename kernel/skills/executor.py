"""Tektos-Ultima-v1 — Skill Executor

Runtime that loads and executes skill steps.

Responsibilities:
  1. Load skill definitions from registry or files
  2. Execute steps in order with error handling
  3. Support different step types (tool calls, shell commands, LLM prompts)
  4. Track execution results for evaluation
  5. Provide context passing between steps
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .registry import Skill

log = logging.getLogger("tektos.skill_executor")


# ── Execution Result ────────────────────────────────────────────────────────


@dataclass
class StepResult:
    """Result of executing a single skill step."""

    step_index: int
    action: str
    success: bool
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0


@dataclass
class ExecutionResult:
    """Result of executing a complete skill."""

    skill_id: str
    skill_name: str
    success: bool
    steps_executed: int = 0
    steps_succeeded: int = 0
    steps_failed: int = 0
    step_results: list[StepResult] = field(default_factory=list)
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)


# ── Skill Executor ──────────────────────────────────────────────────────────


class SkillExecutor:
    """Executes skill steps with full lifecycle management.

    Supports step types:
    - tool_call: Call a registered tool
    - shell: Execute a shell command
    - llm_prompt: Send a prompt to the LLM
    - noop: No operation (placeholder)
    - conditional: Conditional execution based on context
    - loop: Loop over items

    Attributes:
        runtime_sdk: RuntimeSDK for tool calls and LLM interaction.
        event_bus: Event bus for emitting execution events.
    """

    def __init__(
        self,
        runtime_sdk: Any = None,
        event_bus: Any = None,
        tool_registry: Any = None,
    ) -> None:
        self.runtime_sdk = runtime_sdk
        self.event_bus = event_bus
        self.tool_registry = tool_registry

    async def execute(
        self,
        skill: Skill,
        context: dict[str, Any],
        max_steps: int = 50,
    ) -> ExecutionResult:
        """Execute a skill's steps.

        Args:
            skill: The skill to execute.
            context: Execution context (tools, session info, etc.).
            max_steps: Maximum number of steps to execute.

        Returns:
            ExecutionResult with full details.
        """
        start = datetime.now(timezone.utc)
        result = ExecutionResult(
            skill_id=skill.id,
            skill_name=skill.name,
            success=False,
            context=dict(context),
        )

        log.info("[EXECUTOR] Starting skill: %s (%d steps)", skill.name, len(skill.steps))

        # Emit start event
        await self._emit_event(
            skill.id,
            "execution.started",
            {
                "skill_name": skill.name,
                "steps_count": len(skill.steps),
            },
        )

        # Execute steps in order
        for i, step in enumerate(skill.steps[:max_steps]):
            step_start = datetime.now(timezone.utc)
            action = step.get("action", step.get("type", "noop"))

            try:
                step_result = await self._execute_step(step, context, i)
                step_result.duration_ms = (
                    datetime.now(timezone.utc) - step_start
                ).total_seconds() * 1000
                result.step_results.append(step_result)
                result.steps_executed += 1

                if step_result.success:
                    result.steps_succeeded += 1
                    # Update context with step output for subsequent steps
                    if step_result.output:
                        context[f"step_{i}_output"] = step_result.output
                else:
                    result.steps_failed += 1
                    log.warning(
                        "[EXECUTOR] Step %d failed in skill %s: %s",
                        i,
                        skill.name,
                        step_result.error,
                    )
                    # On failure, stop execution (fail-fast)
                    break

            except Exception as e:
                result.step_results.append(
                    StepResult(
                        step_index=i,
                        action=action,
                        success=False,
                        error=str(e),
                    )
                )
                result.steps_executed += 1
                result.steps_failed += 1
                log.exception("[EXECUTOR] Exception in step %d of skill %s", i, skill.name)
                break

        # Determine overall success
        result.success = result.steps_failed == 0 and result.steps_executed > 0
        result.output = "\n".join(sr.output for sr in result.step_results if sr.output)
        result.error = (
            result.step_results[-1].error if result.step_results and not result.success else ""
        )
        result.duration_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000

        # Emit completion event
        await self._emit_event(
            skill.id,
            "execution.complete",
            {
                "skill_name": skill.name,
                "success": result.success,
                "steps_executed": result.steps_executed,
                "steps_succeeded": result.steps_succeeded,
                "steps_failed": result.steps_failed,
                "duration_ms": result.duration_ms,
            },
        )

        log.info(
            "[EXECUTOR] Skill %s: %s (%d/%d steps succeeded, %.0fms)",
            skill.name,
            "SUCCESS" if result.success else "FAILED",
            result.steps_succeeded,
            result.steps_executed,
            result.duration_ms,
        )

        return result

    async def _execute_step(
        self,
        step: dict[str, Any],
        context: dict[str, Any],
        index: int,
    ) -> StepResult:
        """Execute a single step."""
        action = step.get("action", step.get("type", "noop"))
        target = step.get("target", step.get("tool", ""))
        args = step.get("args", step.get("parameters", {}))
        description = step.get("description", "")

        if action == "tool_call":
            return await self._execute_tool_call(target, args, context)
        elif action == "shell":
            return await self._execute_shell(target, args, context)
        elif action == "llm_prompt":
            return await self._execute_llm_prompt(target, args, context)
        elif action == "noop":
            return StepResult(step_index=index, action="noop", success=True)
        elif action == "conditional":
            return await self._execute_conditional(step, context, index)
        elif action == "loop":
            return await self._execute_loop(step, context, index)
        else:
            # Unknown action — treat as informational
            return StepResult(
                step_index=index,
                action=action,
                success=True,
                output=f"[INFO] Step {index}: {description}",
            )

    async def _execute_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        context: dict[str, Any],
    ) -> StepResult:
        """Execute a tool call."""
        try:
            if self.tool_registry:
                tool = self.tool_registry.get_tool(tool_name)
                if tool:
                    result = await tool(**args)
                    return StepResult(
                        step_index=0,
                        action="tool_call",
                        success=True,
                        output=str(result),
                    )

            if self.runtime_sdk:
                # Fallback: use runtime SDK's tool execution
                result = await self.runtime_sdk.execute_tool(tool_name, args)
                return StepResult(
                    step_index=0,
                    action="tool_call",
                    success=True,
                    output=str(result),
                )

            return StepResult(
                step_index=0,
                action="tool_call",
                success=False,
                error=f"Tool {tool_name} not available",
            )

        except Exception as e:
            return StepResult(
                step_index=0,
                action="tool_call",
                success=False,
                error=str(e),
            )

    async def _execute_shell(
        self,
        command: str,
        args: dict[str, Any],
        context: dict[str, Any],
    ) -> StepResult:
        """Execute a shell command."""
        try:
            timeout = args.get("timeout", 60)
            cwd = args.get("cwd", context.get("cwd", "."))

            result = await asyncio.wait_for(
                asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                ),
                timeout=timeout,
            )

            stdout, stderr = await result.communicate()
            output = stdout.decode("utf-8", errors="replace")

            if result.returncode == 0:
                return StepResult(
                    step_index=0,
                    action="shell",
                    success=True,
                    output=output,
                )
            else:
                return StepResult(
                    step_index=0,
                    action="shell",
                    success=False,
                    output=output,
                    error=stderr.decode("utf-8", errors="replace"),
                )

        except asyncio.TimeoutError:
            return StepResult(
                step_index=0,
                action="shell",
                success=False,
                error=f"Command timed out after {args.get('timeout', 60)}s",
            )
        except Exception as e:
            return StepResult(
                step_index=0,
                action="shell",
                success=False,
                error=str(e),
            )

    async def _execute_llm_prompt(
        self,
        prompt: str,
        args: dict[str, Any],
        context: dict[str, Any],
    ) -> StepResult:
        """Send a prompt to the LLM."""
        try:
            if self.runtime_sdk:
                messages = args.get("messages", [{"role": "user", "content": prompt}])
                result = await self.runtime_sdk.chat(messages)
                return StepResult(
                    step_index=0,
                    action="llm_prompt",
                    success=True,
                    output=str(result),
                )

            return StepResult(
                step_index=0,
                action="llm_prompt",
                success=False,
                error="Runtime SDK not available for LLM calls",
            )

        except Exception as e:
            return StepResult(
                step_index=0,
                action="llm_prompt",
                success=False,
                error=str(e),
            )

    async def _execute_conditional(
        self,
        step: dict[str, Any],
        context: dict[str, Any],
        index: int,
    ) -> StepResult:
        """Execute a conditional step."""
        condition = step.get("condition", "")
        if_true = step.get("if_true", [])
        if_false = step.get("if_false", [])

        # Evaluate condition against context
        condition_met = self._evaluate_condition(condition, context)

        steps_to_execute = if_true if condition_met else if_false

        if not steps_to_execute:
            return StepResult(
                step_index=index,
                action="conditional",
                success=True,
                output=f"Condition '{condition}' {'met' if condition_met else 'not met'} — no steps to execute",
            )

        # Execute the selected steps
        for sub_step in steps_to_execute:
            sub_result = await self._execute_step(sub_step, context, index)
            if not sub_result.success:
                return StepResult(
                    step_index=index,
                    action="conditional",
                    success=False,
                    error=f"Sub-step failed: {sub_result.error}",
                )

        return StepResult(
            step_index=index,
            action="conditional",
            success=True,
            output=f"Condition '{condition}' {'met' if condition_met else 'not met'}",
        )

    async def _execute_loop(
        self,
        step: dict[str, Any],
        context: dict[str, Any],
        index: int,
    ) -> StepResult:
        """Execute a loop step."""
        items = step.get("items", [])
        template = step.get("template", {})
        max_iterations = step.get("max_iterations", 10)

        results = []
        for i, item in enumerate(items[:max_iterations]):
            # Substitute item into template
            sub_step = dict(template)
            sub_step["args"] = {
                k: v.replace("{item}", str(item)).replace("{i}", str(i))
                for k, v in template.get("args", {}).items()
            }
            sub_step["args"]["item"] = item
            sub_step["args"]["index"] = i

            sub_result = await self._execute_step(sub_step, context, index)
            results.append(sub_result)

            if not sub_result.success:
                return StepResult(
                    step_index=index,
                    action="loop",
                    success=False,
                    error=f"Iteration {i} failed: {sub_result.error}",
                )

        return StepResult(
            step_index=index,
            action="loop",
            success=True,
            output=f"Loop completed: {len(results)} iterations",
        )

    def _evaluate_condition(
        self,
        condition: str,
        context: dict[str, Any],
    ) -> bool:
        """Evaluate a condition string against context.

        Supports simple conditions:
        - "key in context" → context.get("key") is truthy
        - "key == value" → context.get("key") == value
        - "key != value" → context.get("key") != value
        - "key > value" → numeric comparison
        - "key < value" → numeric comparison
        """
        condition = condition.strip()

        # Check for comparison operators
        for op in ("==", "!=", ">", "<", ">=", "<="):
            if op in condition:
                parts = condition.split(op, 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip().strip("'\"")
                    ctx_value = context.get(key)
                    if ctx_value is None:
                        return False
                    try:
                        if op == "==":
                            return str(ctx_value) == value
                        elif op == "!=":
                            return str(ctx_value) != value
                        elif op == ">":
                            return float(ctx_value) > float(value)
                        elif op == "<":
                            return float(ctx_value) < float(value)
                        elif op == ">=":
                            return float(ctx_value) >= float(value)
                        elif op == "<=":
                            return float(ctx_value) <= float(value)
                    except (ValueError, TypeError):
                        return False

        # Simple truthiness check
        value = context.get(condition)
        return bool(value) if value is not None else False

    async def _emit_event(
        self,
        skill_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Emit an execution event."""
        if self.event_bus:
            try:
                self.event_bus.emit(
                    f"skill.{event_type}",
                    {
                        "skill_id": skill_id,
                        **data,
                    },
                )
            except Exception as e:
                log.warning("Failed to emit skill event: %s", e)
