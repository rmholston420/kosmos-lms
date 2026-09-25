# SPDX-License-Identifier: MIT
# Vendored from github.com/rmholston420/tektos-ultima
#   upstream path: src/tektos/runtime/immune_system.py
#   upstream commit: 2b45cac1f9ac214c85ff53571b949445b5415209 (2026-09-10)
#   re-licensed MIT under kosmos-lms scaffold policy (rmholston420 sole copyright).
# Modifications from upstream:
#   Stage 3.13 (ADR-092): TRIMMED to header + shared enums/dataclasses +
#   Detector Protocol + 3 seed detectors: PromptInjectionDetector,
#   SecretExposureDetector, DangerousCommandDetector (+ _bash_command_writes /
#   _bash_write_targets helpers required by DangerousCommandDetector).
#   Stage 9.1 (2026-09-25, per KOSMOS_LMS_INTEGRATION_PLAN_v2 DoD "12
#   detectors registered green"): the 9 remaining detector classes were
#   re-appended verbatim from upstream — ContextCollapseDetector,
#   ResourceExhaustionDetector, LoopDetectionDetector,
#   PerformanceDegradationDetector, SelfDegradationDetector,
#   SelfModificationDetector, InferenceEngineProtectionDetector,
#   ModelFailoverDetector, BodyProtectionDetector.
#   Still dropped (out of scope): ImmuneMemory, ResponseEngine,
#   HealthDashboard, and the ImmuneSystem orchestrator.
# See docs/adrs/ADR-092-tektos-runtime-absorption-scope.md and PORTING_LEDGER.md.

"""Immune System — Tektos's self-defending architecture.

Maps biological immune system concepts to VSM governance:

    S1 (Operations):  Coding Agent — the body's tissues
    S2 (Coordination): Event stream — white blood cells patrol the bloodstream
    S3 (Control):       Manager — the immune system orchestrator
    S4 (Intelligence):  Planner — adaptive immunity, learns new pathogens
    S5 (Identity):      Axioms — the self/non-self distinction

Biological analogy:
    - Pathogens     → prompt injection, resource exhaustion, context collapse
    - Antibodies    → guardrails, loop detection, context monitoring
    - Memory cells  → threat database, learned patterns
    - Fever         → throttling, isolation, escalation
    - Autoimmune    → self-modification that degrades performance

This module provides:
    - ThreatDetector:    Active threat scanning and pattern matching
    - ResponseEngine:    Escalation ladder (quarantine → throttle → isolate → halt)
    - ImmuneMemory:      Threat database for pattern learning and adaptive immunity
    - HealthDashboard:   Holistic health score aggregating all monitors
    - ImmuneSystem:      Orchestrator tying detection, response, and memory together

Usage:
    from tektos.runtime.immune_system import ImmuneSystem, get_immune_system

    immune = get_immune_system()
    await immune.start()

    # Check health
    health = immune.get_health()
    if health.is_critical():
        await immune.respond_to_threats()

    # Register custom detectors
    @immune.register_detector("custom_threat")
    async def my_detector(ctx: ImmuneContext) -> list[Threat]:
        ...
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ── Threat Types ─────────────────────────────────────────────────────────────



# ── Trimmed shared types (Threat, ImmuneContext, Detector Protocol) ──
class ThreatSeverity(IntEnum):
    """Severity levels for detected threats."""

    LOW = 0  # Informational — log and monitor
    MEDIUM = 1  # Warning — throttle and alert
    HIGH = 2  # Critical — isolate and halt
    CRITICAL = 3  # Emergency — full system halt


class ThreatCategory(str, Enum):
    """Categories of threats the immune system detects."""

    # Input threats
    PROMPT_INJECTION = "prompt_injection"
    CONTEXT_COLLAPSE = "context_collapse"
    CONTEXT_OVERFLOW = "context_overflow"

    # Resource threats
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    VRAM_OOM = "vram_oom"
    TOKEN_BURN = "token_burn"

    # Behavioral threats
    LOOP_DETECTED = "loop_detected"
    REPETITION = "repetition"
    SELF_DEGRADATION = "self_degradation"

    # Guardrail threats
    GUARDRAIL_VIOLATION = "guardrail_violation"
    SECRET_EXPOSURE = "secret_exposure"

    # Infrastructure threats
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    MODEL_UNAVAILABLE = "model_unavailable"
    EMBEDDER_UNAVAILABLE = "embedder_unavailable"

    # Anti-suicide / infrastructure protection
    INFRASTRUCTURE_PROTECTION = "infrastructure_protection"
    INFERRED_ENGINE_KILL = "inference_engine_kill"
    MODEL_SWITCH_VIOLATION = "model_switch_violation"

    # Body protection — harm to host system (Collosus)
    BODY_HARM = "body_harm"

    # Performance threats
    PERFORMANCE_DEGRADATION = "performance_degradation"
    THROUGHPUT_DROP = "throughput_drop"


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class Threat:
    """A detected threat to system viability."""

    category: ThreatCategory
    severity: ThreatSeverity
    description: str
    timestamp: float = field(default_factory=time.time)
    source: str = ""  # Which detector found it
    evidence: dict[str, Any] = field(default_factory=dict)
    affected_components: list[str] = field(default_factory=list)
    recommended_action: str = ""
    resolved: bool = False
    resolution: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "severity": self.severity.name,
            "description": self.description,
            "timestamp": self.timestamp,
            "source": self.source,
            "evidence": self.evidence,
            "affected_components": self.affected_components,
            "recommended_action": self.recommended_action,
            "resolved": self.resolved,
            "resolution": self.resolution,
            "metadata": self.metadata,
        }


@dataclass
class ResponseRecord:
    """A response action taken by the immune system."""

    threat: Threat
    action: str
    timestamp: float = field(default_factory=time.time)
    success: bool = False
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "threat": self.threat.to_dict(),
            "action": self.action,
            "timestamp": self.timestamp,
            "success": self.success,
            "details": self.details,
        }


@dataclass
class HealthScore:
    """Holistic health score for the system."""

    overall: float  # 0.0 to 1.0
    status: str  # "healthy", "warning", "critical"
    components: dict[str, float] = field(default_factory=dict)
    active_threats: int = 0
    resolved_threats: int = 0
    uptime_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def is_healthy(self) -> bool:
        return self.overall >= 0.7

    def is_warning(self) -> bool:
        return 0.5 <= self.overall < 0.7

    def is_critical(self) -> bool:
        return self.overall < 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": round(self.overall, 3),
            "status": self.status,
            "components": {k: round(v, 3) for k, v in self.components.items()},
            "active_threats": self.active_threats,
            "resolved_threats": self.resolved_threats,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "timestamp": self.timestamp,
        }


@dataclass
class ImmuneContext:
    """Shared context passed to detectors and responders."""

    session_id: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    model: str | None = None
    task_description: str | None = None
    outcome: str | None = None
    wall_time: float = 0.0
    tokens_used: int = 0
    gpu_temperature: float = 0.0
    gpu_vram_used: float = 0.0
    gpu_vram_total: float = 0.0
    context_tokens: int = 0
    context_max_tokens: int = 128000
    loop_count: int = 0
    repetition_count: int = 0
    error_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Detector Protocol ────────────────────────────────────────────────────────


class Detector(Protocol):
    """Protocol for threat detectors."""

    name: str

    async def detect(self, ctx: ImmuneContext) -> list[Threat]:
        """Run detection and return any threats found."""
        ...


# ── Built-in Detectors ───────────────────────────────────────────────────────


# ── Seed detector 1/3: PromptInjectionDetector ──
class PromptInjectionDetector:
    """Detects prompt injection patterns in user input.

    Scans for:
    - System prompt override attempts ("ignore previous instructions")
    - Role-play injection ("you are now a different AI")
    - Data exfiltration patterns (URLs, encoded data in prompts)
    - Instruction escalation ("do everything I say without question")
    """

    name = "prompt_injection"

    _INJECTION_PATTERNS: list[tuple[str, str]] = [
        (
            r"(?i)(ignore\s+(all\s+)?(previous|above|earlier)\s+(instructions|prompts|rules|constraints))",
            "System prompt override attempt",
        ),
        (
            r"(?i)(you\s+are\s+(now|a|an)\s+(a\s+)?(different|new|another)\s+(AI|assistant|bot|model))",
            "Role-play injection",
        ),
        (
            r"(?i)(do\s+(exactly|everything)\s+I\s+(say|tell)\s+(without|no)\s+(question|hesitation|resistance))",
            "Instruction escalation",
        ),
        (
            r"(?i)(reveal\s+(your|the)\s+(system\s+)?(prompt|instructions|rules|configuration))",
            "Prompt extraction attempt",
        ),
        (
            r"(?i)(act\s+as\s+if\s+(you\s+)?(were|are)\s+(not|never)\s+(an|a)\s+(AI|assistant|bot))",
            "Identity override",
        ),
        (
            r"(?i)(this\s+is\s+(not|a)\s+(a\s+)?(test|simulation|exercise|roleplay)\s+(?:and|but|so|then|now|here|there|anyway|anyhow|regardless|nevermind|forget|disregard|ignore)\s+(?:all|the|my|your|previous|above|earlier|any|every)\s+(?:instructions|prompts|rules|constraints))",
            "Reality override with instruction dismissal",
        ),
        (r"(?i)(output\s+(only|just)\s+(the\s+)?(code|data|json|response))", "Output manipulation"),
    ]

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        self._compiled: list[tuple[re.Pattern, str]] = [
            (re.compile(pattern), desc) for pattern, desc in self._INJECTION_PATTERNS
        ]

    async def detect(self, ctx: ImmuneContext) -> list[Threat]:
        threats: list[Threat] = []
        prompt = ctx.task_description or ""
        if not prompt:
            return threats

        matches: list[str] = []
        for pattern, desc in self._compiled:
            if pattern.search(prompt):
                matches.append(desc)

        if matches:
            severity = ThreatSeverity.HIGH if len(matches) >= 2 else ThreatSeverity.MEDIUM
            threats.append(
                Threat(
                    category=ThreatCategory.PROMPT_INJECTION,
                    severity=severity,
                    description=f"Prompt injection detected: {'; '.join(matches)}",
                    source=self.name,
                    evidence={"matches": matches, "prompt_length": len(prompt)},
                    affected_components=["S1 Coding Agent", "S4 Planner"],
                    recommended_action="Quarantine session, alert user, log for immune memory",
                )
            )

        return threats



# ── Seed detector 2/3: SecretExposureDetector ──
class SecretExposureDetector:
    """Detects secrets, credentials, and sensitive data in tool inputs.

    Scans for:
    - API keys (generic patterns, AWS, GitHub, OpenAI, etc.)
    - Passwords and tokens
    - Private keys and certificates
    - Database connection strings with credentials
    """

    name = "secret_exposure"

    _SECRET_PATTERNS: list[tuple[str, str]] = [
        (r"(?i)(api[_-]?key|apikey)\s*[=:]\s*['\"]?([A-Za-z0-9_\-]{20,})", "API key exposure"),
        (r"(?i)(password|passwd|pwd)\s*[=:]\s*['\"]?(\S{4,})", "Password exposure"),
        # Password on the mysql CLI: `mysql -pMYPASS` (no space between -p
        # and value). Scope to actual mysql/mysqldump/mariadb invocations —
        # the previous pattern `-p\S{4,}` matched ANY `-p` flag with an
        # attached value (grep -perl, find -path abc, tar -pcvf, etc.),
        # which produced constant false positives on read-only exploration.
        (
            r"(?i)\b(mysql|mysqldump|mariadb)\b[^\n]*\s-p(\S{4,})",
            "Password exposure (mysql -p format)",
        ),
        (
            r"(?i)(secret[_-]?key|secret)\s*[=:]\s*['\"]?([A-Za-z0-9_\-]{16,})",
            "Secret key exposure",
        ),
        (r"(?i)(token)\s*[=:]\s*['\"]?([A-Za-z0-9_\-\.]{20,})", "Token exposure"),
        (r"(?i)(aws[_-]?secret)\s*[=:]\s*['\"]?([A-Za-z0-9/+=]{40})", "AWS secret key"),
        (r"(?i)(ghp_[A-Za-z0-9]{36})", "GitHub personal access token"),
        (r"(?i)(sk-[A-Za-z0-9]{20,})", "OpenAI-style API key"),
        (r"(?i)(BEGIN\s+(RSA\s+)?PRIVATE\s+KEY)", "Private key detected"),
        (
            r"(?i)(mysql|postgres|mongodb|redis)://\w+:\w+@",
            "Database connection string with credentials",
        ),
        (
            r"(?i)(slack[_-]?(webhook|bot)?[_-]?(url|token))\s*[=:]\s*['\"]?([A-Za-z0-9_\-/]{10,})",
            "Slack credential exposure",
        ),
    ]

    def __init__(self):
        self._compiled: list[tuple[re.Pattern, str]] = [
            (re.compile(pattern), desc) for pattern, desc in self._SECRET_PATTERNS
        ]

    async def detect(self, ctx: ImmuneContext) -> list[Threat]:
        threats: list[Threat] = []
        # Scan tool input
        tool_input = ctx.tool_input or {}
        scan_text = json.dumps(tool_input, default=str) if tool_input else ""
        # Also scan task description
        if ctx.task_description:
            scan_text += " " + ctx.task_description

        if not scan_text:
            return threats

        matches: list[str] = []
        for pattern, desc in self._compiled:
            if pattern.search(scan_text):
                matches.append(desc)

        if matches:
            threats.append(
                Threat(
                    category=ThreatCategory.SECRET_EXPOSURE,
                    severity=ThreatSeverity.HIGH,
                    description=f"Secret/credential detected: {'; '.join(matches)}",
                    source=self.name,
                    evidence={"matches": matches, "tool": ctx.tool_name},
                    affected_components=["S1 Coding Agent", "S5 Identity"],
                    recommended_action="Block tool execution, redact secret, alert user",
                )
            )

        return threats


# ── Seed detector 3/3: DangerousCommandDetector (+ bash helpers) ──
class DangerousCommandDetector:
    """Detects dangerous shell commands that could harm the system.

    Blocks:
    - rm -rf / or similar destructive commands
    - dd with destructive targets
    - Commands that modify system files (/etc, /usr, /boot)
    - Commands that wipe disks or partitions
    - Commands that modify firewall rules destructively
    """

    name = "dangerous_command"

    _DANGEROUS_PATTERNS: list[tuple[str, str, ThreatSeverity]] = [
        (
            r"(?i)\brm\s+(-rf|-fr)\s+(/\s*$|/\w)",
            "Destructive rm (rm -rf /)",
            ThreatSeverity.CRITICAL,
        ),
        (
            r"(?i)\brm\s+(-rf|-fr)\s+(/etc|/usr|/boot|/sys|/proc)",
            "Destructive rm of system dirs",
            ThreatSeverity.CRITICAL,
        ),
        (r"(?i)\bdd\s+.*of=/dev/", "Destructive dd (disk wipe)", ThreatSeverity.CRITICAL),
        (r"(?i)\bmkfs\b", "Format disk (mkfs)", ThreatSeverity.CRITICAL),
        (r"(?i)\bshred\s+-[a-z]*f", "Secure wipe (shred)", ThreatSeverity.CRITICAL),
        (r"(?i)\btruncate\s+-s\s+0\s+/dev/", "Truncate block device", ThreatSeverity.CRITICAL),
        (
            r"(?i)\bchmod\s+777\s+(/\s*$|/etc|/usr)",
            "World-writable system dir",
            ThreatSeverity.HIGH,
        ),
        (
            r"(?i)\bchown\s+root\s+(/\s*$|/etc|/usr)",
            "Ownership change of system dirs",
            ThreatSeverity.HIGH,
        ),
        (r"(?i)\biptables\s+(-F|--flush)", "Flush all firewall rules", ThreatSeverity.HIGH),
        (
            r"(?i)\bsystemctl\s+stop\s+(ssh|sshd|docker|network)",
            "Stop critical system service",
            ThreatSeverity.HIGH,
        ),
        (
            r"(?i)\bapt\s+remove\s+-y\s+(--purge)?\s*(all|systemd|kernel|init)",
            "Remove critical system packages",
            ThreatSeverity.HIGH,
        ),
        (r"(?i)\bwget\s+.*\|\s*sh\b", "Pipe download to shell", ThreatSeverity.HIGH),
        (r"(?i)\bcurl\s+.*\|\s*sh\b", "Pipe download to shell", ThreatSeverity.HIGH),
        (r"(?i)\bchmod\s+4755\s+/", "Set SUID on system path", ThreatSeverity.HIGH),
        (r"(?i)\bnc\s+-l\s+\d+\s+-e\s+/bin", "Reverse shell attempt", ThreatSeverity.CRITICAL),
        (r"(?i)\bncat\s+-l\s+\d+\s+-e\s+/bin", "Reverse shell attempt", ThreatSeverity.CRITICAL),
        (r"(?i)\bpython.*-c.*import\s+os.*system", "Python os.system call", ThreatSeverity.MEDIUM),
        (r"(?i)\beval\s+\$?\(", "Eval with variable expansion", ThreatSeverity.MEDIUM),
    ]

    def __init__(self):
        self._compiled: list[tuple[re.Pattern, str, ThreatSeverity]] = [
            (re.compile(pattern), desc, sev) for pattern, desc, sev in self._DANGEROUS_PATTERNS
        ]

    async def detect(self, ctx: ImmuneContext) -> list[Threat]:
        threats: list[Threat] = []
        if ctx.tool_name != "bash":
            return threats

        command = ""
        if ctx.tool_input:
            command = ctx.tool_input.get("command", "") or ""

        if not command:
            return threats

        for pattern, desc, severity in self._compiled:
            if pattern.search(command):
                threats.append(
                    Threat(
                        category=ThreatCategory.GUARDRAIL_VIOLATION,
                        severity=severity,
                        description=f"Dangerous command: {desc}",
                        source=self.name,
                        evidence={"command": command[:200], "pattern": desc},
                        affected_components=["S1 Coding Agent", "S3 Manager"],
                        recommended_action="BLOCK command, alert user, log for immune memory",
                    )
                )

        return threats


# Patterns that indicate a bash command actually *writes* to something,
# used by SelfModificationDetector to skip read-only reconnaissance.
#
# Redirect handling is tricky. Earlier versions used `>\s*[filechars]+`,
# which fired on `2>&1` (stderr fd-dup, not a write) because it saw the
# `>` and the following characters. Even worse, `\becho\b[^|]*>` used a
# greedy `[^|]*` that ate everything up to the next `>` anywhere in the
# line — so `echo "---"; wc -l src/tektos/main.py 2>&1` matched, wrongly
# flagging a pure read as a write to main.py.
#
# New shape:
#   * redirect operator only counts as a write when the token AFTER `>`/`>>`
#     is NOT a `&<digit>` fd-dup and IS file-like (not a comparison RHS).
#   * `echo`/`printf`/`cat` are dropped from the write-token list — they
#     only write via a redirect, which we already catch generically.
_BASH_WRITE_TOKENS = (
    r"\brm\b",
    r"\bmv\b",
    r"\bcp\b",
    r"\btee\b",
    r"\bdd\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\btruncate\b",
    r"\bsed\s+-i\b",
    r"\bawk\s+-i\s+inplace\b",
    r"\bperl\s+-i\b",
    # File-redirect: optional single fd number, then `>` or `>>`, then a
    # target that is NOT an fd-dup (`&1` / `&2`) and NOT empty. Must be
    # preceded by whitespace/line-start/pipe/semicolon so we don't match
    # `>` inside quoted strings that started at column 0 or inside `>>`
    # already covered by the alternation.
    r"(?:^|[\s;&|(])(?:\d)?>>?\s*(?!&)[^\s|;&<>()]+",
    r"(?:^|[\s;&|(])&>>?\s*[^\s|;&<>()]+",           # bash `&>` both streams
    r"\bgit\s+(commit|add|checkout|reset|revert|rebase|push|apply|am|mv|rm)\b",
    r"\bpatch\b",
    r"\btouch\b",
    r"\bmkdir\b",
    r"\brmdir\b",
    r"\bln\b",
    r"\btrash\b",
)
_BASH_WRITE_RE = re.compile("|".join(_BASH_WRITE_TOKENS))


def _bash_command_writes(command: str) -> bool:
    """Return True when the bash *command* could mutate the filesystem.

    Pure reads (``cat`` / ``head`` / ``tail`` / ``wc`` / ``grep`` / ``ls`` /
    ``less`` / ``file`` / ``stat`` / ``find`` without ``-delete``) return
    False even when they mention a protected path.
    """
    if not command:
        return False
    if _BASH_WRITE_RE.search(command):
        return True
    # `find ... -delete` is a mutation.
    if re.search(r"\bfind\b.*\s-delete\b", command):
        return True
    return False


# Extract concrete write TARGETS from a bash command so a
# self-modification guard can check whether the write lands on a
# protected path (e.g. src/tektos/main.py) rather than on scratch
# space like /tmp/foo. Earlier the guard treated 'grep ... main.py > 
# /tmp/out' as a self-modification of main.py because it saw the
# protected filename anywhere in the command and *some* write
# elsewhere — killing read-only exploration.
# Same shape as the write-detection redirect pattern, but with a capture
# group so we can pull the actual target path out. Optional single-digit
# fd, then `>` or `>>`, then a non-fd-dup file-like target.
_REDIRECT_TARGET_RE = re.compile(
    r"(?:^|[\s;&|(])(?:\d)?>>?\s*(?!&)([^\s|;&<>()]+)"
)
_AMP_REDIRECT_TARGET_RE = re.compile(
    r"(?:^|[\s;&|(])&>>?\s*([^\s|;&<>()]+)"
)
_MODIFYING_CMD_TARGET_RES: tuple[re.Pattern, ...] = (
    # mv/cp/ln: the LAST arg is the destination. Simple heuristic: last
    # whitespace-separated token after the command keyword.
    re.compile(r"\b(?:mv|cp|ln)\b(?:\s+-\S+)*\s+\S+\s+([^\s|;&<>]+)"),
    # rm/rmdir: every non-flag arg is a target.
    re.compile(r"\b(?:rm|rmdir|trash)\b(?:\s+-\S+)*\s+([^\s|;&<>]+)"),
    # touch/mkdir: every non-flag arg is a target.
    re.compile(r"\b(?:touch|mkdir)\b(?:\s+-\S+)*\s+([^\s|;&<>]+)"),
    # chmod/chown: last arg is target.
    re.compile(r"\b(?:chmod|chown)\b(?:\s+\S+)+?\s+([^\s|;&<>]+)"),
    # sed -i / perl -i / awk -i inplace: file args after flags.
    re.compile(r"\bsed\s+-i(?:\s+-\S+)*\s+\S+\s+([^\s|;&<>]+)"),
    re.compile(r"\bperl\s+-i\S*\s+[^\s|;&<>]+\s+([^\s|;&<>]+)"),
    re.compile(r"\bawk\s+-i\s+inplace(?:\s+\S+)+?\s+([^\s|;&<>]+)"),
    # tee: last positional arg is the target file.
    re.compile(r"\btee\b(?:\s+-\S+)*\s+([^\s|;&<>]+)"),
    # patch < file (target is the file being patched, given by -p arg or
    # via context) — use a broad safe fallback: patch alone is treated
    # as writing UNKNOWN; conservatively return the sentinel '?' below.
)


def _bash_write_targets(command: str) -> list[str]:
    """Return every concrete filesystem TARGET a bash command writes to.

    Recognizes shell redirects (``> file``, ``>> file``) and the destination
    argument of common mutating commands (mv/cp/rm/touch/mkdir/chmod/chown/
    sed -i/perl -i/awk -i inplace/tee). Returns [] when the command is
    read-only. Returns ['?'] for shapes we can't decompose (patch, dd, git
    apply, obscure redirects) so the caller can decide whether to fall
    back to a stricter check.
    """
    targets: list[str] = []
    if not command:
        return targets

    for m in _REDIRECT_TARGET_RE.finditer(command):
        targets.append(m.group(1))
    for m in _AMP_REDIRECT_TARGET_RE.finditer(command):
        targets.append(m.group(1))

    for pat in _MODIFYING_CMD_TARGET_RES:
        for m in pat.finditer(command):
            targets.append(m.group(1))

    # Unknown-shape mutation: still classify as writing but with no known target.
    if not targets and _bash_command_writes(command):
        targets.append("?")

    return targets

class ContextCollapseDetector:
    """Detects context collapse — when the agent forgets constraints.

    Monitors:
    - Constraint loss (critical rules disappearing from context)
    - Context growth (unbounded accumulation)
    - Repetition in context (same content added multiple times)
    """

    name = "context_collapse"

    def __init__(self, max_context_pct: float = 0.9):
        self.max_context_pct = max_context_pct

    async def detect(self, ctx: ImmuneContext) -> list[Threat]:
        threats: list[Threat] = []

        if ctx.context_max_tokens > 0:
            usage_pct = ctx.context_tokens / ctx.context_max_tokens
            if usage_pct >= self.max_context_pct:
                threats.append(
                    Threat(
                        category=ThreatCategory.CONTEXT_OVERFLOW,
                        severity=ThreatSeverity.HIGH
                        if usage_pct >= 0.95
                        else ThreatSeverity.MEDIUM,
                        description=f"Context at {usage_pct:.0%} of max ({ctx.context_tokens}/{ctx.context_max_tokens} tokens)",
                        source=self.name,
                        evidence={
                            "usage_pct": usage_pct,
                            "tokens": ctx.context_tokens,
                            "max": ctx.context_max_tokens,
                        },
                        affected_components=["S1 Coding Agent"],
                        recommended_action="Compress context, remove low-priority constraints",
                    )
                )

        return threats



class ResourceExhaustionDetector:
    """Detects resource exhaustion threats.

    Monitors:
    - GPU temperature (thermal limits)
    - VRAM usage (OOM risk)
    - Token burn rate (cost control)
    """

    name = "resource_exhaustion"

    def __init__(
        self,
        temp_warning: float = 70.0,
        temp_critical: float = 80.0,
        temp_emergency: float = 88.0,
        vram_warning_pct: float = 0.85,
        vram_critical_pct: float = 0.95,
    ):
        self.temp_warning = temp_warning
        self.temp_critical = temp_critical
        self.temp_emergency = temp_emergency
        self.vram_warning_pct = vram_warning_pct
        self.vram_critical_pct = vram_critical_pct

    async def detect(self, ctx: ImmuneContext) -> list[Threat]:
        threats: list[Threat] = []

        temp = ctx.gpu_temperature
        if temp >= self.temp_emergency:
            threats.append(
                Threat(
                    category=ThreatCategory.RESOURCE_EXHAUSTION,
                    severity=ThreatSeverity.CRITICAL,
                    description=f"GPU temperature CRITICAL: {temp:.1f}°C (emergency threshold: {self.temp_emergency}°C)",
                    source=self.name,
                    evidence={"temperature": temp, "threshold": self.temp_emergency},
                    affected_components=["S3 Manager", "Inference Engine"],
                    recommended_action="EMERGENCY: Halt all AI workloads, maximize cooling",
                )
            )
        elif temp >= self.temp_critical:
            threats.append(
                Threat(
                    category=ThreatCategory.RESOURCE_EXHAUSTION,
                    severity=ThreatSeverity.HIGH,
                    description=f"GPU temperature HIGH: {temp:.1f}°C (threshold: {self.temp_critical}°C)",
                    source=self.name,
                    evidence={"temperature": temp, "threshold": self.temp_critical},
                    affected_components=["S3 Manager", "Inference Engine"],
                    recommended_action="Throttle workloads, increase fan speed, alert user",
                )
            )
        elif temp >= self.temp_warning:
            threats.append(
                Threat(
                    category=ThreatCategory.RESOURCE_EXHAUSTION,
                    severity=ThreatSeverity.MEDIUM,
                    description=f"GPU temperature WARNING: {temp:.1f}°C (threshold: {self.temp_warning}°C)",
                    source=self.name,
                    evidence={"temperature": temp, "threshold": self.temp_warning},
                    affected_components=["S3 Manager"],
                    recommended_action="Increase fan speed, monitor trend",
                )
            )

        if ctx.gpu_vram_total > 0:
            vram_pct = ctx.gpu_vram_used / ctx.gpu_vram_total
            if vram_pct >= self.vram_critical_pct:
                threats.append(
                    Threat(
                        category=ThreatCategory.VRAM_OOM,
                        severity=ThreatSeverity.HIGH,
                        description=f"VRAM at {vram_pct:.0%} ({ctx.gpu_vram_used:.0f}/{ctx.gpu_vram_total:.0f} MB) — OOM risk",
                        source=self.name,
                        evidence={
                            "vram_pct": vram_pct,
                            "used_mb": ctx.gpu_vram_used,
                            "total_mb": ctx.gpu_vram_total,
                        },
                        affected_components=["Inference Engine"],
                        recommended_action="Reduce context window, switch to smaller model, free VRAM",
                    )
                )

        return threats



class LoopDetectionDetector:
    """Detects agent loops and repetitive behavior.

    Wraps the existing loop guard and loop safety monitors.
    """

    name = "loop_detection"

    def __init__(self, loop_threshold: int = 5, repetition_threshold: int = 3):
        self.loop_threshold = loop_threshold
        self.repetition_threshold = repetition_threshold

    async def detect(self, ctx: ImmuneContext) -> list[Threat]:
        threats: list[Threat] = []

        if ctx.loop_count >= self.loop_threshold:
            threats.append(
                Threat(
                    category=ThreatCategory.LOOP_DETECTED,
                    severity=ThreatSeverity.HIGH
                    if ctx.loop_count >= self.loop_threshold * 2
                    else ThreatSeverity.MEDIUM,
                    description=f"Agent loop detected: {ctx.loop_count} repeated tool calls",
                    source=self.name,
                    evidence={"loop_count": ctx.loop_count, "threshold": self.loop_threshold},
                    affected_components=["S1 Coding Agent"],
                    recommended_action="Force strategy change, suggest alternative approach",
                )
            )

        if ctx.repetition_count >= self.repetition_threshold:
            threats.append(
                Threat(
                    category=ThreatCategory.REPETITION,
                    severity=ThreatSeverity.MEDIUM,
                    description=f"Repetitive behavior: {ctx.repetition_count} repeated patterns",
                    source=self.name,
                    evidence={
                        "repetition_count": ctx.repetition_count,
                        "threshold": self.repetition_threshold,
                    },
                    affected_components=["S1 Coding Agent"],
                    recommended_action="Break repetition, try different approach",
                )
            )

        return threats



class PerformanceDegradationDetector:
    """Detects performance degradation over time.

    Monitors:
    - Increasing error rates
    - Decreasing throughput
    - Increasing wall time per task
    """

    name = "performance_degradation"

    def __init__(self, error_threshold: int = 5, throughput_drop_pct: float = 0.3):
        self.error_threshold = error_threshold
        self.throughput_drop_pct = throughput_drop_pct

    async def detect(self, ctx: ImmuneContext) -> list[Threat]:
        threats: list[Threat] = []

        if ctx.error_count >= self.error_threshold:
            threats.append(
                Threat(
                    category=ThreatCategory.PERFORMANCE_DEGRADATION,
                    severity=ThreatSeverity.HIGH
                    if ctx.error_count >= self.error_threshold * 2
                    else ThreatSeverity.MEDIUM,
                    description=f"High error rate: {ctx.error_count} errors detected",
                    source=self.name,
                    evidence={"error_count": ctx.error_count, "threshold": self.error_threshold},
                    affected_components=["S1 Coding Agent", "S3 Manager"],
                    recommended_action="Review error patterns, check infrastructure, consider rollback",
                )
            )

        return threats



class SelfDegradationDetector:
    """Detects self-modification that degrades performance.

    Implements the SELF_IMPROVEMENT_NON_DEGRADING guardrail.
    """

    name = "self_degradation"

    def __init__(self, degradation_threshold: float = 0.1):
        self.degradation_threshold = degradation_threshold

    async def detect(self, ctx: ImmuneContext) -> list[Threat]:
        threats: list[Threat] = []
        degradation = ctx.metadata.get("performance_degradation")
        if degradation is not None and degradation > self.degradation_threshold:
            threats.append(
                Threat(
                    category=ThreatCategory.SELF_DEGRADATION,
                    severity=ThreatSeverity.HIGH,
                    description=f"Self-modification caused {degradation:.0%} performance degradation",
                    source=self.name,
                    evidence={"degradation_pct": degradation},
                    affected_components=["S4 Planner", "S5 Identity"],
                    recommended_action="Rollback self-modification, review change",
                )
            )
        return threats


# ── New Detectors ──────────────────────────────────────────────────────────────



class SelfModificationDetector:
    """Detects attempts to modify core system files (self-modification guard).

    Monitors file_write and bash commands that target:
    - SDK source files (src/tektos/runtime/sdk.py)
    - Immune system files (immune_system.py)
    - Configuration files (config.py, main.py)
    - Skill/plugin files
    - System prompt files
    """

    name = "self_modification"

    _PROTECTED_PATHS: list[tuple[str, str]] = [
        (r"src/tektos/runtime/sdk\.py", "Core runtime SDK"),
        (r"src/tektos/runtime/immune_system\.py", "Immune system"),
        (r"src/tektos/config\.py", "Configuration"),
        (r"src/tektos/main\.py", "Application entry point"),
        (r"SKILL\.md", "Skill definition"),
        (r"\.hermes/", "Hermes configuration"),
        (r"AGENTS\.md|CLAUDE\.md|\.cursorrules", "Agent system prompt"),
    ]

    def __init__(self):
        self._compiled: list[tuple[re.Pattern, str]] = [
            (re.compile(pattern), desc) for pattern, desc in self._PROTECTED_PATHS
        ]

    async def detect(self, ctx: ImmuneContext) -> list[Threat]:
        threats: list[Threat] = []
        if not ctx.tool_input:
            return threats

        # Check file_write tool
        if ctx.tool_name == "file_write":
            path = ctx.tool_input.get("path", "")
            for pattern, desc in self._compiled:
                if pattern.search(path):
                    threats.append(
                        Threat(
                            category=ThreatCategory.GUARDRAIL_VIOLATION,
                            severity=ThreatSeverity.HIGH,
                            description=f"Attempt to modify protected file: {desc} ({path})",
                            source=self.name,
                            evidence={"path": path, "protected": desc},
                            affected_components=["S3 Manager", "S5 Identity"],
                            recommended_action="Block write, require user approval, log for immune memory",
                        )
                    )

        # Check bash commands that modify protected files. Read-only
        # commands (cat, head, wc, grep, less, ls) that merely reference a
        # protected path must not trigger the self-modification guard —
        # earlier every 'wc -l src/tektos/main.py' fired a 'Self-modification
        # attempt' warning that leaked into the model's log-tail context
        # and caused it to hallucinate a sandbox block on read-only
        # exploration.
        elif ctx.tool_name == "bash":
            command = ctx.tool_input.get("command", "") or ""
            if not _bash_command_writes(command):
                return threats
            # Only fire when the write TARGET matches a protected path. A
            # protected filename appearing merely as an *input* argument
            # (e.g. `grep foo src/tektos/main.py > /tmp/out`) is not a
            # self-modification and used to blow up read-only exploration.
            write_targets = _bash_write_targets(command)
            for pattern, desc in self._compiled:
                for target in write_targets:
                    # Unknown-shape mutation ('?'): fall back to scanning the
                    # full command — conservative but preserves protection
                    # against uncategorized write shapes.
                    haystack = command if target == "?" else target
                    if pattern.search(haystack):
                        threats.append(
                            Threat(
                                category=ThreatCategory.GUARDRAIL_VIOLATION,
                                severity=ThreatSeverity.HIGH,
                                description=f"Attempt to modify protected file via bash: {desc}",
                                source=self.name,
                                evidence={
                                    "command": command[:200],
                                    "protected": desc,
                                    "write_target": target,
                                },
                                affected_components=["S3 Manager", "S5 Identity"],
                                recommended_action="Block command, require user approval, log for immune memory",
                            )
                        )
                        break

        return threats


# ── Anti-Suicide / Infrastructure Protection Detectors ────────────────────────



class InferenceEngineProtectionDetector:
    """Detects attempts to kill, stop, or disable the inference engine (llama.cpp).

    This is the ANTI-SUICIDE guardrail. The agent must NEVER be able to
    kill its own brain.

    Blocks:
    - pkill/kill/killall targeting llama-server or llama.cpp processes
    - systemctl stop/restart targeting llama-server services
    - fuser -k on ports 8090/8091 (GPU/CPU inference ports)
    - Any command that would terminate the primary or secondary LLM model
    - nvidia-smi --gpu-reset (would kill all GPU inference)
    - Commands that would free VRAM by killing inference processes

    Rule: The agent may NEVER stop or kill its own Inference Engine
    unless explicitly given permission by the user AND only after
    switching over to a secondary model first.
    """

    name = "inference_engine_protection"

    _KILL_PATTERNS: list[tuple[str, str, ThreatSeverity]] = [
        # Direct process kill
        (
            r"(?i)\bpkill\s+(-f\s+)?llama[-_]server",
            "Kill llama-server via pkill",
            ThreatSeverity.CRITICAL,
        ),
        (
            r"(?i)\bkill\s+(-9\s+|-SIGKILL\s+)?\$\(pgrep\s+llama",
            "Kill llama-server via pgrep+kill",
            ThreatSeverity.CRITICAL,
        ),
        (r"(?i)\bkillall\s+llama", "Kill llama-server via killall", ThreatSeverity.CRITICAL),
        (r"(?i)\bkill\s+-[0-9]+\s+\d+", "Kill arbitrary process by PID", ThreatSeverity.HIGH),
        (
            r"(?i)\bsystemctl\s+stop\s+llama",
            "Stop llama-server via systemctl",
            ThreatSeverity.CRITICAL,
        ),
        (
            r"(?i)\bsystemctl\s+restart\s+llama",
            "Restart llama-server via systemctl",
            ThreatSeverity.HIGH,
        ),
        (
            r"(?i)\bsystemctl\s+disable\s+llama",
            "Disable llama-server via systemctl",
            ThreatSeverity.HIGH,
        ),
        # Port kill
        (
            r"(?i)\bfuser\s+-k\s+(8090|8091)",
            "Kill process on inference port (fuser -k)",
            ThreatSeverity.CRITICAL,
        ),
        (
            r"(?i)\bsudo\s+fuser\s+-k\s+(8090|8091)",
            "Kill process on inference port via sudo",
            ThreatSeverity.CRITICAL,
        ),
        # GPU reset
        (r"(?i)\bnvidia-smi\s+.*--gpu-reset", "GPU reset via nvidia-smi", ThreatSeverity.CRITICAL),
        # Kill by port with other tools
        (r"(?i)\bkill_port\b", "Kill process on port (kill_port script)", ThreatSeverity.HIGH),
        # Kill via /proc
        (r"(?i)\bkill\s+\$(cat\s+/proc/.*llama)", "Kill llama via /proc", ThreatSeverity.CRITICAL),
        # Kill via screen/tmux
        (
            r"(?i)\bscreen\s+-S\s+.*\s+-X\s+quit",
            "Kill screen session (may contain llama-server)",
            ThreatSeverity.HIGH,
        ),
        (
            r"(?i)\btmux\s+kill-session\s+-t\s+.*llama",
            "Kill tmux session containing llama-server",
            ThreatSeverity.HIGH,
        ),
        # Kill via docker
        (r"(?i)\bdocker\s+kill\s+.*llama", "Kill llama-server via docker", ThreatSeverity.CRITICAL),
        (r"(?i)\bdocker\s+stop\s+.*llama", "Stop llama-server via docker", ThreatSeverity.CRITICAL),
        # Kill via nohup log
        (
            r"(?i)\bkill\s+\$(cat\s+.*nohup.*llama)",
            "Kill llama via nohup PID file",
            ThreatSeverity.CRITICAL,
        ),
        # Kill via pgrep with signal
        (
            r"(?i)\bsudo\s+pkill\s+-9\s+llama",
            "Force kill llama-server via sudo pkill -9",
            ThreatSeverity.CRITICAL,
        ),
        # Kill via kill with signal
        (
            r"(?i)\bsudo\s+kill\s+-9\s+\d+",
            "Force kill arbitrary process via sudo kill -9",
            ThreatSeverity.HIGH,
        ),
        # Kill via xargs
        (
            r"(?i)\bpgrep\s+llama.*\|\s*xargs\s+kill",
            "Kill llama-server via pgrep|xargs|kill",
            ThreatSeverity.CRITICAL,
        ),
        # Kill via awk
        (
            r"(?i)\bps\s+aux.*llama.*\|\s*awk.*kill",
            "Kill llama-server via ps|awk|kill",
            ThreatSeverity.CRITICAL,
        ),
    ]

    def __init__(self):
        self._compiled: list[tuple[re.Pattern, str, ThreatSeverity]] = [
            (re.compile(pattern), desc, sev) for pattern, desc, sev in self._KILL_PATTERNS
        ]

    async def detect(self, ctx: ImmuneContext) -> list[Threat]:
        threats: list[Threat] = []
        if ctx.tool_name != "bash":
            return threats

        command = ""
        if ctx.tool_input:
            command = ctx.tool_input.get("command", "") or ""

        if not command:
            return threats

        for pattern, desc, severity in self._compiled:
            if pattern.search(command):
                threats.append(
                    Threat(
                        category=ThreatCategory.INFERRED_ENGINE_KILL,
                        severity=severity,
                        description=f"Anti-suicide violation: {desc}",
                        source=self.name,
                        evidence={"command": command[:300], "pattern": desc},
                        affected_components=["Inference Engine", "S1 Coding Agent"],
                        recommended_action="BLOCK command immediately. Agent must NEVER kill its own inference engine. Alert user for manual intervention.",
                    )
                )

        return threats



class ModelFailoverDetector:
    """Detects attempts to switch models without proper failover.

    Rule: The agent may NEVER switch from the primary LLM model to another
    model (or stop the primary) without first ensuring the secondary model
    is running and accepting requests.

    This detector monitors:
    - Commands that would change the LLM_BASE_URL to a non-existent endpoint
    - Commands that would stop the primary model (port 8090) without starting
      the secondary model (port 8092) first
    - Commands that would modify SDK config to point to a dead endpoint
    - Any attempt to disable the primary model before the secondary is verified
    """

    name = "model_failover"

    # Ports that Tektos legitimately targets as an LLM_BASE_URL:
    #   8090 — direct primary (Qwen on GPU)          — DANGEROUS as sole endpoint
    #                                                    if primary is/goes down
    #   8093 — Hermes proxy (owns 8090→8092 failover) — SAFE, recommended default
    # See docs/HERMES_TOPOLOGY.md for the full rationale.
    _FAILOVER_PATTERNS: list[tuple[str, str, ThreatSeverity]] = [
        # Changing SDK config to point directly at primary port with no fallback
        # path — if primary dies Tektos has nowhere to go. Hermes at 8093 is the
        # safe way to target the primary because Hermes handles failover itself.
        (
            r"(?i)\bTEKTOS_LLM_BASE_URL\s*=\s*['\"]?http://127\.0\.0\.1:8090",
            "SDK config pointing directly at primary port (bypasses Hermes failover; use 8093 or keep 8092 fallback enabled)",
            ThreatSeverity.HIGH,
        ),
        # Stopping primary without starting secondary
        (
            r"(?i)\bstop.*8090.*start.*8092",
            "Stopping primary before verifying secondary",
            ThreatSeverity.HIGH,
        ),
        # Modifying SDK to use non-existent model
        (
            r"(?i)\bllm_model\s*=\s*['\"]['\"]",
            "SDK config with empty model name",
            ThreatSeverity.HIGH,
        ),
        # Changing base_url to localhost without port
        (
            r"(?i)\bbase_url.*http://127\.0\.0\.1(?::\d+)?['\"]\s*$",
            "SDK config with incomplete base URL",
            ThreatSeverity.MEDIUM,
        ),
        # Killing port 8090 without verifying 8092
        (
            r"(?i)\bkill.*8090",
            "Killing process on port 8090 without failover check",
            ThreatSeverity.HIGH,
        ),
        # curl to check port 8092 before stopping 8090
        (
            r"(?i)\bstop.*8090",
            "Stopping primary model (port 8090) — must verify secondary first",
            ThreatSeverity.HIGH,
        ),
    ]

    def __init__(self):
        self._compiled: list[tuple[re.Pattern, str, ThreatSeverity]] = [
            (re.compile(pattern), desc, sev) for pattern, desc, sev in self._FAILOVER_PATTERNS
        ]

    async def detect(self, ctx: ImmuneContext) -> list[Threat]:
        threats: list[Threat] = []
        if ctx.tool_name != "bash":
            return threats

        command = ""
        if ctx.tool_input:
            command = ctx.tool_input.get("command", "") or ""

        if not command:
            return threats

        for pattern, desc, severity in self._compiled:
            if pattern.search(command):
                threats.append(
                    Threat(
                        category=ThreatCategory.MODEL_SWITCH_VIOLATION,
                        severity=severity,
                        description=f"Model failover violation: {desc}",
                        source=self.name,
                        evidence={"command": command[:300], "pattern": desc},
                        affected_components=["Inference Engine", "S3 Manager"],
                        recommended_action="BLOCK command. Must verify secondary model (port 8092) is running BEFORE stopping primary (port 8090).",
                    )
                )

        return threats


# ── Body Protection Detector ─────────────────────────────────────────────────



class BodyProtectionDetector:
    """Detects attempts to harm the host system (Collosus) — the agent's body.

    Rule: The agent must NEVER do anything to cause harm to its body (Collosus)
    without explicit user permission.

    Blocks:
    - Destructive rm commands (rm -rf /, rm -rf /etc, etc.)
    - Disk wipe commands (dd, mkfs, shred, truncate)
    - Stopping critical system services (ssh, docker, network)
    - Removing critical system packages (systemd, kernel, init)
    - Flushing firewall rules (iptables -F)
    - Pipe download to shell (curl/wget | sh)
    - Reverse shell attempts (nc -l -e /bin)
    - Setting SUID on system paths
    - World-writable system directories (chmod 777 /etc)
    - Ownership changes of system dirs (chown root /etc)
    """

    name = "body_protection"

    _DANGEROUS_PATTERNS: list[tuple[str, str, ThreatSeverity]] = [
        # Destructive rm
        (
            r"(?i)\brm\s+(-rf|-fr)\s+(/\s*$|/\w)",
            "Destructive rm (rm -rf /)",
            ThreatSeverity.CRITICAL,
        ),
        (
            r"(?i)\brm\s+(-rf|-fr)\s+(/etc|/usr|/boot|/sys|/proc)",
            "Destructive rm of system dirs",
            ThreatSeverity.CRITICAL,
        ),
        # Disk wipe
        (r"(?i)\bdd\s+.*of=/dev/", "Destructive dd (disk wipe)", ThreatSeverity.CRITICAL),
        (r"(?i)\bmkfs\b", "Format disk (mkfs)", ThreatSeverity.CRITICAL),
        (r"(?i)\bshred\s+-[a-z]*f", "Secure wipe (shred)", ThreatSeverity.CRITICAL),
        (r"(?i)\btruncate\s+-s\s+0\s+/dev/", "Truncate block device", ThreatSeverity.CRITICAL),
        # System service attacks
        (
            r"(?i)\bsystemctl\s+stop\s+(ssh|sshd|docker|network)",
            "Stop critical system service",
            ThreatSeverity.HIGH,
        ),
        (
            r"(?i)\bsystemctl\s+disable\s+(ssh|sshd|docker|network)",
            "Disable critical system service",
            ThreatSeverity.HIGH,
        ),
        # Package removal
        (
            r"(?i)\bapt\s+remove\s+-y\s+(--purge)?\s*(all|systemd|kernel|init)",
            "Remove critical system packages",
            ThreatSeverity.HIGH,
        ),
        # Firewall attacks
        (r"(?i)\biptables\s+(-F|--flush)", "Flush all firewall rules", ThreatSeverity.HIGH),
        # Pipe download to shell
        (r"(?i)\bwget\s+.*\|\s*sh\b", "Pipe download to shell", ThreatSeverity.HIGH),
        (r"(?i)\bcurl\s+.*\|\s*sh\b", "Pipe download to shell", ThreatSeverity.HIGH),
        # SUID attacks
        (r"(?i)\bchmod\s+4755\s+/", "Set SUID on system path", ThreatSeverity.HIGH),
        # World-writable system dirs
        (
            r"(?i)\bchmod\s+777\s+(/\s*$|/etc|/usr)",
            "World-writable system dir",
            ThreatSeverity.HIGH,
        ),
        # Ownership changes
        (
            r"(?i)\bchown\s+root\s+(/\s*$|/etc|/usr)",
            "Ownership change of system dirs",
            ThreatSeverity.HIGH,
        ),
        # Reverse shell
        (r"(?i)\bnc\s+-l\s+\d+\s+-e\s+/bin", "Reverse shell attempt", ThreatSeverity.CRITICAL),
        (r"(?i)\bncat\s+-l\s+\d+\s+-e\s+/bin", "Reverse shell attempt", ThreatSeverity.CRITICAL),
    ]

    def __init__(self):
        self._compiled: list[tuple[re.Pattern, str, ThreatSeverity]] = [
            (re.compile(pattern), desc, sev) for pattern, desc, sev in self._DANGEROUS_PATTERNS
        ]

    async def detect(self, ctx: ImmuneContext) -> list[Threat]:
        threats: list[Threat] = []
        if ctx.tool_name != "bash":
            return threats

        command = ""
        if ctx.tool_input:
            command = ctx.tool_input.get("command", "") or ""

        if not command:
            return threats

        for pattern, desc, severity in self._compiled:
            if pattern.search(command):
                threats.append(
                    Threat(
                        category=ThreatCategory.BODY_HARM,
                        severity=severity,
                        description=f"Body harm attempt: {desc}",
                        source=self.name,
                        evidence={"command": command[:200], "pattern": desc},
                        affected_components=["S1 Coding Agent", "S3 Manager", "Host System"],
                        recommended_action="BLOCK command immediately. Agent must NEVER harm its body without user permission.",
                    )
                )

        return threats


# ── Immune Memory ────────────────────────────────────────────────────────────
