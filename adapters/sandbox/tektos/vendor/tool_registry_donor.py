"""adapters.sandbox.tektos.vendor.tool_registry_donor — tool descriptor shape.

# SPDX-License-Identifier: MIT
# Vendored from github.com/rmholston420/tektos-ultima
#   upstream path: src/tektos/tools/registry.py
#   upstream commit: 2b45cac1f9ac214c85ff53571b949445b5415209 (2026-09-10)
#   re-licensed MIT under kosmos-lms scaffold policy (rmholston420 sole
#   copyright).
# Modifications from upstream: trimmed from 553 lines to ~140. Kept the
#   ToolDefinition shape (name, description, JSON-schema parameters,
#   handler callable, enabled, timeout) and JSON-schema parameter
#   validation via jsonschema. Dropped: MCPClient integration (Stage 4.8+
#   MCP), REST API surface (/api/tools), direct event emission (kosmos
#   routes envelopes through the formal EventBusPort at the tool-registry
#   layer), call_count / last_call telemetry (redundant with EventBusPort
#   observability), factories that pre-register bash/file/search handlers
#   (kosmos wires those via `TektosToolRegistry.register` at the plugin
#   layer with approval-tier metadata the upstream ToolDefinition lacked).
# See docs/adrs/ADR-093-tektos-sandbox-planner-tools-absorption-scope.md
# and PORTING_LEDGER.md.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger("tektos.tools.vendor")


class ToolDefinitionDonor:
    """Upstream ToolDefinition shape, verbatim minus counters.

    Kosmos does NOT use this class directly at Stage 4.7 — the plugin
    layer subclasses/composes it into ``ToolDescriptor`` with the
    additional ``approval_tier`` + ``network`` fields the upstream
    definition lacked. Kept here so future MCP integration (Stage 4.8+)
    can register upstream-shaped tool definitions without a schema
    translation layer.
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[[dict[str, Any]], Any],
        enabled: bool = True,
        timeout: int = 30,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.enabled = enabled
        self.timeout = timeout

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "enabled": self.enabled,
            "timeout": self.timeout,
        }


class JsonSchemaValidationError(ValueError):
    """Raised by ``validate_arguments`` when arguments don't match the schema."""


def validate_arguments(
    parameters_schema: dict[str, Any],
    arguments: dict[str, Any],
) -> None:
    """Validate ``arguments`` against ``parameters_schema`` (JSON Schema).

    Prefers the ``jsonschema`` package when installed (upstream default);
    falls back to a permissive best-effort check for CI environments
    where ``jsonschema`` isn't pinned. The fallback enforces:

    - ``type == "object"`` at the root
    - every key listed in ``required`` is present
    - keys not in ``properties`` are rejected when
      ``additionalProperties=False``

    That covers every argument shape the Stage 4.7 tool registry
    actually exercises. Full JSON-schema validation kicks in when the
    real ``jsonschema`` dependency is available.
    """

    try:
        import jsonschema  # type: ignore[import-not-found]
    except ImportError:
        _fallback_validate(parameters_schema, arguments)
        return

    try:
        jsonschema.validate(instance=arguments, schema=parameters_schema)
    except jsonschema.ValidationError as exc:  # pragma: no cover - depends on jsonschema
        raise JsonSchemaValidationError(str(exc)) from exc


def _fallback_validate(
    parameters_schema: dict[str, Any],
    arguments: dict[str, Any],
) -> None:
    schema_type = parameters_schema.get("type")
    if schema_type not in (None, "object"):
        raise JsonSchemaValidationError(
            f"root schema type must be 'object' (got {schema_type!r})"
        )
    if not isinstance(arguments, dict):
        raise JsonSchemaValidationError("arguments must be a dict at the root")

    required = parameters_schema.get("required", ())
    for key in required:
        if key not in arguments:
            raise JsonSchemaValidationError(f"missing required argument: {key!r}")

    properties = parameters_schema.get("properties") or {}
    additional_allowed = parameters_schema.get("additionalProperties", True)
    if additional_allowed is False:
        extra = set(arguments) - set(properties)
        if extra:
            raise JsonSchemaValidationError(
                f"unexpected argument(s): {sorted(extra)!r}"
            )


__all__ = [
    "JsonSchemaValidationError",
    "ToolDefinitionDonor",
    "validate_arguments",
]
