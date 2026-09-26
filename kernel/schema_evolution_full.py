"""Tektos-Ultima-v1 — Schema Evolution Engine

Full lifecycle schema management for Tektos's own databases.
Enables the agent to autonomously create, modify, extend, and improve
its database schema:

    introspect → analyze → plan → validate → apply → verify

Capabilities:
    1. Versioned migrations — forward, backward, and rollback
    2. Schema diffing — compare desired vs actual, generate migration SQL
    3. Relationship detection — FK relationships, many-to-many tables
    4. Normalization analysis — detect denormalization, suggest improvements
    5. Schema documentation — auto-generate docs from schema
    6. Database health monitoring — fragmentation, bloat, corruption
    7. Schema versioning — track changes over time with rollback
    8. Automated optimization — propose and apply improvements

Architecture:
    SchemaEvolutionEngine (public API)
        ├── MigrationEngine (versioned migrations)
        ├── SchemaDiffer (diffing + migration SQL generation)
        ├── RelationshipDetector (FK + many-to-many detection)
        ├── NormalizationAnalyzer (denormalization detection)
        ├── SchemaDocumenter (auto-doc generation)
        └── HealthMonitor (fragmentation, bloat, corruption)

Usage:
    engine = SchemaEvolutionEngine(db_path)

    # Introspect
    schema = engine.introspect()

    # Diff schemas
    diff = engine.diff_schema(desired_schema)
    migration_sql = engine.generate_migration(diff)

    # Apply migrations
    engine.apply_migration(migration_sql)
    engine.rollback_migration()

    # Analyze relationships
    relationships = engine.detect_relationships()

    # Check health
    health = engine.check_health()

    # Generate docs
    docs = engine.generate_docs()
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# DIVERGENCE (13.2a): logger renamed tektos.* -> kosmos.* (kernel namespace).
log = logging.getLogger("kosmos.schema_evolution_full")

# ── Safety Limits ────────────────────────────────────────────────────────────

MAX_MIGRATION_SIZE = 1024 * 1024  # 1 MB
MAX_MIGRATIONS = 1000
MAX_SCHEMA_VERSION = 99999
MIGRATION_TABLE = "__tektos_migrations__"
HEALTH_TABLE = "__tektos_health__"

# ── Data Classes ─────────────────────────────────────────────────────────────


@dataclass
class MigrationRecord:
    """A single migration record."""

    id: str
    version: int
    name: str
    applied_at: float
    sql: str
    checksum: str = ""
    rolled_back: bool = False


@dataclass
class SchemaDiff:
    """Difference between two schemas."""

    tables_to_create: list[dict] = field(default_factory=list)
    tables_to_drop: list[str] = field(default_factory=list)
    tables_to_alter: list[dict] = field(default_factory=list)
    indexes_to_create: list[dict] = field(default_factory=list)
    indexes_to_drop: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)


@dataclass
class Relationship:
    """Detected relationship between tables."""

    source_table: str
    source_column: str
    target_table: str
    target_column: str
    relationship_type: str  # "one-to-one", "one-to-many", "many-to-many"
    confidence: float = 0.0


@dataclass
class NormalizationIssue:
    """A normalization issue detected in the schema."""

    table: str
    column: str
    issue_type: str  # "repeating_group", "partial_dependency", "transitive_dependency"
    description: str
    suggestion: str


@dataclass
class HealthReport:
    """Database health report."""

    overall_score: float  # 0-100
    fragmentation_pct: float
    bloat_bytes: int
    corruption_detected: bool
    missing_indexes: list[str] = field(default_factory=list)
    large_tables: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class SchemaDoc:
    """Generated schema documentation."""

    title: str
    version: int
    tables: list[dict] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    generated_at: float = 0.0


# ── Migration Engine ─────────────────────────────────────────────────────────


class MigrationEngine:
    """Versioned migration management."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

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

    def _ensure_migration_table(self, conn: sqlite3.Connection):
        """Create the migration tracking table if it doesn't exist."""
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
                id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                name TEXT NOT NULL,
                applied_at REAL NOT NULL,
                sql TEXT NOT NULL,
                checksum TEXT,
                rolled_back INTEGER DEFAULT 0
            )
        """)

    def get_current_version(self) -> int:
        """Get the current schema version."""
        with self._connect() as conn:
            self._ensure_migration_table(conn)
            row = conn.execute(
                f"SELECT MAX(version) FROM {MIGRATION_TABLE} WHERE rolled_back = 0"
            ).fetchone()
            return row[0] or 0

    def get_applied_migrations(self) -> list[MigrationRecord]:
        """Get all applied (non-rolled-back) migrations."""
        with self._connect() as conn:
            self._ensure_migration_table(conn)
            rows = conn.execute(
                f"SELECT id, version, name, applied_at, sql, checksum, rolled_back "
                f"FROM {MIGRATION_TABLE} WHERE rolled_back = 0 ORDER BY version"
            ).fetchall()
            return [
                MigrationRecord(
                    id=r[0],
                    version=r[1],
                    name=r[2],
                    applied_at=r[3],
                    sql=r[4],
                    checksum=r[5],
                    rolled_back=bool(r[6]),
                )
                for r in rows
            ]

    def get_all_migrations(self) -> list[MigrationRecord]:
        """Get all migrations including rolled-back ones."""
        with self._connect() as conn:
            self._ensure_migration_table(conn)
            rows = conn.execute(
                f"SELECT id, version, name, applied_at, sql, checksum, rolled_back "
                f"FROM {MIGRATION_TABLE} ORDER BY version"
            ).fetchall()
            return [
                MigrationRecord(
                    id=r[0],
                    version=r[1],
                    name=r[2],
                    applied_at=r[3],
                    sql=r[4],
                    checksum=r[5],
                    rolled_back=bool(r[6]),
                )
                for r in rows
            ]

    def apply_migration(
        self,
        migration_id: str,
        version: int,
        name: str,
        sql: str,
        checksum: str = "",
    ) -> bool:
        """
        Apply a migration.

        Args:
            migration_id: Unique migration identifier.
            version: Schema version number.
            name: Human-readable migration name.
            sql: SQL statements to execute.
            checksum: SHA256 checksum of the SQL for validation.

        Returns:
            True if migration was applied successfully.
        """
        if version > MAX_SCHEMA_VERSION:
            raise ValueError(f"Version {version} exceeds maximum {MAX_SCHEMA_VERSION}")

        if len(sql) > MAX_MIGRATION_SIZE:
            raise ValueError(f"Migration SQL exceeds {MAX_MIGRATION_SIZE} bytes")

        if not checksum:
            import hashlib

            checksum = hashlib.sha256(sql.encode()).hexdigest()[:16]

        with self._connect() as conn:
            self._ensure_migration_table(conn)

            # Check if already applied
            existing = conn.execute(
                f"SELECT id FROM {MIGRATION_TABLE} WHERE id = ?",
                (migration_id,),
            ).fetchone()
            if existing:
                log.warning("Migration '%s' already applied, skipping", migration_id)
                return False

            # Execute migration SQL
            try:
                conn.executescript(sql)
            except sqlite3.Error as e:
                raise RuntimeError(f"Migration '{name}' failed: {e}") from e

            # Record migration
            conn.execute(
                f"INSERT INTO {MIGRATION_TABLE} "
                f"(id, version, name, applied_at, sql, checksum, rolled_back) "
                f"VALUES (?, ?, ?, ?, ?, ?, 0)",
                (migration_id, version, name, time.time(), sql, checksum),
            )

        log.info("Applied migration '%s' (version %d)", name, version)
        return True

    def rollback_migration(self, migration_id: str) -> bool:
        """
        Roll back a migration by marking it as rolled back.

        Note: This marks the migration as rolled back but does NOT execute
        reverse SQL. For full rollback, provide reverse SQL in a new migration.

        Args:
            migration_id: Migration to roll back.

        Returns:
            True if rolled back successfully.
        """
        with self._connect() as conn:
            self._ensure_migration_table(conn)

            row = conn.execute(
                f"SELECT version, sql FROM {MIGRATION_TABLE} WHERE id = ?",
                (migration_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Migration '{migration_id}' not found")

            # Mark as rolled back
            conn.execute(
                f"UPDATE {MIGRATION_TABLE} SET rolled_back = 1 WHERE id = ?",
                (migration_id,),
            )

        log.info("Rolled back migration '%s'", migration_id)
        return True

    def get_migration_history(self) -> list[dict]:
        """Get full migration history as list of dicts."""
        migrations = self.get_all_migrations()
        return [
            {
                "id": m.id,
                "version": m.version,
                "name": m.name,
                "applied_at": m.applied_at,
                "rolled_back": m.rolled_back,
                "checksum": m.checksum,
            }
            for m in migrations
        ]


# ── Schema Differ ────────────────────────────────────────────────────────────


class SchemaDiffer:
    """Compare schemas and generate migration SQL."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

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

    def _safe_identifier(self, name: str) -> str:
        """Escape a SQL identifier safely."""
        import re

        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$", name):
            raise ValueError(f"Invalid identifier: {name}")
        return f'"{name}"'

    def get_current_schema(self) -> dict[str, Any]:
        """Get the current database schema as a dict."""
        with self._connect() as conn:
            schema = {}

            # Get all user tables
            tables = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND substr(name, 1, 1) != '_' "
                "ORDER BY name"
            ).fetchall()

            for (table_name,) in tables:
                safe_name = self._safe_identifier(table_name)

                # Get columns
                columns = []
                for col_data in conn.execute(f"PRAGMA table_info({safe_name})").fetchall():
                    columns.append(
                        {
                            "name": col_data[1],
                            "type": col_data[2] or "",
                            "notnull": bool(col_data[3]),
                            "default_value": col_data[4],
                            "pk": bool(col_data[5]),
                        }
                    )

                # Get indexes
                indexes = []
                for idx_data in conn.execute(f"PRAGMA index_list({safe_name})").fetchall():
                    idx_name = idx_data[1]
                    is_unique = bool(idx_data[2])
                    idx_cols = [
                        col[1]
                        for col in conn.execute(
                            f"PRAGMA index_info({self._safe_identifier(idx_name)})"
                        ).fetchall()
                    ]
                    indexes.append(
                        {
                            "name": idx_name,
                            "unique": is_unique,
                            "columns": idx_cols,
                        }
                    )

                schema[table_name] = {
                    "columns": columns,
                    "indexes": indexes,
                }

            return schema

    def diff_schemas(
        self,
        desired_schema: dict[str, Any],
        current_schema: dict[str, Any] | None = None,
    ) -> SchemaDiff:
        """
        Compare desired schema against current schema.

        Args:
            desired_schema: Target schema definition.
            current_schema: Current schema (auto-detected if None).

        Returns:
            SchemaDiff with all differences.
        """
        if current_schema is None:
            current_schema = self.get_current_schema()

        diff = SchemaDiff()

        # Normalize desired_schema columns to dict format
        normalized_desired = {}
        for table_name, table_def in desired_schema.items():
            cols = table_def.get("columns", {})
            if isinstance(cols, list):
                # Convert list format to dict format
                cols_dict = {}
                for col in cols:
                    if isinstance(col, dict):
                        cols_dict[col["name"]] = col
                    elif isinstance(col, str):
                        cols_dict[col] = {"type": "TEXT"}
                cols = cols_dict
            normalized_desired[table_name] = {**table_def, "columns": cols}

        # Tables to create
        for table_name, table_def in normalized_desired.items():
            if table_name not in current_schema:
                diff.tables_to_create.append(
                    {
                        "name": table_name,
                        "columns": table_def.get("columns", {}),
                        "primary_key": table_def.get("primary_key"),
                    }
                )
                diff.changes.append(f"CREATE TABLE {table_name}")

        # Tables to drop
        for table_name in current_schema:
            if table_name not in normalized_desired:
                diff.tables_to_drop.append(table_name)
                diff.changes.append(f"DROP TABLE {table_name}")

        # Tables to alter
        for table_name in normalized_desired:
            if table_name in current_schema:
                desired_cols = normalized_desired[table_name].get("columns", {})
                current_cols = {c["name"]: c for c in current_schema[table_name]["columns"]}

                # Columns to add
                for col_name, col_def in desired_cols.items():
                    if col_name not in current_cols:
                        diff.tables_to_alter.append(
                            {
                                "table": table_name,
                                "action": "add_column",
                                "column": col_name,
                                "type": col_def.get("type", "TEXT")
                                if isinstance(col_def, dict)
                                else col_def,
                                "notnull": col_def.get("notnull", False)
                                if isinstance(col_def, dict)
                                else False,
                                "default": col_def.get("default")
                                if isinstance(col_def, dict)
                                else None,
                            }
                        )
                        diff.changes.append(f"ALTER TABLE {table_name} ADD COLUMN {col_name}")

                # Columns to drop
                for col_name in current_cols:
                    if col_name not in desired_cols:
                        diff.tables_to_alter.append(
                            {
                                "table": table_name,
                                "action": "drop_column",
                                "column": col_name,
                            }
                        )
                        diff.changes.append(f"ALTER TABLE {table_name} DROP COLUMN {col_name}")

                # Columns to modify (type change)
                for col_name, desired_col in desired_cols.items():
                    if col_name in current_cols:
                        current_type = current_cols[col_name].get("type", "")
                        desired_type = (
                            desired_col.get("type", "")
                            if isinstance(desired_col, dict)
                            else desired_col
                        )
                        if current_type != desired_type:
                            diff.tables_to_alter.append(
                                {
                                    "table": table_name,
                                    "action": "modify_column",
                                    "column": col_name,
                                    "from_type": current_type,
                                    "to_type": desired_type,
                                }
                            )
                            diff.changes.append(
                                f"ALTER TABLE {table_name} MODIFY COLUMN {col_name} {desired_type}"
                            )

        # Indexes to create
        for table_name, table_def in normalized_desired.items():
            if table_name in current_schema:
                desired_indexes = {idx["name"]: idx for idx in table_def.get("indexes", [])}
                current_indexes = {
                    idx["name"]: idx for idx in current_schema[table_name]["indexes"]
                }

                for idx_name, idx_def in desired_indexes.items():
                    if idx_name not in current_indexes:
                        diff.indexes_to_create.append(
                            {
                                "name": idx_name,
                                "table": table_name,
                                "columns": idx_def.get("columns", []),
                                "unique": idx_def.get("unique", False),
                            }
                        )
                        diff.changes.append(f"CREATE INDEX {idx_name}")

        # Indexes to drop
        for table_name, table_def in current_schema.items():
            if table_name in normalized_desired:
                desired_indexes = {
                    idx["name"]: idx for idx in normalized_desired[table_name].get("indexes", [])
                }
                for idx_name in table_def.get("indexes", []):
                    if isinstance(idx_name, dict):
                        if idx_name["name"] not in desired_indexes:
                            diff.indexes_to_drop.append(idx_name["name"])
                            diff.changes.append(f"DROP INDEX {idx_name['name']}")

        return diff

    def generate_migration_sql(self, diff: SchemaDiff) -> str:
        """
        Generate SQL from a SchemaDiff.

        Args:
            diff: SchemaDiff to convert to SQL.

        Returns:
            SQL string with all migration statements.
        """
        sql_statements = []

        # Create tables
        for table in diff.tables_to_create:
            cols = []
            pk_set = False
            for col_name, col_def in table["columns"].items():
                if isinstance(col_def, str):
                    col_type = col_def
                    if "PRIMARY KEY" in col_type.upper():
                        pk_set = True
                    cols.append(f'"{col_name}" {col_type}')
                elif isinstance(col_def, dict):
                    col_type = col_def.get("type", "TEXT")
                    notnull = " NOT NULL" if col_def.get("notnull") else ""
                    default = ""
                    if "default" in col_def:
                        val = col_def["default"]
                        default = f" DEFAULT '{val}'" if isinstance(val, str) else f" DEFAULT {val}"
                    if "PRIMARY KEY" in col_type.upper():
                        pk_set = True
                    cols.append(f'"{col_name}" {col_type}{notnull}{default}')

            pk = table.get("primary_key")
            if pk and not pk_set:
                cols.append(f'PRIMARY KEY ("{pk}")')

            sql_statements.append(
                f'CREATE TABLE IF NOT EXISTS "{table["name"]}" ({", ".join(cols)})'
            )

        # Drop tables
        for table_name in diff.tables_to_drop:
            sql_statements.append(f'DROP TABLE IF EXISTS "{table_name}"')

        # Alter tables
        for alter in diff.tables_to_alter:
            if alter["action"] == "add_column":
                col_type = alter["type"]
                notnull = " NOT NULL" if alter.get("notnull") else ""
                default = ""
                if "default" in alter:
                    val = alter["default"]
                    default = f" DEFAULT '{val}'" if isinstance(val, str) else f" DEFAULT {val}"
                sql_statements.append(
                    f'ALTER TABLE "{alter["table"]}" ADD COLUMN "{alter["column"]}" {col_type}{notnull}{default}'
                )
            elif alter["action"] == "drop_column":
                sql_statements.append(
                    f'ALTER TABLE "{alter["table"]}" DROP COLUMN "{alter["column"]}"'
                )
            elif alter["action"] == "modify_column":
                # SQLite doesn't support MODIFY COLUMN directly
                # Need to recreate the table
                sql_statements.append(
                    f"-- SQLite: recreate table to modify column {alter['table']}.{alter['column']}"
                )

        # Create indexes
        for idx in diff.indexes_to_create:
            unique = "UNIQUE " if idx.get("unique") else ""
            cols = ", ".join(f'"{c}"' for c in idx["columns"])
            sql_statements.append(
                f'CREATE {unique}INDEX IF NOT EXISTS "{idx["name"]}" ON "{idx["table"]}" ({cols})'
            )

        # Drop indexes
        for idx_name in diff.indexes_to_drop:
            sql_statements.append(f'DROP INDEX IF EXISTS "{idx_name}"')

        return "\n".join(sql_statements)

    def generate_migration_plan(
        self,
        desired_schema: dict[str, Any],
        current_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Generate a migration plan with SQL and metadata.

        Args:
            desired_schema: Target schema definition.
            current_schema: Current schema (auto-detected if None).

        Returns:
            Dict with diff, SQL, and metadata.
        """
        diff = self.diff_schemas(desired_schema, current_schema)
        sql = self.generate_migration_sql(diff)

        return {
            "diff": {
                "tables_to_create": len(diff.tables_to_create),
                "tables_to_drop": len(diff.tables_to_drop),
                "tables_to_alter": len(diff.tables_to_alter),
                "indexes_to_create": len(diff.indexes_to_create),
                "indexes_to_drop": len(diff.indexes_to_drop),
                "changes": diff.changes,
            },
            "sql": sql,
            "statement_count": len(
                [s for s in sql.split("\n") if s.strip() and not s.strip().startswith("--")]
            ),
        }


# ── Relationship Detector ────────────────────────────────────────────────────


class RelationshipDetector:
    """Detect relationships between tables."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

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

    def detect_relationships(self) -> list[Relationship]:
        """
        Detect relationships between tables.

        Returns:
            List of Relationship objects.
        """
        with self._connect() as conn:
            relationships = []

            # Get all user tables
            tables = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND substr(name, 1, 1) != '_' "
                "ORDER BY name"
            ).fetchall()

            table_names = [t[0] for t in tables]

            # Check for explicit foreign keys
            for table_name in table_names:
                safe_name = f'"{table_name}"'
                fk_info = conn.execute(f"PRAGMA foreign_key_list({safe_name})").fetchall()

                for fk in fk_info:
                    # fk: (id, seq, table, from, to, on_update, on_delete, match)
                    relationships.append(
                        Relationship(
                            source_table=table_name,
                            source_column=fk[3],
                            target_table=fk[2],
                            target_column=fk[4],
                            relationship_type="one-to-many",
                            confidence=0.95,
                        )
                    )

            # Check for implicit relationships (column name patterns)
            for table_name in table_names:
                safe_name = f'"{table_name}"'
                columns = conn.execute(f"PRAGMA table_info({safe_name})").fetchall()

                for col in columns:
                    col_name = col[1]
                    col[2] or ""

                    # Check if column name matches another table's primary key
                    if col_name.lower().endswith("_id"):
                        base = col_name[:-3]  # Remove "_id" suffix
                        # Try exact match first
                        if base in table_names:
                            target_table = base
                        else:
                            # Try pluralization: user -> users, tag -> tags
                            target_table = None
                            for tn in table_names:
                                if tn == base + "s" or tn == base + "es":
                                    target_table = tn
                                    break
                        if target_table:
                            # Check if target table has an integer primary key
                            target_pk = conn.execute(
                                f'PRAGMA table_info("{target_table}")'
                            ).fetchall()
                            if (
                                target_pk
                                and target_pk[0][2]
                                and "INTEGER" in target_pk[0][2].upper()
                            ):
                                # Check data correlation
                                correlation = self._check_correlation(
                                    conn, table_name, col_name, target_table
                                )
                                relationships.append(
                                    Relationship(
                                        source_table=table_name,
                                        source_column=col_name,
                                        target_table=target_table,
                                        target_column=target_pk[0][1],
                                        relationship_type="one-to-many",
                                        confidence=correlation,
                                    )
                                )

            # Check for many-to-many relationships (junction tables)
            for table_name in table_names:
                safe_name = f'"{table_name}"'
                columns = conn.execute(f"PRAGMA table_info({safe_name})").fetchall()

                # A junction table typically has exactly 2 foreign key columns
                # and no primary key other than the combination
                if len(columns) == 2:
                    col1_name = columns[0][1]
                    col2_name = columns[1][1]

                    # Check if both columns look like foreign keys
                    if col1_name.lower().endswith("_id") and col2_name.lower().endswith("_id"):
                        target1 = col1_name[:-3]
                        target2 = col2_name[:-3]

                        if target1 in table_names and target2 in table_names:
                            relationships.append(
                                Relationship(
                                    source_table=table_name,
                                    source_column=col1_name,
                                    target_table=target1,
                                    target_column="id",
                                    relationship_type="many-to-many",
                                    confidence=0.85,
                                )
                            )
                            relationships.append(
                                Relationship(
                                    source_table=table_name,
                                    source_column=col2_name,
                                    target_table=target2,
                                    target_column="id",
                                    relationship_type="many-to-many",
                                    confidence=0.85,
                                )
                            )

            return relationships

    def _check_correlation(
        self,
        conn: sqlite3.Connection,
        source_table: str,
        source_col: str,
        target_table: str,
    ) -> float:
        """
        Check data correlation between columns to estimate relationship confidence.

        Returns a confidence score between 0 and 1.
        """
        try:
            # Check if all source values exist in target
            source_values = conn.execute(
                f'SELECT DISTINCT "{source_col}" FROM "{source_table}" '
                f'WHERE "{source_col}" IS NOT NULL'
            ).fetchall()

            if not source_values:
                return 0.0

            source_ids = [v[0] for v in source_values]
            placeholders = ",".join("?" for _ in source_ids)

            target_exists = conn.execute(
                f'SELECT COUNT(*) FROM "{target_table}" WHERE "id" IN ({placeholders})',
                source_ids,
            ).fetchone()[0]

            # If all source values exist in target, high confidence
            return min(1.0, target_exists / len(source_ids))
        except Exception:
            return 0.5  # Default moderate confidence


# ── Normalization Analyzer ───────────────────────────────────────────────────


class NormalizationAnalyzer:
    """Analyze schema for normalization issues."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

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

    def analyze_normalization(self) -> list[NormalizationIssue]:
        """
        Analyze schema for normalization issues.

        Returns:
            List of NormalizationIssue objects.
        """
        with self._connect() as conn:
            issues = []

            # Get all user tables
            tables = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND substr(name, 1, 1) != '_' "
                "ORDER BY name"
            ).fetchall()

            for (table_name,) in tables:
                safe_name = f'"{table_name}"'

                # Get columns
                columns = conn.execute(f"PRAGMA table_info({safe_name})").fetchall()

                # Get row count
                row_count = conn.execute(f"SELECT COUNT(*) FROM {safe_name}").fetchone()[0]

                if row_count == 0:
                    continue

                # Check for repeating groups (columns with similar names)
                col_names = [col[1] for col in columns]
                repeating = self._detect_repeating_groups(col_names)
                for group in repeating:
                    issues.append(
                        NormalizationIssue(
                            table=table_name,
                            column=", ".join(group),
                            issue_type="repeating_group",
                            description=f"Columns {group} appear to be a repeating group",
                            suggestion=f"Create a separate table for {group[0]} values",
                        )
                    )

                # Check for partial dependencies (non-key columns depending on part of composite key)
                pk_cols = [col[1] for col in columns if col[5]]
                if len(pk_cols) > 1:
                    for col in columns:
                        col_name = col[1]
                        if col_name not in pk_cols:
                            # Check if this column depends on only part of the key
                            for pk_col in pk_cols:
                                if pk_col.lower().endswith("_id"):
                                    # This column might depend on just this PK part
                                    issues.append(
                                        NormalizationIssue(
                                            table=table_name,
                                            column=col_name,
                                            issue_type="partial_dependency",
                                            description=(
                                                f"Column '{col_name}' may depend only on "
                                                f"'{pk_col}' part of composite key"
                                            ),
                                            suggestion=f"Consider moving '{col_name}' to a separate table",
                                        )
                                    )

                # Check for transitive dependencies
                for col1 in columns:
                    col1_name = col1[1]
                    if col1_name.lower().endswith("_id"):
                        for col2 in columns:
                            col2_name = col2[1]
                            if col2_name != col1_name and not col2[5]:
                                # Check if col2 depends on col1 (transitive)
                                correlation = self._check_column_correlation(
                                    conn, table_name, col1_name, col2_name
                                )
                                if correlation > 0.9:
                                    issues.append(
                                        NormalizationIssue(
                                            table=table_name,
                                            column=f"{col1_name} -> {col2_name}",
                                            issue_type="transitive_dependency",
                                            description=(
                                                f"Column '{col2_name}' appears to transitively "
                                                f"depend on '{col1_name}'"
                                            ),
                                            suggestion=f"Remove '{col2_name}' and derive it from '{col1_name}'",
                                        )
                                    )

            return issues

    def _detect_repeating_groups(self, col_names: list[str]) -> list[list[str]]:
        """Detect columns that appear to be repeating groups."""
        groups = []

        # Look for patterns like: field_1, field_2, field_3 or field_a, field_b, field_c
        patterns = {}
        for name in col_names:
            # Match patterns like "name_1", "name_2", etc.
            match = re.match(r"^(.+?)_(\d+)$", name)
            if match:
                base = match.group(1)
                num = int(match.group(2))
                if base not in patterns:
                    patterns[base] = []
                patterns[base].append((num, name))

            # Match patterns like "name_a", "name_b", etc.
            match = re.match(r"^(.+?)_([a-z])$", name)
            if match:
                base = match.group(1)
                letter = match.group(2)
                if base not in patterns:
                    patterns[base] = []
                patterns[base].append((ord(letter), name))

        for base, entries in patterns.items():
            if len(entries) >= 2:
                # Check if the numbers are sequential
                nums = sorted([e[0] for e in entries])
                if nums == list(range(min(nums), max(nums) + 1)):
                    groups.append([e[1] for _, e in sorted(entries)])

        return groups

    def _check_column_correlation(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        col1: str,
        col2: str,
    ) -> float:
        """Check if two columns have a strong correlation."""
        try:
            # Get distinct values of col1
            col1_values = conn.execute(
                f'SELECT DISTINCT "{col1}" FROM "{table_name}" WHERE "{col1}" IS NOT NULL'
            ).fetchall()

            if not col1_values:
                return 0.0

            # For each col1 value, check if col2 has consistent values
            total = 0
            consistent = 0
            for (val,) in col1_values:
                col2_vals = conn.execute(
                    f'SELECT DISTINCT "{col2}" FROM "{table_name}" WHERE "{col1}" = ?',
                    (val,),
                ).fetchall()
                total += 1
                if len(col2_vals) == 1:
                    consistent += 1

            return consistent / total if total > 0 else 0.0
        except Exception:
            return 0.0


# ── Schema Documenter ────────────────────────────────────────────────────────


class SchemaDocumenter:
    """Auto-generate schema documentation."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

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

    def generate_docs(self, title: str = "Tektos Database Schema") -> SchemaDoc:
        """
        Generate schema documentation.

        Args:
            title: Title for the documentation.

        Returns:
            SchemaDoc with documentation.
        """
        with self._connect() as conn:
            doc = SchemaDoc(
                title=title,
                version=0,
                generated_at=time.time(),
            )

            # Get all user tables
            tables = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND substr(name, 1, 1) != '_' "
                "ORDER BY name"
            ).fetchall()

            for (table_name,) in tables:
                safe_name = f'"{table_name}"'

                # Get columns
                columns = conn.execute(f"PRAGMA table_info({safe_name})").fetchall()

                # Get row count
                row_count = conn.execute(f"SELECT COUNT(*) FROM {safe_name}").fetchone()[0]

                # Get indexes
                indexes = conn.execute(f"PRAGMA index_list({safe_name})").fetchall()

                table_doc = {
                    "name": table_name,
                    "row_count": row_count,
                    "columns": [],
                    "indexes": [],
                }

                for col in columns:
                    table_doc["columns"].append(
                        {
                            "name": col[1],
                            "type": col[2] or "",
                            "notnull": bool(col[3]),
                            "default": col[4],
                            "primary_key": bool(col[5]),
                        }
                    )

                for idx in indexes:
                    idx_name = idx[1]
                    is_unique = bool(idx[2])
                    idx_cols = [
                        c[1] for c in conn.execute(f'PRAGMA index_info("{idx_name}")').fetchall()
                    ]
                    table_doc["indexes"].append(
                        {
                            "name": idx_name,
                            "unique": is_unique,
                            "columns": idx_cols,
                        }
                    )

                doc.tables.append(table_doc)

            # Detect relationships.
            # DIVERGENCE (13.2a): donor self-imported
            # `from .schema_evolution import RelationshipDetector` (same
            # module — the full engine's own class). In the kernel the
            # file is kernel/schema_evolution_full.py, so the import is
            # absolute to this module.
            from kernel.schema_evolution_full import RelationshipDetector

            detector = RelationshipDetector(self.db_path)
            relationships = detector.detect_relationships()
            for rel in relationships:
                doc.relationships.append(
                    {
                        "source_table": rel.source_table,
                        "source_column": rel.source_column,
                        "target_table": rel.target_table,
                        "target_column": rel.target_column,
                        "type": rel.relationship_type,
                        "confidence": rel.confidence,
                    }
                )

            return doc

    def to_markdown(self, doc: SchemaDoc | str) -> str:
        """Convert SchemaDoc to markdown format."""
        if isinstance(doc, str):
            # Handle case where a string is passed instead of SchemaDoc
            doc = SchemaDoc(title=doc, version=0, generated_at=time.time())
        lines = [
            f"# {doc.title}",
            "",
            f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(doc.generated_at))}",
            "",
            "## Tables",
            "",
        ]

        for table in doc.tables:
            lines.append(f"### `{table['name']}`")
            lines.append("")
            lines.append(f"Rows: {table['row_count']}")
            lines.append("")
            lines.append("| Column | Type | Not Null | Default | Primary Key |")
            lines.append("|--------|------|----------|---------|-------------|")

            for col in table["columns"]:
                pk = "Yes" if col["primary_key"] else "No"
                default = str(col["default"]) if col["default"] is not None else ""
                lines.append(
                    f"| {col['name']} | {col['type']} | "
                    f"{'Yes' if col['notnull'] else 'No'} | {default} | {pk} |"
                )

            if table["indexes"]:
                lines.append("")
                lines.append("**Indexes:**")
                lines.append("")
                for idx in table["indexes"]:
                    unique = "UNIQUE " if idx["unique"] else ""
                    cols = ", ".join(idx["columns"])
                    lines.append(f"- `{unique}{idx['name']}` on ({cols})")

            lines.append("")

        if doc.relationships:
            lines.append("## Relationships")
            lines.append("")
            lines.append("| Source | Source Column | Target | Target Column | Type | Confidence |")
            lines.append("|--------|--------------|--------|---------------|------|------------|")

            for rel in doc.relationships:
                lines.append(
                    f"| {rel['source_table']} | {rel['source_column']} | "
                    f"{rel['target_table']} | {rel['target_column']} | "
                    f"{rel['type']} | {rel['confidence']:.0%} |"
                )

            lines.append("")

        return "\n".join(lines)


# ── Health Monitor ───────────────────────────────────────────────────────────


class HealthMonitor:
    """Monitor database health: fragmentation, bloat, corruption."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

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

    def check_health(self) -> HealthReport:
        """
        Check database health.

        Returns:
            HealthReport with health metrics.
        """
        with self._connect() as conn:
            # Get page info
            page_size = conn.execute("PRAGMA page_size").fetchone()[0]
            page_count = conn.execute("PRAGMA page_count").fetchone()[0]
            freelist_count = conn.execute("PRAGMA freelist_count").fetchone()[0]

            total_pages = page_count
            free_pages = freelist_count
            total_pages - free_pages

            # Calculate fragmentation
            fragmentation_pct = (free_pages / total_pages * 100) if total_pages > 0 else 0.0

            # Calculate bloat
            bloat_bytes = free_pages * page_size

            # Check for corruption
            corruption_detected = self._check_corruption(conn)

            # Find missing indexes
            missing_indexes = self._find_missing_indexes(conn)

            # Find large tables
            large_tables = self._find_large_tables(conn, page_size)

            # Generate suggestions
            suggestions = []
            if fragmentation_pct > 20:
                suggestions.append(
                    f"Database is {fragmentation_pct:.1f}% fragmented — run VACUUM to reclaim space"
                )
            if bloat_bytes > 10 * 1024 * 1024:  # 10 MB
                suggestions.append(
                    f"Database has {bloat_bytes / (1024 * 1024):.1f} MB of free space — "
                    f"run VACUUM to reclaim"
                )
            if missing_indexes:
                suggestions.append(
                    f"Found {len(missing_indexes)} potential missing indexes — "
                    f"consider adding indexes on frequently queried columns"
                )
            if large_tables:
                suggestions.append(
                    f"Found {len(large_tables)} large tables — consider partitioning or archiving"
                )
            if corruption_detected:
                suggestions.append(
                    "Corruption detected — run integrity_check and consider restoring from backup"
                )

            # Calculate overall score
            score = 100.0
            score -= fragmentation_pct * 0.5  # Up to -50 for fragmentation
            if corruption_detected:
                score -= 50  # Major penalty for corruption
            if bloat_bytes > 50 * 1024 * 1024:  # 50 MB
                score -= 10
            score = max(0.0, min(100.0, score))

            return HealthReport(
                overall_score=round(score, 1),
                fragmentation_pct=round(fragmentation_pct, 2),
                bloat_bytes=bloat_bytes,
                corruption_detected=corruption_detected,
                missing_indexes=missing_indexes,
                large_tables=large_tables,
                suggestions=suggestions,
            )

    def _check_corruption(self, conn: sqlite3.Connection) -> bool:
        """Check for database corruption."""
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            return result[0] != "ok"
        except Exception:
            return True

    def _find_missing_indexes(self, conn: sqlite3.Connection) -> list[str]:
        """Find columns that might benefit from indexes."""
        missing = []

        tables = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "AND substr(name, 1, 1) != '_' "
            "ORDER BY name"
        ).fetchall()

        for (table_name,) in tables:
            safe_name = f'"{table_name}"'

            # Get columns
            columns = conn.execute(f"PRAGMA table_info({safe_name})").fetchall()

            # Get existing indexes
            indexes = conn.execute(f"PRAGMA index_list({safe_name})").fetchall()
            indexed_cols = set()
            for idx in indexes:
                idx_name = idx[1]
                idx_cols = [
                    c[1] for c in conn.execute(f'PRAGMA index_info("{idx_name}")').fetchall()
                ]
                indexed_cols.update(idx_cols)

            # Check for _id columns without indexes
            for col in columns:
                col_name = col[1]
                if col_name.lower().endswith("_id") and col_name not in indexed_cols:
                    missing.append(f"{table_name}.{col_name}")

        return missing

    def _find_large_tables(
        self,
        conn: sqlite3.Connection,
        page_size: int,
        threshold_mb: float = 10.0,
    ) -> list[str]:
        """Find tables larger than threshold."""
        large = []
        threshold_bytes = int(threshold_mb * 1024 * 1024)

        tables = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "AND substr(name, 1, 1) != '_' "
            "ORDER BY name"
        ).fetchall()

        for (table_name,) in tables:
            safe_name = f'"{table_name}"'
            # Estimate table size
            size = (
                conn.execute(f"SELECT COUNT(*) FROM {safe_name}").fetchone()[0] * page_size
            )  # Rough estimate

            if size > threshold_bytes:
                large.append(table_name)

        return large

    def get_health_history(self) -> list[dict]:
        """Get health check history from the health tracking table."""
        with self._connect() as conn:
            # Create health tracking table if needed
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {HEALTH_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    score REAL NOT NULL,
                    fragmentation_pct REAL NOT NULL,
                    bloat_bytes INTEGER NOT NULL,
                    corruption_detected INTEGER NOT NULL,
                    notes TEXT
                )
            """)

            # Record current health
            health = self.check_health()
            conn.execute(
                f"INSERT INTO {HEALTH_TABLE} "
                f"(timestamp, score, fragmentation_pct, bloat_bytes, corruption_detected, notes) "
                f"VALUES (?, ?, ?, ?, ?, ?)",
                (
                    time.time(),
                    health.overall_score,
                    health.fragmentation_pct,
                    health.bloat_bytes,
                    1 if health.corruption_detected else 0,
                    "; ".join(health.suggestions),
                ),
            )

            # Get history
            rows = conn.execute(
                f"SELECT * FROM {HEALTH_TABLE} ORDER BY timestamp DESC LIMIT 10"
            ).fetchall()

            return [
                {
                    "id": r[0],
                    "timestamp": r[1],
                    "score": r[2],
                    "fragmentation_pct": r[3],
                    "bloat_bytes": r[4],
                    "corruption_detected": bool(r[5]),
                    "notes": r[6],
                }
                for r in rows
            ]


# ── Schema Evolution Engine (Main Entry Point) ───────────────────────────────


class SchemaEvolutionEngine:
    """
    Full lifecycle schema management for Tektos.

    Combines MigrationEngine, SchemaDiffer, RelationshipDetector,
    NormalizationAnalyzer, SchemaDocumenter, and HealthMonitor
    into a single interface.

    Usage:
        engine = SchemaEvolutionEngine("/path/to/tektos.db")

        # Introspect
        schema = engine.introspect()

        # Diff schemas
        diff = engine.diff_schema(desired_schema)
        migration_sql = engine.generate_migration(diff)

        # Apply migrations
        engine.apply_migration("add_users_table", 1, "Add users table", migration_sql)

        # Analyze relationships
        relationships = engine.detect_relationships()

        # Check health
        health = engine.check_health()

        # Generate docs
        docs = engine.generate_docs()
    """

    def __init__(self, db_path: str | Path, backup_dir: str | None = None):
        self.db_path = Path(db_path)
        self.migrations = MigrationEngine(self.db_path)
        self.differ = SchemaDiffer(self.db_path)
        self.relationships = RelationshipDetector(self.db_path)
        self.normalization = NormalizationAnalyzer(self.db_path)
        self.documenter = SchemaDocumenter(self.db_path)
        self.health = HealthMonitor(self.db_path)

    # ── Convenience Methods ──────────────────────────────────────────────

    def introspect(self) -> dict[str, Any]:
        """Get current schema as dict."""
        return self.differ.get_current_schema()

    def diff_schema(
        self,
        desired_schema: dict[str, Any],
        current_schema: dict[str, Any] | None = None,
    ) -> SchemaDiff:
        """Diff desired schema against current."""
        return self.differ.diff_schemas(desired_schema, current_schema)

    def generate_migration(
        self,
        diff: SchemaDiff,
    ) -> str:
        """Generate SQL from a SchemaDiff."""
        return self.differ.generate_migration_sql(diff)

    def generate_migration_plan(
        self,
        desired_schema: dict[str, Any],
        current_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a full migration plan with SQL and metadata."""
        return self.differ.generate_migration_plan(desired_schema, current_schema)

    def apply_migration(
        self,
        migration_id: str,
        version: int,
        name: str,
        sql: str,
        checksum: str = "",
    ) -> bool:
        """Apply a versioned migration."""
        return self.migrations.apply_migration(migration_id, version, name, sql, checksum)

    def rollback_migration(self, migration_id: str) -> bool:
        """Roll back a migration."""
        return self.migrations.rollback_migration(migration_id)

    def get_current_version(self) -> int:
        """Get current schema version."""
        return self.migrations.get_current_version()

    def get_migration_history(self) -> list[dict]:
        """Get migration history."""
        return self.migrations.get_migration_history()

    def detect_relationships(self) -> list[Relationship]:
        """Detect relationships between tables."""
        return self.relationships.detect_relationships()

    def analyze_normalization(self) -> list[NormalizationIssue]:
        """Analyze schema for normalization issues."""
        return self.normalization.analyze_normalization()

    def generate_docs(self, title: str = "Tektos Database Schema") -> SchemaDoc:
        """Generate schema documentation."""
        return self.documenter.generate_docs(title)

    def to_markdown(self, title: str = "Tektos Database Schema") -> str:
        """Generate schema documentation as markdown."""
        doc = self.generate_docs(title)
        return self.documenter.to_markdown(doc)

    def check_health(self) -> HealthReport:
        """Check database health."""
        return self.health.check_health()

    def get_health_history(self) -> list[dict]:
        """Get health check history."""
        return self.health.get_health_history()

    def optimize(self) -> dict[str, Any]:
        """
        Run database optimization: VACUUM, rebuild indexes, analyze.

        Returns:
            Dict with optimization results.
        """
        results = {}

        with self._connect() as conn:
            conn.execute("VACUUM")
            results["vacuum"] = "completed"

            conn.execute("ANALYZE")
            results["analyze"] = "completed"

        # Run analysis
        normalization_issues = self.analyze_normalization()
        relationships = self.detect_relationships()
        health = self.check_health()
        schema = self.introspect()

        results["normalization_issues"] = len(normalization_issues)
        results["relationships_detected"] = len(relationships)
        results["health_score"] = health.overall_score
        results["tables_analyzed"] = len(schema)
        results["evolution_suggestions"] = health.suggestions

        log.info("Database optimization completed")
        return results

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


# ── Module-Level Convenience ─────────────────────────────────────────────────


def create_engine(db_path: str | Path, backup_dir: str | None = None) -> SchemaEvolutionEngine:
    """Create a SchemaEvolutionEngine instance."""
    return SchemaEvolutionEngine(db_path, backup_dir)
