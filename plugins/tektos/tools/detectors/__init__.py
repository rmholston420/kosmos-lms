"""Pre-approval detectors for TektosToolRegistry (Stage 4.8, ADR-094).

Detectors implement the ``Detector`` Protocol from ``ports/immune.py``.
The registry runs them sequentially before ``ApprovalGatewayPort.propose``;
any ``severity="block"`` hit publishes an ``immune.verdict.block`` envelope
+ ``MemoryPort(provenance="immune_verdict", confidence=1.0)`` write +
``tektos.tool.denied`` envelope, and raises a ``ToolApprovalDenied``
subclass.
"""

from __future__ import annotations

from plugins.tektos.tools.detectors.path_traversal import (
    PathTraversalDetected,
    PathTraversalDetector,
)

__all__ = ["PathTraversalDetected", "PathTraversalDetector"]
