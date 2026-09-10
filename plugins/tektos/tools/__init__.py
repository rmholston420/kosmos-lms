"""plugins.tektos.tools — approval-gated Tektos tool registry (ADR-093 §4)."""

from plugins.tektos.tools.registry import (
    TektosToolRegistry,
    ToolApprovalDenied,
    ToolDescriptor,
    ToolNotFound,
)

__all__ = [
    "TektosToolRegistry",
    "ToolApprovalDenied",
    "ToolDescriptor",
    "ToolNotFound",
]
