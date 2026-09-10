# SPDX-License-Identifier: MIT
# Vendored from github.com/rmholston420/tektos-ultima
#   upstream path: src/tektos/runtime/immune_system.py
#   upstream commit: 2b45cac1f9ac214c85ff53571b949445b5415209 (2026-09-10)
#   re-licensed MIT under kosmos-lms scaffold policy (rmholston420 sole copyright).
# Modifications from upstream:
#   TRIMMED — kept only header + shared enums/dataclasses + Detector Protocol
#   + 3 seed detectors: PromptInjectionDetector, SecretExposureDetector,
#   DangerousCommandDetector (+ _bash_command_writes / _bash_write_targets
#   helpers required by DangerousCommandDetector).
#   Dropped: ResponseRecord, HealthScore, and 9 other detectors
#   (ContextCollapse, ResourceExhaustion, LoopDetection, PerformanceDegradation,
#   SelfDegradation, SelfModification, InferenceEngineProtection, ModelFailover,
#   BodyProtection), ImmuneMemory, ResponseEngine, HealthDashboard, and the
#   ImmuneSystem orchestrator. Those live outside Stage 3.13 scope per ADR-092
#   and are deferred to a follow-up Stage 3.13+n batch.
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


