"""Schema evolution engine — generic DB introspection/evolution substrate (ADR-141 T8c-9).

Donor provenance: tektos-ultima-v1 ``src/tektos/migrations/schema_evolution.py``
(758 LOC) ported VERBATIM — the one external import
(``tektos.utils.db_utils.escape_sql_identifier``) is inlined below (helper
verbatim from the donor's ``src/tektos/utils/db_utils.py:13-76``).

Layering decision (user's governing rule): schema introspection/evolution is
GENERIC shared infrastructure (any SQLite store, threat-model-agnostic) →
kernel-level, same class as ``kernel/tektos_telemetry.py`` /
``kernel/evaluation_framework.py``. ADR-007: no plugin imports.

ADR-141 disposition: serves the P route ``GET /api/schema`` (donor
main.py:4747) NOW; the 3 Stage 13.1 D routes (``/api/schema/patterns``,
``/propose``, ``/apply``) ride this same substrate when Stage 13.1 lands —
porting the FULL engine (not just the 4 read methods) keeps that path
clean.
"""

from __future__ import annotations

import re as _re

# ── Donor helper (tektos/utils/db_utils.py:13-76), verbatim ──────────────
# Strict regex for SQL identifiers: must start with letter/underscore,
# contain only alphanumeric + underscore, max 64 chars
_TABLE_RE = _re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


def escape_sql_identifier(identifier: str) -> str:
    """Escape a SQL identifier (table/column name) for safe use.

    For SQLite, identifiers are wrapped in double quotes if they need quoting.
    This does NOT prevent SQL injection by itself — use validate_table_name() first.

    Args:
        identifier: The SQL identifier to escape.

    Returns:
        Safely escaped identifier.

    Raises:
        ValueError: If identifier is invalid.
    """
    if not _TABLE_RE.match(identifier):
        raise ValueError(
            f"Invalid SQL identifier '{identifier}': "
            "must start with letter/underscore, contain only alphanumeric + underscore"
        )

    # SQLite identifiers: wrap in double quotes
    return f'"{identifier}"'


# (donor module docstring omitted — see ADR-141 T8c-9 header above)


import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


log = logging.getLogger(__name__)


# ── Schema Introspection ───────────────────────────────────────────────────


@dataclass
class ColumnInfo:
    """Information about a single column."""

    cid: int
    name: str
    col_type: str
    notnull: bool
    default_value: Any
    pk: bool


@dataclass
class TableInfo:
    """Information about a single table."""

    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    indexes: list[str] = field(default_factory=list)
    row_count: int = 0


@dataclass
class SchemaSnapshot:
    """Complete schema snapshot at a point in time."""

    version: int
    tables: dict[str, TableInfo] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Pattern Detection ──────────────────────────────────────────────────────


@dataclass
class FieldPattern:
    """A pattern detected in the data that might warrant schema evolution."""

    table: str
    field_name: str
    pattern_type: str  # "missing_column", "repeated_metadata", "enum_growth", etc.
    evidence_count: int  # How many records show this pattern
    total_records: int  # Total records in table
    percentage: float
    suggested_column: str  # What the column should be called
    suggested_type: str  # SQLite type
    example_values: list  # Sample values
    confidence: float  # 0.0 to 1.0


# ── Schema Proposal ────────────────────────────────────────────────────────


@dataclass
class SchemaProposal:
    """A proposed schema change with metadata for validation."""

    reason: str
    action: str  # "add_column", "create_table", "rename_column", etc.
    table: str
    column: str | None = None
    column_type: str | None = None
    column_default: Any = None
    column_notnull: bool = False
    new_table_name: str | None = None
    new_table_columns: list[dict] | None = None
    proposed_sql: str = ""
    validation_errors: list[str] = field(default_factory=list)
    rollback_sql: str = ""
    created_at: float = field(default_factory=time.time)

    def validate(self, engine: SchemaEvolutionEngine) -> bool:
        """Validate the proposal against the current schema."""
        schema = engine.introspect()

        if self.action == "add_column":
            if self.table not in schema.tables:
                self.validation_errors.append(f"Table {self.table} does not exist")
                return False
            if self.column in [c.name for c in schema.tables[self.table].columns]:
                self.validation_errors.append(
                    f"Column {self.column} already exists in {self.table}"
                )
                return False

        elif self.action == "create_table":
            if self.new_table_name and self.new_table_name in schema.tables:
                self.validation_errors.append(f"Table {self.new_table_name} already exists")
                return False

        if not self.validation_errors:
            log.info("Schema proposal valid: %s", self.reason)
            return True

        return False


# ── Schema Evolution Engine ────────────────────────────────────────────────


class SchemaEvolutionEngine:
    """
    Full lifecycle schema evolution engine.

    Enables the agent to:
    1. Introspect its own memory structure
    2. Detect patterns that suggest schema changes
    3. Propose and validate changes
    4. Apply changes atomically with rollback
    5. Track evolution history
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._migration_versions: dict[int, str] = {}
        self._migration_functions: dict[int, Any] = {}
        self._applied_versions: list[int] = []
        # Ensure the evolution log table exists
        with self._connect() as conn:
            self._ensure_evolution_log(conn)

    # ── Connection helpers ─────────────────────────────────────────────

    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a raw connection (caller must close it)."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_evolution_log(self, conn: sqlite3.Connection) -> None:
        """Create the evolution log table if it doesn't exist.

        Also runs a small forward-only migration to add ``rollback_sql``
        to pre-existing databases so ``rollback_last`` has data to work
        with even on legacy stores.
        """
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _schema_evolution_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL,
                action TEXT NOT NULL,
                "table" TEXT,
                column TEXT,
                proposed_sql TEXT,
                rollback_sql TEXT,
                created_at REAL NOT NULL
            )
        """)
        # Add rollback_sql to legacy tables that predate this column.
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(_schema_evolution_log)").fetchall()
        }
        if "rollback_sql" not in existing_cols:
            conn.execute("ALTER TABLE _schema_evolution_log ADD COLUMN rollback_sql TEXT")

    # ── Version management ─────────────────────────────────────────────

    def _get_schema_version(self, conn: sqlite3.Connection) -> int:
        """Get current schema version."""
        self._ensure_evolution_log(conn)
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM _schema_evolution_log").fetchone()
        return row[0] or 0

    def _increment_version(self, conn: sqlite3.Connection) -> int:
        """Increment schema version counter. Returns new version."""
        current = self._get_schema_version(conn)
        new_version = current + 1
        conn.execute(
            "INSERT INTO _schema_evolution_log (version, action, \"table\", column, proposed_sql, created_at) VALUES (?, 'version_increment', '', '', '', ?)",
            (new_version, time.time()),
        )
        return new_version

    def get_current_version(self) -> int:
        """Get current schema version."""
        with self._connect() as conn:
            return self._get_schema_version(conn)

    # ── Introspection ──────────────────────────────────────────────────

    def introspect(self) -> SchemaSnapshot:
        """Get complete schema snapshot."""
        conn = self._get_conn()
        try:
            self._ensure_evolution_log(conn)
            tables = {}

            # Get all tables
            table_names = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ).fetchall()
            ]

            for table_name in table_names:
                safe_name = escape_sql_identifier(table_name)
                # Get columns
                columns = []
                for col_data in conn.execute(f"PRAGMA table_info({safe_name})").fetchall():
                    columns.append(
                        ColumnInfo(
                            cid=col_data[0],
                            name=col_data[1],
                            col_type=col_data[2] or "",
                            notnull=bool(col_data[3]),
                            default_value=col_data[4],
                            pk=bool(col_data[5]),
                        )
                    )

                # Get indexes
                indexes = [
                    row[1] for row in conn.execute(f"PRAGMA index_list({safe_name})").fetchall()
                ]

                # Get row count
                row_count = conn.execute(f"SELECT COUNT(*) FROM {safe_name}").fetchone()[0]

                tables[table_name] = TableInfo(
                    name=table_name,
                    columns=columns,
                    indexes=indexes,
                    row_count=row_count,
                )

            # Get schema version
            version = self._get_schema_version(conn)

            return SchemaSnapshot(
                version=version,
                tables=tables,
                metadata={"introspected_at": time.time(), "db_path": str(self.db_path)},
            )
        finally:
            conn.close()

    def get_schema(self) -> dict[str, Any]:
        """Get schema as a serializable dict."""
        snapshot = self.introspect()
        return {
            "version": snapshot.version,
            "tables": {
                name: {
                    "columns": [
                        {
                            "cid": c.cid,
                            "name": c.name,
                            "type": c.col_type,
                            "notnull": c.notnull,
                            "pk": c.pk,
                        }
                        for c in info.columns
                    ],
                    "indexes": info.indexes,
                    "row_count": info.row_count,
                }
                for name, info in snapshot.tables.items()
            },
        }

    def get_table_sample(self, table_name: str, limit: int = 100) -> list[dict]:
        """Get a sample of records from a table for pattern analysis."""
        conn = self._get_conn()
        try:
            rows = conn.execute(f"SELECT * FROM {table_name} LIMIT {limit}").fetchall()
            columns = [
                col[1] for col in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            ]

            return [{col: val for col, val in zip(columns, row)} for row in rows]
        finally:
            conn.close()

    # ── Pattern Detection ────────────────────────────────────────────

    def detect_patterns(
        self,
        table_name: str,
        metadata_field: str = "payload",
        top_k: int = 10,
    ) -> list[FieldPattern]:
        """
        Detect patterns in table data that might warrant schema changes.

        Looks for:
        - Fields appearing frequently in JSON metadata that aren't columns
        - Values that look like enums but are stored as strings
        - Numeric fields stored as strings
        - Nested JSON that could be flattened

        Returns patterns ranked by confidence (most likely to need schema change first).
        """
        conn = self._get_conn()
        try:
            # Get total count
            total = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            if total == 0:
                return []

            # Get all JSON records
            rows = conn.execute(
                f"SELECT {metadata_field} FROM {table_name} WHERE {metadata_field} LIKE '{{%' LIMIT {top_k * 10}"
            ).fetchall()

            # Extract all unique keys from JSON
            field_counts: dict[str, dict[str, Any]] = {}

            for (json_str,) in rows:
                try:
                    data = json.loads(json_str)
                    for key, value in data.items():
                        if key not in field_counts:
                            field_counts[key] = {
                                "count": 0,
                                "types": set(),
                                "values": [],
                            }
                        field_counts[key]["count"] += 1
                        field_counts[key]["types"].add(type(value).__name__)
                        if len(field_counts[key]["values"]) < 5:
                            field_counts[key]["values"].append(value)
                except json.JSONDecodeError:
                    continue

            # Current table columns
            current_columns = {
                col.name
                for col in self.introspect()
                .tables.get(table_name, TableInfo(name=table_name))
                .columns
            }

            # Build patterns
            patterns: list[FieldPattern] = []
            for field_name, stats in field_counts.items():
                if field_name in current_columns:
                    continue  # Already a column

                # Calculate percentage
                percentage = stats["count"] / total

                # Determine suggested type
                types = stats["types"]
                if types == {"int"} or types == {"int", "float"} or types == {"float"}:
                    suggested_type = "REAL"
                elif types == {"str"}:
                    suggested_type = "TEXT"
                elif types == {"bool"}:
                    suggested_type = "INTEGER"
                else:
                    suggested_type = "TEXT"

                # Confidence based on frequency
                if percentage > 0.5:
                    confidence = 0.95
                elif percentage > 0.3:
                    confidence = 0.8
                elif percentage > 0.1:
                    confidence = 0.6
                else:
                    confidence = 0.3

                patterns.append(
                    FieldPattern(
                        table=table_name,
                        field_name=field_name,
                        pattern_type="repeated_metadata",
                        evidence_count=stats["count"],
                        total_records=total,
                        percentage=percentage,
                        suggested_column=field_name,
                        suggested_type=suggested_type,
                        example_values=stats["values"],
                        confidence=confidence,
                    )
                )

            # Sort by confidence (highest first)
            patterns.sort(key=lambda p: p.confidence, reverse=True)

            return patterns[:top_k]

        finally:
            conn.close()

    # ── Proposal Generation ──────────────────────────────────────────

    def propose_from_pattern(self, pattern: FieldPattern) -> SchemaProposal:
        """Generate a schema proposal from a detected pattern."""
        if pattern.pattern_type == "repeated_metadata":
            default = f"'{pattern.example_values[0]}'" if pattern.example_values else None
            return SchemaProposal(
                reason=f"Field '{pattern.field_name}' appears in {pattern.percentage:.0%} of {pattern.table} records",
                action="add_column",
                table=pattern.table,
                column=pattern.field_name,
                column_type=pattern.suggested_type,
                column_default=default,
                column_notnull=False,
                proposed_sql=f"ALTER TABLE {pattern.table} ADD COLUMN {pattern.field_name} {pattern.suggested_type} DEFAULT {default}",
                rollback_sql=f"ALTER TABLE {pattern.table} DROP COLUMN {pattern.field_name}",
            )

        elif pattern.pattern_type == "missing_column":
            return SchemaProposal(
                reason=f"Table {pattern.table} appears to be missing column '{pattern.field_name}'",
                action="add_column",
                table=pattern.table,
                column=pattern.field_name,
                column_type=pattern.suggested_type,
                column_default=None,
                proposed_sql=f"ALTER TABLE {pattern.table} ADD COLUMN {pattern.field_name} {pattern.suggested_type}",
                rollback_sql=f"ALTER TABLE {pattern.table} DROP COLUMN {pattern.field_name}",
            )

        # Default fallback
        return SchemaProposal(
            reason=f"Pattern detected in {pattern.table}.{pattern.field_name}",
            action="add_column",
            table=pattern.table,
            column=pattern.field_name,
            column_type=pattern.suggested_type,
            proposed_sql=f"ALTER TABLE {pattern.table} ADD COLUMN {pattern.field_name} {pattern.suggested_type}",
        )

    def propose(self, reason: str, action: str, **kwargs) -> SchemaProposal:
        """Manually propose a schema change."""
        proposal = SchemaProposal(reason=reason, action=action, **kwargs)

        # Generate SQL based on action
        if action == "add_column":
            default = (
                f"DEFAULT {kwargs.get('column_default')}" if kwargs.get("column_default") else ""
            )
            "NOT NULL" if kwargs.get("column_notnull") else ""
            proposal.proposed_sql = f"ALTER TABLE {kwargs['table']} ADD COLUMN {kwargs['column']} {kwargs['column_type']}{default}{' NOT NULL' if kwargs.get('column_notnull') else ''}".strip()
            # SQLite 3.35+ supports DROP COLUMN, which is the actual
            # inverse of ADD COLUMN. Older backends can override this
            # rollback_sql before calling apply_proposal if they need to
            # fall back to the table-swap dance.
            proposal.rollback_sql = f"ALTER TABLE {kwargs['table']} DROP COLUMN {kwargs['column']}"

        elif action == "create_table":
            cols = ", ".join(
                f"{c['name']} {c['type']}" + (f" DEFAULT {c['default']}" if "default" in c else "")
                for c in kwargs.get("new_table_columns", [])
            )
            proposal.new_table_name = kwargs.get("table")
            proposal.proposed_sql = f"CREATE TABLE {proposal.new_table_name} ({cols})"
            proposal.rollback_sql = f"DROP TABLE IF EXISTS {proposal.new_table_name}"

        return proposal

    # ── Migration Application ────────────────────────────────────────

    def apply_proposal(self, proposal: SchemaProposal) -> bool:
        """
        Apply a validated schema proposal.

        Returns True if successful, False otherwise.
        Logs all changes to migration history.
        """
        if not proposal.validate(self):
            log.error("Proposal validation failed: %s", proposal.validation_errors)
            return False

        with self._connect() as conn:
            # Execute migration
            log.info("Applying schema proposal: %s", proposal.reason)
            conn.execute(proposal.proposed_sql)

            # Update version
            self._increment_version(conn)

            # Log migration with rollback SQL so rollback_last can replay it.
            conn.execute(
                'INSERT INTO _schema_evolution_log (version, action, "table", column, proposed_sql, rollback_sql, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (
                    self._get_schema_version(conn),
                    proposal.action,
                    proposal.table,
                    proposal.column,
                    proposal.proposed_sql,
                    proposal.rollback_sql,
                    time.time(),
                ),
            )

            log.info(
                "Schema proposal applied: %s → v%d", proposal.reason, self._get_schema_version(conn)
            )
            return True

    def apply_migration(self, sql: str, description: str = "") -> bool:
        """Apply raw SQL migration with logging."""
        with self._connect() as conn:
            log.info("Applying migration: %s", description or sql[:50])
            conn.execute(sql)

            # Log
            conn.execute(
                "INSERT INTO _schema_evolution_log (version, action, \"table\", column, proposed_sql, created_at) VALUES (?, 'custom', '', '', ?, ?)",
                (
                    self._get_schema_version(conn),
                    sql,
                    time.time(),
                ),
            )

            return True

    def rollback_last(self) -> bool:
        """Rollback the most recent applied migration.

        Reads the latest applied entry from ``_schema_evolution_log`` (skipping
        internal ``version_increment`` markers), executes its stored
        ``rollback_sql`` inside a transaction, then bumps the version and
        logs the rollback so the history is auditable.

        Returns True when a rollback ran, False when there is nothing to
        roll back or the previous migration recorded no rollback SQL.
        """
        conn = self._get_conn()
        try:
            self._ensure_evolution_log(conn)
            # Find the last real migration (ignore version_increment markers).
            row = conn.execute(
                """
                SELECT id, version, action, "table", column, proposed_sql, rollback_sql
                FROM _schema_evolution_log
                WHERE action != 'version_increment'
                ORDER BY version DESC, id DESC
                LIMIT 1
                """
            ).fetchone()

            if not row:
                log.warning("No migrations to rollback")
                return False

            _row_id, version, action, table, column, proposed_sql, rollback_sql = row

            if not rollback_sql:
                log.warning(
                    "Cannot rollback v%d (%s on %s.%s): no rollback SQL stored",
                    version,
                    action,
                    table,
                    column,
                )
                return False

            try:
                conn.execute("BEGIN")
                conn.execute(rollback_sql)
                new_version = self._get_schema_version(conn) + 1
                conn.execute(
                    "INSERT INTO _schema_evolution_log "
                    '(version, action, "table", column, proposed_sql, rollback_sql, created_at) '
                    "VALUES (?, 'rollback', ?, ?, ?, NULL, ?)",
                    (new_version, table, column, rollback_sql, time.time()),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

            log.info(
                "Rolled back v%d (%s on %s.%s) → v%d via: %s",
                version,
                action,
                table,
                column,
                new_version,
                (proposed_sql or "")[:80],
            )
            return True

        finally:
            conn.close()

    # ── Migration Versioning ─────────────────────────────────────────

    def get_evolution_history(self) -> list[dict]:
        """Get full schema evolution history."""
        conn = self._get_conn()
        try:
            self._ensure_evolution_log(conn)
            rows = conn.execute(
                'SELECT version, action, "table", column, proposed_sql, created_at FROM _schema_evolution_log ORDER BY version ASC'
            ).fetchall()

            return [
                {
                    "version": row[0],
                    "action": row[1],
                    "table": row[2],
                    "column": row[3],
                    "sql": row[4],
                    "created_at": row[5],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def apply_migrations(self) -> list[int]:
        """
        Apply all registered migrations up to the highest version.

        Returns list of applied version numbers.
        """
        if not self._migration_versions:
            return []

        _target = max(self._migration_versions.keys())
        applied: list[int] = []

        with self._connect() as conn:
            current = self._get_schema_version(conn)

            for version, name in sorted(self._migration_versions.items()):
                if version <= current:
                    continue

                fn = self._migration_functions.get(version)
                if not fn:
                    log.warning("Migration v%d (%s) has no function — skipping", version, name)
                    continue

                log.info("Applying migration v%d: %s", version, name)

                try:
                    fn()
                    self._record_migration(conn, version, name)
                    applied.append(version)
                except Exception as exc:
                    log.error("Migration v%d failed: %s", version, exc)
                    raise RuntimeError(f"Migration v{version} ({name}) failed: {exc}")

        if applied:
            log.info("Applied %d migration(s): %s", len(applied), applied)
        return applied

    def register_migration(self, version: int, name: str, fn=None):
        """
        Register a migration function.

        Usage:
            @engine.register_migration(2, "add_self_improvement_fields")
            def migration_2():
                ...

        Or:
            engine.register_migration(2, "name", migration_function)
        """
        self._migration_versions[version] = name
        if fn is not None:
            self._migration_functions[version] = fn

        # When used as decorator, fn is the decorated function
        # Return a wrapper so the decorator chain works
        def decorator(f):
            self._migration_functions[version] = f
            return f

        return decorator

    def get_migration_functions(self) -> dict[int, Any]:
        """Get registered migration functions."""
        return dict(self._migration_functions)

    def _record_migration(self, conn: sqlite3.Connection, version: int, name: str) -> None:
        """Record a migration as applied."""
        self._ensure_evolution_log(conn)
        conn.execute(
            "INSERT INTO _schema_evolution_log (version, action, \"table\", column, proposed_sql, created_at) VALUES (?, 'applied', ?, '', '', ?)",
            (version, name, time.time()),
        )
