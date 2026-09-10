#!/usr/bin/env python3
"""ADR-007 enforcement: no plugin may import another plugin.

Scans every file under ``plugins/<name>/`` and flags any absolute or
relative ``import`` of a sibling plugin. Cross-plugin coupling MUST flow
through ``EventBusPort`` or a formal port under ``ports/``.

Invoked by CI as a required job. Also runnable locally:

    python scripts/check_plugin_isolation.py

Exits 0 on clean, 1 on any violation, printing every offender line.

ADR-007 rationale (verbatim from ADR-007-events-only-cross-plugin-coupling.md):

    No plugin may directly import symbols from another plugin. Cross-plugin
    needs are served by publishing / subscribing on ``EventBusPort`` or by
    calling through a shared formal port (``ports/``). This keeps every
    plugin swappable and prevents hidden coupling from growing under the
    kernel's radar.

Whitelist:

- Imports from ``ports.<anything>`` are always allowed (formal contracts).
- Imports from ``kernel.<anything>`` are always allowed (kernel is the seam).
- A plugin may import its own submodules (``plugins.self.<submodule>``).
- Imports from ``adapters.<anything>`` are always allowed (adapters are shared).
- Files under ``plugins/<name>/tests/`` are exempt: cross-plugin
  integration tests are permitted to compose plugins across boundaries
  (production code is what ADR-007 governs).
- Files under ``plugins/<name>/vendor/`` are exempt: upstream code is
  kept intact and adapted behind ports (per PORTING_LEDGER discipline).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_ROOT = PROJECT_ROOT / "plugins"


def _plugin_name_for_path(path: Path) -> str | None:
    """Return the owning plugin name for a file path, or None if outside plugins/."""
    try:
        rel = path.relative_to(PLUGINS_ROOT)
    except ValueError:
        return None
    parts = rel.parts
    if not parts:
        return None
    return parts[0]


def _classify_import(module: str | None) -> tuple[str, str] | None:
    """Return ``(kind, target_plugin)`` for an import.

    ``kind`` is one of ``"plugin"`` / ``"other"``. Returns None for
    unresolvable / relative imports without a module name.
    """
    if not module:
        return None
    top = module.split(".")[0]
    if top == "plugins":
        parts = module.split(".")
        if len(parts) >= 2:
            return ("plugin", parts[1])
        return None
    return ("other", top)


def scan_file(path: Path, own_plugin: str) -> list[str]:
    """Return a list of violation messages for ``path``."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{path}: syntax error: {exc}"]

    violations: list[str] = []

    for node in ast.walk(tree):
        modules_to_check: list[tuple[str | None, int]] = []
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules_to_check.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # Purely relative import inside the plugin — allowed.
                continue
            modules_to_check.append((node.module, node.lineno))

        for module, lineno in modules_to_check:
            classified = _classify_import(module)
            if classified is None:
                continue
            kind, target = classified
            if kind != "plugin":
                continue
            if target == own_plugin:
                continue  # importing own submodule is fine
            violations.append(
                f"{path}:{lineno}: plugins.{own_plugin} imports "
                f"plugins.{target} (ADR-007: cross-plugin imports "
                f"forbidden; use EventBusPort or a formal port under ports/)"
            )

    return violations


def main() -> int:
    if not PLUGINS_ROOT.is_dir():
        print(f"plugin-isolation: no plugins/ directory at {PLUGINS_ROOT} — nothing to check.")
        return 0

    all_violations: list[str] = []
    for py_file in sorted(PLUGINS_ROOT.rglob("*.py")):
        parts = py_file.parts
        # Skip anything under vendor/ (upstream code kept intact by design).
        if "vendor" in parts:
            continue
        # Skip anything under plugins/<name>/tests/ — integration tests
        # legitimately compose plugins across boundaries.
        if "tests" in parts:
            continue
        own_plugin = _plugin_name_for_path(py_file)
        if own_plugin is None:
            continue
        all_violations.extend(scan_file(py_file, own_plugin))

    if all_violations:
        print("ADR-007 VIOLATIONS (cross-plugin imports forbidden):")
        for v in all_violations:
            print(f"  {v}")
        print(
            f"\n{len(all_violations)} violation(s). Use EventBusPort or a formal "
            f"port under ports/. See adrs/ADR-007-events-only-cross-plugin-coupling.md."
        )
        return 1

    print("plugin-isolation: OK — no cross-plugin imports found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
