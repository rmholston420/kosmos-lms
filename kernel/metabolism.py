"""Tektos-Ultima v1 — Metabolism Layer

Full resource metabolism: VRAM tracking, context budget, power management,
and context compression triggers. Replaces the thin GPU temp check with
a comprehensive resource monitoring system.

Architecture:
  Metabolism (resource monitor)
      ↓
  Event Bus (resource.warning, resource.critical events)
      ↓
  Context Compressor (triggered when budget exceeded)
      ↓
  Power Manager (400W cap, thermal limits)

Design:
- Monitors GPU VRAM, system RAM, disk, context tokens, inference latency
- Tracks per-model VRAM allocation and context usage
- Emits events via event bus when thresholds hit
- Context compression trigger: auto-summarize when near budget
- Power budget: tracks power draw vs 400W cap
- Thermal management: 82°C trigger → 10s cooling, 90°C throttle, 85°C cutoff

Thermal Limits (RTX 5090):
  - Normal: < 70°C
  - Warning: 70-82°C (yellow alert)
  - Cooling trigger: 82°C (10s break, fan boost)
  - Emergency cutoff: 85°C (reduce workload)
  - Hard throttle: 90°C (max power reduction)

Context Budget:
  - Max: 262,144 tokens (256k + headroom)
  - Warning: 80% (209,715 tokens)
  - Critical: 90% (235,930 tokens)
  - Emergency: 95% (249,037 tokens)

VRAM Budget:
  - Max: 32,768 MB (32GB)
  - Warning: 80% (26,214 MB)
  - Critical: 90% (29,491 MB)
  - Emergency: 95% (31,130 MB)

"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

log = logging.getLogger("tektos.metabolism")


# ─── Enums ──────────────────────────────────────────────────────────────────


class ResourceAlert(str, Enum):
    """Resource alert levels."""

    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class ContextAction(str, Enum):
    """Actions to take when context budget exceeded."""

    NONE = "none"
    TRIM = "trim_shortest_messages"
    COMPRESS = "summarize_history"
    REJECT = "reject_new_prompt"


# ─── Data Classes ───────────────────────────────────────────────────────────


@dataclass
class GpuMetrics:
    """GPU metrics from nvidia-smi/NVML."""

    timestamp: str
    temperature: float = 0.0
    utilization: float = 0.0
    vram_total_mb: float = 0.0
    vram_used_mb: float = 0.0
    vram_free_mb: float = 0.0
    power_draw_w: float = 0.0
    power_limit_w: float = 0.0
    fan_speed: float = 0.0
    clock_graphics: float = 0.0
    clock_memory: float = 0.0
    process_count: int = 0

    @property
    def vram_pct(self) -> float:
        if self.vram_total_mb <= 0:
            return 0.0
        return (self.vram_used_mb / self.vram_total_mb) * 100

    @property
    def power_pct(self) -> float:
        if self.power_limit_w <= 0:
            return 0.0
        return (self.power_draw_w / self.power_limit_w) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "temperature": round(self.temperature, 1),
            "utilization": round(self.utilization, 1),
            "vram_total_mb": round(self.vram_total_mb, 0),
            "vram_used_mb": round(self.vram_used_mb, 0),
            "vram_free_mb": round(self.vram_free_mb, 0),
            "vram_pct": round(self.vram_pct, 1),
            "power_draw_w": round(self.power_draw_w, 1),
            "power_limit_w": round(self.power_limit_w, 1),
            "power_pct": round(self.power_pct, 1),
            "fan_speed": round(self.fan_speed, 0),
            "clock_graphics": round(self.clock_graphics, 0),
            "clock_memory": round(self.clock_memory, 0),
            "process_count": self.process_count,
        }


@dataclass
class SystemMetrics:
    """System-level metrics."""

    timestamp: str
    cpu_percent: float = 0.0
    memory_total_mb: float = 0.0
    memory_used_mb: float = 0.0
    memory_free_mb: float = 0.0
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    disk_free_gb: float = 0.0
    uptime_seconds: float = 0.0

    @property
    def memory_pct(self) -> float:
        if self.memory_total_mb <= 0:
            return 0.0
        return (self.memory_used_mb / self.memory_total_mb) * 100

    @property
    def disk_pct(self) -> float:
        if self.disk_total_gb <= 0:
            return 0.0
        return (self.disk_used_gb / self.disk_total_gb) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "cpu_percent": round(self.cpu_percent, 1),
            "memory_total_mb": round(self.memory_total_mb, 0),
            "memory_used_mb": round(self.memory_used_mb, 0),
            "memory_free_mb": round(self.memory_free_mb, 0),
            "memory_pct": round(self.memory_pct, 1),
            "disk_total_gb": round(self.disk_total_gb, 1),
            "disk_used_gb": round(self.disk_used_gb, 1),
            "disk_free_gb": round(self.disk_free_gb, 1),
            "disk_pct": round(self.disk_pct, 1),
            "uptime_seconds": round(self.uptime_seconds, 0),
        }


@dataclass
class ContextBudget:
    """Context window budget tracking."""

    max_tokens: int = 262144  # 256k + headroom
    current_tokens: int = 0
    warning_threshold_pct: float = 80.0
    critical_threshold_pct: float = 90.0
    emergency_threshold_pct: float = 95.0

    @property
    def pct(self) -> float:
        if self.max_tokens <= 0:
            return 0.0
        return (self.current_tokens / self.max_tokens) * 100

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self.current_tokens)

    @property
    def alert_level(self) -> ResourceAlert:
        if self.pct >= self.emergency_threshold_pct:
            return ResourceAlert.EMERGENCY
        if self.pct >= self.critical_threshold_pct:
            return ResourceAlert.CRITICAL
        if self.pct >= self.warning_threshold_pct:
            return ResourceAlert.WARNING
        return ResourceAlert.NORMAL

    @property
    def recommended_action(self) -> ContextAction:
        if self.alert_level == ResourceAlert.EMERGENCY:
            return ContextAction.REJECT
        if self.alert_level == ResourceAlert.CRITICAL:
            return ContextAction.COMPRESS
        if self.alert_level == ResourceAlert.WARNING:
            return ContextAction.TRIM
        return ContextAction.NONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_tokens": self.current_tokens,
            "max_tokens": self.max_tokens,
            "pct": round(self.pct, 1),
            "remaining_tokens": self.remaining_tokens,
            "alert_level": self.alert_level.value,
            "recommended_action": self.recommended_action.value,
            "warning_threshold": self.warning_threshold_pct,
            "critical_threshold": self.critical_threshold_pct,
            "emergency_threshold": self.emergency_threshold_pct,
        }


@dataclass
class MetabolismState:
    """Complete metabolism state snapshot."""

    timestamp: str
    gpu: GpuMetrics | None = None
    system: SystemMetrics | None = None
    context_budget: ContextBudget | None = None
    inference_latency_ms: float = 0.0
    tokens_per_second: float = 0.0
    active_sessions: int = 0
    total_tool_calls: int = 0
    overall_health: ResourceAlert = ResourceAlert.NORMAL

    def to_dict(self) -> dict[str, Any]:
        result = {
            "timestamp": self.timestamp,
            "overall_health": self.overall_health.value,
            "inference_latency_ms": round(self.inference_latency_ms, 1),
            "tokens_per_second": round(self.tokens_per_second, 1),
            "active_sessions": self.active_sessions,
            "total_tool_calls": self.total_tool_calls,
        }
        if self.gpu:
            result["gpu"] = self.gpu.to_dict()
        if self.system:
            result["system"] = self.system.to_dict()
        if self.context_budget:
            result["context_budget"] = self.context_budget.to_dict()
        return result


# ─── Metabolism Engine ──────────────────────────────────────────────────────


class MetabolismEngine:
    """Resource metabolism engine.

    Monitors GPU VRAM, system resources, context budget, and inference metrics.
    Emits alerts via event bus when thresholds are exceeded.
    """

    # Thermal limits for RTX 5090
    THERMAL_WARNING = 70.0
    THERMAL_COOLING = 82.0
    THERMAL_EMERGENCY = 85.0
    THERMAL_THROTTLE = 90.0

    def __init__(
        self,
        event_bus: Any = None,
        max_tokens: int = 262144,
        vram_warning_pct: float = 80.0,
        power_limit_w: float = 400.0,
    ):
        self.event_bus = event_bus
        self.max_tokens = max_tokens
        self.power_limit_w = power_limit_w
        self._last_gpu_alert: ResourceAlert = ResourceAlert.NORMAL
        self._last_temp_alert: ResourceAlert = ResourceAlert.NORMAL
        self._last_context_alert: ResourceAlert = ResourceAlert.NORMAL
        self._start_time = time.time()
        self._token_count = 0
        self._tool_call_count = 0
        self._session_count = 0
        self._metrics_history: list[dict[str, Any]] = []
        self._max_history = 1000

    # ─── GPU Metrics ────────────────────────────────────────────────────

    def get_gpu_metrics(self) -> GpuMetrics:
        """Get current GPU metrics via nvidia-smi."""
        try:
            return self._query_nvidia_smi()
        except Exception as e:
            log.warning(f"Failed to query GPU metrics: {e}")
            return GpuMetrics(timestamp=datetime.now(timezone.utc).isoformat())

    def _query_nvidia_smi(self) -> GpuMetrics:
        """Parse nvidia-smi output for GPU metrics."""
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    # NOTE: 'used_gpus' was in the original field list but is
                    # not a valid nvidia-smi query key; it caused every query
                    # to return non-zero exit status, spamming
                    # 'nvidia-smi query failed' warnings and making
                    # get_gpu_metrics always return defaults. Drop it — the
                    # code below indexes fields[0..8] which stay stable.
                    "--query-gpu=temperature.gpu,power.draw,power.limit,fan.speed,"
                    "utilization.gpu,clocks.current.graphics,clocks.current.memory,"
                    "memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise ValueError(f"nvidia-smi failed: {result.stderr}")

            line = result.stdout.strip()
            if not line:
                raise ValueError("Empty nvidia-smi output")

            fields = [f.strip() for f in line.split(",")]
            if len(fields) < 9:
                raise ValueError(f"Unexpected nvidia-smi fields: {fields}")

            timestamp = datetime.now(timezone.utc).isoformat()
            return GpuMetrics(
                timestamp=timestamp,
                temperature=float(fields[0]),
                power_draw_w=float(fields[1]),
                power_limit_w=float(fields[2]),
                fan_speed=float(fields[3]) if fields[3] != "N/A" else 0.0,
                utilization=float(fields[4]),
                clock_graphics=float(fields[5]) if fields[5] != "N/A" else 0.0,
                clock_memory=float(fields[6]) if fields[6] != "N/A" else 0.0,
                vram_used_mb=float(fields[7]),
                vram_total_mb=float(fields[8]),
            )
        except FileNotFoundError:
            log.warning("nvidia-smi not found — GPU metrics unavailable")
            return GpuMetrics(timestamp=datetime.now(timezone.utc).isoformat())
        except Exception as e:
            log.warning(f"nvidia-smi query failed: {e}")
            return GpuMetrics(timestamp=datetime.now(timezone.utc).isoformat())

    # ─── System Metrics ─────────────────────────────────────────────────

    def get_system_metrics(self) -> SystemMetrics:
        """Get current system metrics."""
        timestamp = datetime.now(timezone.utc).isoformat()

        # CPU + Memory from /proc
        cpu_percent = self._get_cpu_percent()
        mem = self._get_memory()
        disk = self._get_disk()

        return SystemMetrics(
            timestamp=timestamp,
            cpu_percent=cpu_percent,
            memory_total_mb=mem["total"],
            memory_used_mb=mem["used"],
            memory_free_mb=mem["free"],
            disk_total_gb=disk["total"],
            disk_used_gb=disk["used"],
            disk_free_gb=disk["free"],
            uptime_seconds=time.time() - self._start_time,
        )

    def _get_cpu_percent(self) -> float:
        """Get CPU percent from /proc/stat."""
        try:
            with open("/proc/stat") as f:
                line = f.readline()
            parts = line.split()
            # user, nice, system, idle, iowait, irq, softirq, steal
            values = [int(v) for v in parts[1:5]]
            total = sum(values)
            idle = values[3] + values[4]  # idle + iowait
            return round(((total - idle) / total) * 100, 1) if total > 0 else 0.0
        except Exception:
            return 0.0

    def _get_memory(self) -> dict[str, float]:
        """Get memory from /proc/meminfo."""
        try:
            meminfo = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        key = parts[0].rstrip(":")
                        value = int(parts[1])  # kB
                        meminfo[key] = value
            total = meminfo.get("MemTotal", 0)
            free = meminfo.get("MemFree", 0)
            buffers = meminfo.get("Buffers", 0)
            cached = meminfo.get("Cached", 0)
            available = meminfo.get("MemAvailable", 0)
            used = total - available if available > 0 else total - free - buffers - cached
            return {
                "total": round(total / 1024, 0),  # kB → MB
                "used": round(used / 1024, 0),
                "free": round(available / 1024, 0),
            }
        except Exception:
            return {"total": 0, "used": 0, "free": 0}

    def _get_disk(self) -> dict[str, float]:
        """Get disk usage from os.statvfs."""
        try:
            stat = os.statvfs("/")
            total = stat.f_blocks * stat.f_frsize
            free = stat.f_bfree * stat.f_frsize
            used = total - free
            return {
                "total": round(total / (1024**3), 1),  # bytes → GB
                "used": round(used / (1024**3), 1),
                "free": round(free / (1024**3), 1),
            }
        except Exception:
            return {"total": 0, "used": 0, "free": 0}

    # ─── Context Budget ─────────────────────────────────────────────────

    def update_context_budget(self, current_tokens: int) -> ContextBudget:
        """Update context token count and check thresholds."""
        self._token_count = current_tokens
        budget = ContextBudget(
            max_tokens=self.max_tokens,
            current_tokens=current_tokens,
        )

        # Check alert level
        if budget.alert_level != self._last_context_alert:
            alert_name = budget.alert_level.value
            log.warning(f"Context budget alert: {alert_name} ({budget.pct:.1f}%)")
            if self.event_bus:
                self.event_bus.publish(
                    f"context.{alert_name}",
                    "metabolism",
                    budget.to_dict(),
                )
                self.event_bus.publish(
                    "resource.warning",
                    "metabolism",
                    {
                        "type": "context_budget",
                        "level": alert_name,
                        "tokens": current_tokens,
                        "max": self.max_tokens,
                        "pct": round(budget.pct, 1),
                        "action": budget.recommended_action.value,
                    },
                )
            self._last_context_alert = budget.alert_level

        return budget

    # ─── Resource Assessment ────────────────────────────────────────────

    def assess_health(self) -> MetabolismState:
        """Full resource assessment — combines all metrics into one snapshot."""
        timestamp = datetime.now(timezone.utc).isoformat()
        gpu = self.get_gpu_metrics()
        system = self.get_system_metrics()

        # Determine overall health
        alerts = []
        if gpu.temperature >= self.THERMAL_THROTTLE:
            alerts.append(ResourceAlert.EMERGENCY)
        elif gpu.temperature >= self.THERMAL_EMERGENCY:
            alerts.append(ResourceAlert.CRITICAL)
        elif gpu.temperature >= self.THERMAL_COOLING or gpu.temperature >= self.THERMAL_WARNING:
            alerts.append(ResourceAlert.WARNING)

        # VRAM check
        if gpu.vram_pct >= 90:
            alerts.append(ResourceAlert.CRITICAL)
        elif gpu.vram_pct >= 80:
            alerts.append(ResourceAlert.WARNING)

        # Power check
        if gpu.power_draw_w >= self.power_limit_w * 0.95:
            alerts.append(ResourceAlert.WARNING)

        # Disk check
        if system.disk_pct >= 90:
            alerts.append(ResourceAlert.CRITICAL)
        elif system.disk_pct >= 80:
            alerts.append(ResourceAlert.WARNING)

        # Overall health = worst alert
        if ResourceAlert.EMERGENCY in alerts:
            health = ResourceAlert.EMERGENCY
        elif ResourceAlert.CRITICAL in alerts:
            health = ResourceAlert.CRITICAL
        elif ResourceAlert.WARNING in alerts:
            health = ResourceAlert.WARNING
        else:
            health = ResourceAlert.NORMAL

        # Emit overall health event if changed
        if health != self._last_gpu_alert:
            if self.event_bus:
                self.event_bus.publish(
                    "resource.health",
                    "metabolism",
                    {"level": health.value, "alerts": [a.value for a in alerts]},
                )
            self._last_gpu_alert = health

        state = MetabolismState(
            timestamp=timestamp,
            gpu=gpu,
            system=system,
            context_budget=ContextBudget(
                max_tokens=self.max_tokens,
                current_tokens=self._token_count,
            ),
            active_sessions=self._session_count,
            total_tool_calls=self._tool_call_count,
            overall_health=health,
        )

        # Keep metrics history
        self._metrics_history.append(state.to_dict())
        if len(self._metrics_history) > self._max_history:
            self._metrics_history = self._metrics_history[-self._max_history :]

        return state

    # ─── Lifecycle ──────────────────────────────────────────────────────

    def record_tool_call(self) -> None:
        """Track a tool call for efficiency metrics."""
        self._tool_call_count += 1

    def update_session_count(self, count: int) -> None:
        """Update active session count."""
        self._session_count = count

    def record_tokens(self, token_count: int) -> None:
        """Record tokens for efficiency metrics."""
        self._token_count += token_count

    def get_stats(self) -> dict[str, Any]:
        """Get metabolism engine statistics."""
        return {
            "max_tokens": self.max_tokens,
            "current_tokens": self._token_count,
            "token_pct": round((self._token_count / self.max_tokens) * 100, 1)
            if self.max_tokens > 0
            else 0,
            "tool_calls": self._tool_call_count,
            "sessions": self._session_count,
            "metrics_history_count": len(self._metrics_history),
        }

    def get_metrics_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent metrics history."""
        return self._metrics_history[-limit:]
