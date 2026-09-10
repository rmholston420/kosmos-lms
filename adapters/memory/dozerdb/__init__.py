"""adapters.memory.dozerdb — DozerDB-backed MemoryPort adapter (ADR-027, ADR-047, ADR-048)."""

from adapters.memory.dozerdb.adapter import (
    AlwaysBlockAmgPolicy,
    AlwaysQuarantineAmgPolicy,
    AmgPolicy,
    AmgVerdict,
    DozerDbMemoryAdapter,
    GraphBackend,
    InMemoryGraphBackend,
    InMemoryLexicalIndex,
    InMemoryTemporalIndex,
    LexicalIndex,
    NoOpAmgPolicy,
    RRF_K,
    TemporalIndex,
)
from adapters.memory.dozerdb.amg_policy import AmgGuardPolicy, AmgV02Policy
from adapters.memory.dozerdb.dozerdb_graph_backend import DozerDbGraphBackend

# ADR-075 D1: GraphitiTemporalIndex + KosmosGraphitiEmbedder hard-deleted.
# The `TemporalIndex` port survives; `InMemoryTemporalIndex` is the only
# in-tree implementation. Kernel boot uses it unconditionally.

__all__ = [
    "AlwaysBlockAmgPolicy",
    "AlwaysQuarantineAmgPolicy",
    "AmgGuardPolicy",
    "AmgPolicy",
    "AmgV02Policy",
    "AmgVerdict",
    "DozerDbGraphBackend",
    "DozerDbMemoryAdapter",
    "GraphBackend",
    "InMemoryGraphBackend",
    "InMemoryLexicalIndex",
    "InMemoryTemporalIndex",
    "LexicalIndex",
    "NoOpAmgPolicy",
    "RRF_K",
    "TemporalIndex",
]
