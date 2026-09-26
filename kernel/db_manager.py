"""Tektos-Ultima-v1 — Database Manager

Full lifecycle database management for Tektos's own storage.
Enables the agent to create, modify, extend, and improve its databases:

    introspect → analyze → propose → validate → apply → verify

Capabilities:
    1. Introspection — full schema + data distribution analysis
    2. DDL — CREATE TABLE, ALTER TABLE, DROP TABLE, CREATE INDEX, DROP INDEX
    3. DML — INSERT, UPDATE, DELETE with safety checks
    4. Data export/import — JSON, CSV, SQL dump
    5. Backup/restore — full and incremental backups
    6. Schema analysis — detect anomalies, suggest optimizations
    7. Schema evolution — integrate with SchemaEvolutionEngine
    8. Query execution — parameterized SQL with result inspection

Architecture:
    DatabaseManager (public API)
        ├── SchemaManager (DDL operations)
        ├── DataAnalyzer (introspection + analysis)
        ├── BackupManager (backup/restore)
        └── QueryExecutor (safe DML execution)

Usage:
    manager = DatabaseManager(db_path)

    # Introspect
    schema = manager.introspect()
    analysis = manager.analyze_table("sessions")

    # Modify schema
    manager.create_table("new_table", columns={...})
    manager.add_column("sessions", "new_field", "TEXT")
    manager.drop_column("sessions", "old_field")

    # Execute queries
    results = manager.execute_query("SELECT * FROM sessions LIMIT 10")
    manager.execute_dml("UPDATE sessions SET status = ? WHERE id = ?", ["active", "abc123"])

    # Backup/restore
    manager.backup("/path/to/backup.db")
    manager.restore("/path/to/backup.db")

    # Export/import
    manager.export_table("sessions", format="json", path="/tmp/sessions.json")
    manager.import_table("sessions", format="json", path="/tmp/sessions.json")
"""

from __future__ import annotations

import csv
import json
import logging
import shutil
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("kosmos.db_manager")

# ── Safety Limits ────────────────────────────────────────────────────────────

MAX_QUERY_ROWS = 10000
MAX_QUERY_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_COLUMNS_PER_TABLE = 256
MAX_INDEXES_PER_TABLE = 64
MAX_TABLES = 128
BACKUP_RETENTION_DAYS = 30

# ── Data Classes ─────────────────────────────────────────────────────────────


@dataclass
class ColumnInfo:
    """Information about a single column."""

    cid: int
    name: str
    col_type: str
    notnull: bool
    default_value: Any
    pk: bool
    estimated_null_count: int = 0
    estimated_distinct_count: int = 0


@dataclass
class IndexInfo:
    """Information about a single index."""

    name: str
    table: str
    unique: bool
    columns: list[str] = field(default_factory=list)


@dataclass
class TableInfo:
    """Information about a single table."""

    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    row_count: int = 0
    size_bytes: int = 0
    data_size_bytes: int = 0
    index_size_bytes: int = 0


@dataclass
class SchemaSnapshot:
    """Complete schema snapshot at a point in time."""

    version: int
    tables: dict[str, TableInfo] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Analysis result for a single table."""

    table_name: str
    row_count: int
    column_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    missing_indexes: list[str] = field(default_factory=list)
    duplicate_indexes: list[str] = field(default_factory=list)
    large_tables: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    data_quality_issues: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BackupInfo:
    """Information about a backup."""

    path: str
    timestamp: float
    size_bytes: int
    source_db: str
    table_count: int
    row_count: int
    checksum: str = ""


# ── Schema Manager ───────────────────────────────────────────────────────────


class SchemaManager:
    """DDL operations: CREATE, ALTER, DROP tables and indexes."""

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
        # Only allow alphanumeric + underscore, max 64 chars
        import re

        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$", name):
            raise ValueError(f"Invalid identifier: {name}")
        return f'"{name}"'

    def create_table(
        self,
        table_name: str,
        columns: dict[str, str],
        primary_key: str | None = None,
        if_not_exists: bool = True,
    ) -> bool:
        """
        Create a new table.

        Args:
            table_name: Name of the table to create.
            columns: Dict of {column_name: column_type}.
            primary_key: Column name to use as primary key (auto-increment).
            if_not_exists: If True, silently skip if table exists.

        Returns:
            True if table was created, False if it already existed.
        """
        import re

        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$", table_name):
            raise ValueError(f"Invalid table name: {table_name}")

        if len(columns) > MAX_COLUMNS_PER_TABLE:
            raise ValueError(f"Too many columns: {len(columns)} > {MAX_COLUMNS_PER_TABLE}")

        with self._connect() as conn:
            # Check if table already exists
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            if existing:
                if if_not_exists:
                    return False
                raise ValueError(f"Table '{table_name}' already exists")

            col_defs = []
            for col_name, col_type in columns.items():
                if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$", col_name):
                    raise ValueError(f"Invalid column name: {col_name}")
                col_defs.append(f"{self._safe_identifier(col_name)} {col_type}")

            # Only add explicit PRIMARY KEY clause if the primary_key column
            # doesn't already declare it in its type (e.g. "INTEGER PRIMARY KEY")
            if primary_key:
                pk_col_type = columns.get(primary_key, "").upper()
                if "PRIMARY KEY" not in pk_col_type:
                    col_defs.append(f"PRIMARY KEY ({self._safe_identifier(primary_key)})")

            sql = f"CREATE TABLE {'IF NOT EXISTS' if if_not_exists else ''} {self._safe_identifier(table_name)} ({', '.join(col_defs)})"
            conn.execute(sql)
            log.info("Created table: %s with %d columns", table_name, len(columns))
            return True

    def drop_table(self, table_name: str, if_exists: bool = True) -> bool:
        """Drop a table. Returns True if dropped, False if it didn't exist."""
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            if not exists:
                return False
            conn.execute(
                f"DROP TABLE {'IF EXISTS' if if_exists else ''} {self._safe_identifier(table_name)}"
            )
            log.info("Dropped table: %s", table_name)
            return True

    def add_column(
        self,
        table_name: str,
        column_name: str,
        column_type: str,
        default: Any = None,
        notnull: bool = False,
    ) -> bool:
        """
        Add a column to an existing table.

        Returns True if column was added, False if it already exists.
        """
        with self._connect() as conn:
            # Check if column already exists
            columns = conn.execute(
                f"PRAGMA table_info({self._safe_identifier(table_name)})"
            ).fetchall()
            col_names = {col[1] for col in columns}

            if column_name in col_names:
                return False

            col_def = f"{self._safe_identifier(column_name)} {column_type}"
            if default is not None:
                if isinstance(default, str):
                    col_def += f" DEFAULT '{default}'"
                elif isinstance(default, bool):
                    col_def += f" DEFAULT {1 if default else 0}"
                else:
                    col_def += f" DEFAULT {default}"
            if notnull:
                col_def += " NOT NULL"

            conn.execute(f"ALTER TABLE {self._safe_identifier(table_name)} ADD COLUMN {col_def}")
            log.info("Added column '%s' to table '%s'", column_name, table_name)
            return True

    def drop_column(self, table_name: str, column_name: str) -> bool:
        """
        Drop a column from a table.

        Note: SQLite requires recreating the table to drop a column.
        This is done atomically with a backup.
        """
        with self._connect() as conn:
            # Check if column exists
            columns = conn.execute(
                f"PRAGMA table_info({self._safe_identifier(table_name)})"
            ).fetchall()
            col_names = {col[1] for col in columns}

            if column_name not in col_names:
                return False

            # Get all columns except the one to drop
            keep_cols = [col[1] for col in columns if col[1] != column_name]
            keep_cols_sql = ", ".join(self._safe_identifier(c) for c in keep_cols)

            # Create backup table
            backup_name = f"{table_name}__drop_{column_name}__{int(time.time())}"
            conn.execute(
                f"CREATE TABLE {self._safe_identifier(backup_name)} AS "
                f"SELECT {keep_cols_sql} FROM {self._safe_identifier(table_name)}"
            )

            # Drop original and rename backup
            conn.execute(f"DROP TABLE {self._safe_identifier(table_name)}")
            conn.execute(
                f"ALTER TABLE {self._safe_identifier(backup_name)} "
                f"RENAME TO {self._safe_identifier(table_name)}"
            )

            log.info("Dropped column '%s' from table '%s'", column_name, table_name)
            return True

    def rename_table(self, old_name: str, new_name: str) -> bool:
        """Rename a table."""
        import re

        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$", new_name):
            raise ValueError(f"Invalid table name: {new_name}")

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (old_name,),
            ).fetchone()
            if not existing:
                raise ValueError(f"Table '{old_name}' does not exist")

            existing_new = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (new_name,),
            ).fetchone()
            if existing_new:
                raise ValueError(f"Table '{new_name}' already exists")

            conn.execute(
                f"ALTER TABLE {self._safe_identifier(old_name)} "
                f"RENAME TO {self._safe_identifier(new_name)}"
            )
            log.info("Renamed table '%s' → '%s'", old_name, new_name)
            return True

    def create_index(
        self,
        index_name: str,
        table_name: str,
        columns: list[str],
        unique: bool = False,
    ) -> bool:
        """Create an index on one or more columns."""
        with self._connect() as conn:
            # Check index count limit
            indexes = conn.execute(
                f"PRAGMA index_list({self._safe_identifier(table_name)})"
            ).fetchall()
            if len(indexes) >= MAX_INDEXES_PER_TABLE:
                raise ValueError(
                    f"Too many indexes on '{table_name}': {len(indexes)} >= {MAX_INDEXES_PER_TABLE}"
                )

            # Check if index already exists
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (index_name,),
            ).fetchone()
            if existing:
                return False

            col_list = ", ".join(self._safe_identifier(c) for c in columns)
            unique_str = "UNIQUE " if unique else ""
            conn.execute(
                f"CREATE {unique_str}INDEX {self._safe_identifier(index_name)} "
                f"ON {self._safe_identifier(table_name)} ({col_list})"
            )
            log.info("Created index '%s' on '%s'(%s)", index_name, table_name, columns)
            return True

    def drop_index(self, index_name: str) -> bool:
        """Drop an index."""
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (index_name,),
            ).fetchone()
            if not existing:
                return False
            conn.execute(f"DROP INDEX {self._safe_identifier(index_name)}")
            log.info("Dropped index: %s", index_name)
            return True

    def rename_column(self, table_name: str, old_name: str, new_name: str) -> bool:
        """
        Rename a column.

        Note: SQLite 3.25.0+ supports ALTER TABLE ... RENAME COLUMN.
        Falls back to table recreation for older versions.
        """
        import re

        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$", new_name):
            raise ValueError(f"Invalid column name: {new_name}")

        with self._connect() as conn:
            # Check if column exists
            columns = conn.execute(
                f"PRAGMA table_info({self._safe_identifier(table_name)})"
            ).fetchall()
            col_names = {col[1] for col in columns}

            if old_name not in col_names:
                raise ValueError(f"Column '{old_name}' does not exist in '{table_name}'")

            if new_name in col_names:
                raise ValueError(f"Column '{new_name}' already exists in '{table_name}'")

            try:
                conn.execute(
                    f"ALTER TABLE {self._safe_identifier(table_name)} "
                    f"RENAME COLUMN {self._safe_identifier(old_name)} "
                    f"TO {self._safe_identifier(new_name)}"
                )
            except sqlite3.OperationalError:
                # Fallback: recreate table
                keep_cols = [col[1] for col in columns]
                keep_cols_sql = ", ".join(self._safe_identifier(c) for c in keep_cols)

                backup_name = f"{table_name}__rename__{int(time.time())}"
                conn.execute(
                    f"CREATE TABLE {self._safe_identifier(backup_name)} AS "
                    f"SELECT {keep_cols_sql} FROM {self._safe_identifier(table_name)}"
                )
                conn.execute(f"DROP TABLE {self._safe_identifier(table_name)}")
                conn.execute(
                    f"ALTER TABLE {self._safe_identifier(backup_name)} "
                    f"RENAME TO {self._safe_identifier(table_name)}"
                )

            log.info(
                "Renamed column '%s' → '%s' in table '%s'",
                old_name,
                new_name,
                table_name,
            )
            return True


# ── Data Analyzer ────────────────────────────────────────────────────────────


class DataAnalyzer:
    """Introspection and analysis of database contents."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def _safe_identifier(self, name: str) -> str:
        """Escape a SQL identifier safely."""
        import re

        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$", name):
            raise ValueError(f"Invalid identifier: {name}")
        return f'"{name}"'

    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    def introspect(self) -> SchemaSnapshot:
        """Get complete schema snapshot."""
        with self._connect() as conn:
            tables = {}

            # Get all user tables
            table_names = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                    "AND substr(name, 1, 1) != '_' "
                    "ORDER BY name"
                ).fetchall()
            ]

            for table_name in table_names:
                safe_name = self._safe_identifier(table_name)

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
                indexes = []
                for idx_data in conn.execute(f"PRAGMA index_list({safe_name})").fetchall():
                    idx_name = idx_data[1]
                    is_unique = bool(idx_data[2])
                    # Get index columns
                    idx_cols = [
                        col[1]
                        for col in conn.execute(
                            f"PRAGMA index_info({self._safe_identifier(idx_name)})"
                        ).fetchall()
                    ]
                    indexes.append(
                        IndexInfo(
                            name=idx_name,
                            table=table_name,
                            unique=is_unique,
                            columns=idx_cols,
                        )
                    )

                # Get row count
                row_count = conn.execute(f"SELECT COUNT(*) FROM {safe_name}").fetchone()[0]

                # Get table size
                page_size = conn.execute("PRAGMA page_size").fetchone()[0]
                page_count = conn.execute("PRAGMA page_count").fetchone()[0]
                size_bytes = page_size * page_count

                tables[table_name] = TableInfo(
                    name=table_name,
                    columns=columns,
                    indexes=indexes,
                    row_count=row_count,
                    size_bytes=size_bytes,
                )

            return SchemaSnapshot(
                version=0,
                tables=tables,
                metadata={"introspected_at": time.time(), "db_path": str(self.db_path)},
            )

    def analyze_table(self, table_name: str, sample_size: int = 1000) -> AnalysisResult:
        """
        Analyze a table's data quality, distribution, and optimization opportunities.

        Returns an AnalysisResult with suggestions for improvement.
        """
        with self._connect() as conn:
            safe_name = self._safe_identifier(table_name)

            # Check table exists
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            ).fetchone()
            if not existing:
                raise ValueError(f"Table '{table_name}' does not exist")

            # Get columns
            columns = conn.execute(f"PRAGMA table_info({safe_name})").fetchall()
            column_names = [col[1] for col in columns]

            # Get row count
            row_count = conn.execute(f"SELECT COUNT(*) FROM {safe_name}").fetchone()[0]

            # Analyze each column
            column_stats = {}
            for col_name in column_names:
                safe_col = self._safe_identifier(col_name)

                # Null count
                null_count = conn.execute(
                    f"SELECT COUNT(*) FROM {safe_name} WHERE {safe_col} IS NULL"
                ).fetchone()[0]

                # Distinct count
                distinct_count = conn.execute(
                    f"SELECT COUNT(DISTINCT {safe_col}) FROM {safe_name}"
                ).fetchone()[0]

                # Sample values for type inference
                sample_values = conn.execute(
                    f"SELECT {safe_col} FROM {safe_name} WHERE {safe_col} IS NOT NULL LIMIT {min(sample_size, row_count)}"
                ).fetchall()

                # Type distribution
                type_dist = {}
                for (val,) in sample_values:
                    if val is None:
                        continue
                    t = type(val).__name__
                    type_dist[t] = type_dist.get(t, 0) + 1

                # String length stats (for TEXT columns)
                length_stats = None
                col_type = ""
                for c in columns:
                    if c[1] == col_name:
                        col_type = c[2] or ""
                        break
                if "TEXT" in col_type.upper():
                    length_stats = conn.execute(
                        f"SELECT MIN(LENGTH({safe_col})), MAX(LENGTH({safe_col})), AVG(LENGTH({safe_col})) "
                        f"FROM {safe_name} WHERE {safe_col} IS NOT NULL"
                    ).fetchone()

                column_stats[col_name] = {
                    "null_count": null_count,
                    "null_pct": round(null_count / max(row_count, 1) * 100, 2),
                    "distinct_count": distinct_count,
                    "distinct_pct": round(distinct_count / max(row_count, 1) * 100, 2),
                    "type_distribution": type_dist,
                    "length_stats": {
                        "min": length_stats[0] if length_stats else None,
                        "max": length_stats[1] if length_stats else None,
                        "avg": round(length_stats[2], 2)
                        if length_stats and length_stats[2]
                        else None,
                    }
                    if length_stats
                    else None,
                }

            # Check for missing indexes on foreign-key-like columns
            missing_indexes = []
            indexes = conn.execute(f"PRAGMA index_list({safe_name})").fetchall()
            indexed_cols = set()
            for idx_data in indexes:
                idx_name = idx_data[1]
                idx_cols = [
                    col[1]
                    for col in conn.execute(
                        f"PRAGMA index_info({self._safe_identifier(idx_name)})"
                    ).fetchall()
                ]
                indexed_cols.update(idx_cols)

            # Suggest indexes on columns that look like foreign keys
            for col_name in column_names:
                if col_name.lower().endswith("_id") and col_name not in indexed_cols:
                    missing_indexes.append(
                        f"Column '{col_name}' looks like a foreign key — consider adding an index"
                    )

            # Check for duplicate indexes
            duplicate_indexes = []
            seen_col_sets = {}
            for idx_data in indexes:
                idx_name = idx_data[1]
                idx_cols = tuple(
                    col[1]
                    for col in conn.execute(
                        f"PRAGMA index_info({self._safe_identifier(idx_name)})"
                    ).fetchall()
                )
                if idx_cols in seen_col_sets:
                    duplicate_indexes.append(
                        f"Index '{idx_name}' duplicates index '{seen_col_sets[idx_cols]}'"
                    )
                else:
                    seen_col_sets[idx_cols] = idx_name

            # Generate suggestions
            suggestions = []
            if row_count > 10000 and not missing_indexes:
                suggestions.append(
                    f"Table has {row_count} rows — consider adding indexes on frequently queried columns"
                )

            for col_name, stats in column_stats.items():
                if stats["null_pct"] > 50:
                    suggestions.append(
                        f"Column '{col_name}' is NULL in {stats['null_pct']:.0f}% of rows — "
                        f"consider if it should be NOT NULL with a default"
                    )
                if stats["distinct_pct"] < 5 and stats["distinct_count"] > 1:
                    suggestions.append(
                        f"Column '{col_name}' has only {stats['distinct_count']} distinct values — "
                        f"consider if it should be an INTEGER with a lookup table"
                    )

            # Data quality issues
            data_quality_issues = []
            for col_name, stats in column_stats.items():
                if stats["null_pct"] > 80:
                    data_quality_issues.append(
                        {
                            "table": table_name,
                            "column": col_name,
                            "issue": "high_null_rate",
                            "detail": f"{stats['null_pct']:.0f}% NULL values",
                            "severity": "warning",
                        }
                    )

            return AnalysisResult(
                table_name=table_name,
                row_count=row_count,
                column_stats=column_stats,
                missing_indexes=missing_indexes,
                duplicate_indexes=duplicate_indexes,
                suggestions=suggestions,
                data_quality_issues=data_quality_issues,
            )

    def analyze_all_tables(self) -> dict[str, AnalysisResult]:
        """Analyze all tables in the database."""
        snapshot = self.introspect()
        results = {}
        for table_name in snapshot.tables:
            try:
                results[table_name] = self.analyze_table(table_name)
            except Exception as e:
                log.warning("Failed to analyze table '%s': %s", table_name, e)
        return results

    def get_table_sample(self, table_name: str, limit: int = 100) -> list[dict]:
        """Get a sample of records from a table."""
        with self._connect() as conn:
            safe_name = self._safe_identifier(table_name)
            rows = conn.execute(f"SELECT * FROM {safe_name} LIMIT {limit}").fetchall()
            columns = [col[1] for col in conn.execute(f"PRAGMA table_info({safe_name})").fetchall()]
            return [{col: val for col, val in zip(columns, row)} for row in rows]

    def _safe_identifier(self, name: str) -> str:
        """Escape a SQL identifier safely."""
        import re

        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$", name):
            raise ValueError(f"Invalid identifier: {name}")
        return f'"{name}"'


# ── Backup Manager ───────────────────────────────────────────────────────────


class BackupManager:
    """Backup and restore operations."""

    def __init__(self, db_path: str | Path, backup_dir: str | None = None):
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir) if backup_dir else self.db_path.parent / "backups"

    def _connect(self):
        """Get a raw connection."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def backup(
        self,
        backup_path: str | None = None,
        compress: bool = False,
        include_metadata: bool = True,
    ) -> BackupInfo:
        """
        Create a backup of the database.

        Args:
            backup_path: Where to save the backup. Defaults to backups/<timestamp>.db
            compress: If True, gzip the backup.
            include_metadata: If True, include a metadata JSON file.

        Returns:
            BackupInfo with details about the backup.
        """
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        if backup_path is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_path = str(self.backup_dir / f"tektos_{timestamp}.db")

        backup_path = Path(backup_path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)

        # Use SQLite's backup API for a consistent snapshot
        src = self._connect()
        dst = sqlite3.connect(str(backup_path))
        src.backup(dst)
        dst.close()
        src.close()

        # Get backup info
        size_bytes = backup_path.stat().st_size
        with self._connect() as conn:
            table_count = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
            row_count = (
                conn.execute(
                    "SELECT SUM(cnt) FROM (SELECT COUNT(*) as cnt FROM sqlite_master JOIN "
                    "(SELECT name FROM sqlite_master WHERE type='table') t ON 1=1)"
                ).fetchone()[0]
                or 0
            )

        # Calculate checksum
        import hashlib

        with open(backup_path, "rb") as f:
            checksum = hashlib.sha256(f.read()).hexdigest()[:16]

        info = BackupInfo(
            path=str(backup_path),
            timestamp=time.time(),
            size_bytes=size_bytes,
            source_db=str(self.db_path),
            table_count=table_count,
            row_count=row_count,
            checksum=checksum,
        )

        # Save metadata
        if include_metadata:
            meta_path = backup_path.with_suffix(".meta.json")
            meta_path.write_text(json.dumps(info.__dict__, indent=2))

        # Compress if requested
        if compress:
            import gzip

            compressed_path = backup_path.with_suffix(".db.gz")
            with open(backup_path, "rb") as f_in:
                with gzip.open(compressed_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            backup_path.unlink()  # Remove uncompressed
            info.path = str(compressed_path)
            info.size_bytes = compressed_path.stat().st_size

        log.info("Backup created: %s (%d bytes, %d tables)", backup_path, size_bytes, table_count)
        return info

    def restore(self, backup_path: str, verify: bool = True) -> bool:
        """
        Restore the database from a backup.

        WARNING: This replaces the current database entirely.

        Args:
            backup_path: Path to the backup file.
            verify: If True, verify the backup before restoring.

        Returns:
            True if restore succeeded.
        """
        backup_path = Path(backup_path)

        if not backup_path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")

        # Decompress if needed
        if backup_path.suffix == ".gz":
            import gzip

            decompressed = backup_path.with_suffix(".db")
            with gzip.open(backup_path, "rb") as f_in:
                with open(decompressed, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            backup_path = decompressed

        if verify:
            # Verify the backup is a valid SQLite database
            try:
                test_conn = sqlite3.connect(str(backup_path))
                test_conn.execute("SELECT COUNT(*) FROM sqlite_master")
                test_conn.close()
            except sqlite3.DatabaseError as e:
                raise ValueError(f"Invalid backup file: {e}")

        # Backup current database before restoring
        current_backup = self.backup(
            backup_path=str(self.backup_dir / f"pre_restore_{int(time.time())}.db"),
            compress=False,
            include_metadata=False,
        )
        log.info("Pre-restore backup created: %s", current_backup.path)

        # Checkpoint WAL on current database before restoring
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()

        # Remove current database and any associated WAL/SHM files
        for ext in ["", "-wal", "-shm"]:
            f = Path(str(self.db_path) + ext)
            if f.exists():
                f.unlink()

        # Copy backup to database location
        shutil.copy2(str(backup_path), str(self.db_path))

        # Checkpoint WAL on restored database
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()

        log.info("Database restored from: %s", backup_path)
        return True

    def list_backups(self) -> list[BackupInfo]:
        """List all available backups."""
        if not self.backup_dir.exists():
            return []

        backups = []
        for meta_file in sorted(self.backup_dir.glob("*.meta.json")):
            try:
                meta = json.loads(meta_file.read_text())
                backups.append(BackupInfo(**meta))
            except (json.JSONDecodeError, KeyError):
                continue

        return backups

    def cleanup_old_backups(self, retention_days: int = BACKUP_RETENTION_DAYS) -> int:
        """Remove backups older than retention_days. Returns count removed."""
        cutoff = time.time() - (retention_days * 86400)
        removed = 0

        for meta_file in self.backup_dir.glob("*.meta.json"):
            try:
                meta = json.loads(meta_file.read_text())
                if meta.get("timestamp", 0) < cutoff:
                    meta_file.unlink()
                    # Also remove the backup file
                    db_file = self.backup_dir / meta["path"].split("/")[-1]
                    if db_file.exists():
                        db_file.unlink()
                    removed += 1
            except (json.JSONDecodeError, KeyError, FileNotFoundError):
                continue

        if removed:
            log.info("Cleaned up %d old backup(s)", removed)
        return removed


# ── Query Executor ───────────────────────────────────────────────────────────


class QueryExecutor:
    """Safe query execution with DML protection."""

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

    def execute_query(
        self,
        sql: str,
        params: tuple | None = None,
        limit: int = MAX_QUERY_ROWS,
    ) -> list[dict[str, Any]]:
        """
        Execute a SELECT query and return results as list of dicts.

        Args:
            sql: SQL query (SELECT only for safety).
            params: Query parameters.
            limit: Maximum rows to return.

        Returns:
            List of dicts, one per row.
        """
        # Safety: only allow SELECT queries
        stripped = sql.strip().upper()
        if not stripped.startswith("SELECT"):
            raise ValueError(
                "execute_query only allows SELECT statements. "
                "Use execute_dml() for INSERT/UPDATE/DELETE."
            )

        with self._connect() as conn:
            cursor = conn.execute(sql, params or ())
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(limit)

            result = []
            total_bytes = 0
            for row in rows:
                row_dict = dict(zip(columns, row))
                # Check size
                row_bytes = len(json.dumps(row_dict).encode())
                total_bytes += row_bytes
                if total_bytes > MAX_QUERY_BYTES:
                    log.warning("Query result exceeds %d bytes — truncating", MAX_QUERY_BYTES)
                    break
                result.append(row_dict)

            return result

    def execute_dml(
        self,
        sql: str,
        params: tuple | None = None,
        require_confirmation: bool = True,
    ) -> int:
        """
        Execute a DML statement (INSERT/UPDATE/DELETE).

        Args:
            sql: SQL statement.
            params: Statement parameters.
            require_confirmation: If True, requires a WHERE clause for safety.

        Returns:
            Number of rows affected.
        """
        stripped = sql.strip().upper()

        # Safety: require WHERE clause for UPDATE/DELETE
        if require_confirmation:
            if stripped.startswith("UPDATE") or stripped.startswith("DELETE"):
                if "WHERE" not in stripped:
                    raise ValueError(
                        "UPDATE/DELETE without WHERE clause is dangerous. "
                        "Add a WHERE clause or set require_confirmation=False."
                    )

        with self._connect() as conn:
            cursor = conn.execute(sql, params or ())
            return cursor.rowcount

    def execute_transaction(self, statements: list[tuple[str, tuple]]) -> list[int]:
        """
        Execute multiple statements in a single transaction.

        Args:
            statements: List of (sql, params) tuples.

        Returns:
            List of row counts for each statement.
        """
        results = []
        with self._connect() as conn:
            for sql, params in statements:
                cursor = conn.execute(sql, params or ())
                results.append(cursor.rowcount)
        return results

    def explain_query(self, sql: str, params: tuple | None = None) -> dict[str, Any]:
        """
        Get query plan for a SELECT statement.

        Returns:
            Dict with query plan details.
        """
        if not sql.strip().upper().startswith("SELECT"):
            raise ValueError("explain_query only works with SELECT statements")

        with self._connect() as conn:
            plan_rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}", params or ()).fetchall()
            plan = [
                {
                    "id": row[0],
                    "parent": row[1],
                    "notused": row[2],
                    "detail": row[3],
                }
                for row in plan_rows
            ]

            # Also get row estimate
            count_rows = conn.execute(f"SELECT COUNT(*) FROM ({sql})", params or ()).fetchall()
            estimated_rows = count_rows[0][0] if count_rows else 0

            return {
                "plan": plan,
                "estimated_rows": estimated_rows,
                "uses_index": any("USING INDEX" in p["detail"] for p in plan),
            }


# ── Database Manager (Main Entry Point) ──────────────────────────────────────


class DatabaseManager:
    """
    Full lifecycle database management for Tektos.

    Combines SchemaManager, DataAnalyzer, BackupManager, and QueryExecutor
    into a single interface.

    Usage:
        manager = DatabaseManager("/path/to/tektos.db")

        # Introspect
        schema = manager.introspect()
        analysis = manager.analyze_table("sessions")

        # Modify schema
        manager.create_table("new_table", columns={"id": "INTEGER PRIMARY KEY", "name": "TEXT"})
        manager.add_column("sessions", "new_field", "TEXT", default="")

        # Execute queries
        results = manager.execute_query("SELECT * FROM sessions LIMIT 10")
        manager.execute_dml("UPDATE sessions SET status = ? WHERE id = ?", ["active", "abc123"])

        # Backup/restore
        manager.backup()
        manager.restore("/path/to/backup.db")

        # Export/import
        manager.export_table("sessions", format="json", path="/tmp/sessions.json")
        manager.import_table("sessions", format="json", path="/tmp/sessions.json")

        # Full analysis
        all_analysis = manager.analyze_all()
    """

    def __init__(self, db_path: str | Path, backup_dir: str | None = None):
        self.db_path = Path(db_path)
        self.schema = SchemaManager(self.db_path)
        self.analyzer = DataAnalyzer(self.db_path)
        self.backup_mgr = BackupManager(self.db_path, backup_dir)
        self.query = QueryExecutor(self.db_path)

        # Schema evolution engine (lazy import to avoid circular deps)
        self._evolution: Any = None

    @property
    def evolution(self):
        """Lazy-load SchemaEvolutionEngine."""
        if self._evolution is None:
            from kernel.schema_evolution_full import SchemaEvolutionEngine

            # DIVERGENCE (13.2a): the donor's db_manager lazy-imports the
            # FULL lifecycle engine (tektos/schema_evolution.py, 1644 LOC —
            # MigrationEngine + SchemaDiffer + RelationshipDetector +
            # NormalizationAnalyzer + SchemaDocumenter + HealthMonitor),
            # NOT the smaller migrations engine (tektos/migrations/
            # schema_evolution.py, 758 LOC) that T8c-9 ported to
            # kernel/schema_evolution.py and that powers the /api/schema/*
            # routes. Both engines are named SchemaEvolutionEngine but are
            # distinct classes with different method surfaces. The live
            # donor's /api/db/optimize runs THIS full engine (it returns
            # normalization_issues / relationships_detected / health_score).
            # Ported verbatim to kernel/schema_evolution_full.py.
            self._evolution = SchemaEvolutionEngine(self.db_path)
        return self._evolution

    # ── Convenience Methods ──────────────────────────────────────────────

    def introspect(self) -> SchemaSnapshot:
        """Get complete schema snapshot."""
        return self.analyzer.introspect()

    def analyze_table(self, table_name: str, sample_size: int = 1000) -> AnalysisResult:
        """Analyze a single table."""
        return self.analyzer.analyze_table(table_name, sample_size)

    def analyze_all(self) -> dict[str, AnalysisResult]:
        """Analyze all tables."""
        return self.analyzer.analyze_all_tables()

    def get_table_sample(self, table_name: str, limit: int = 100) -> list[dict]:
        """Get a sample of records from a table."""
        return self.analyzer.get_table_sample(table_name, limit)

    def create_table(
        self,
        table_name: str,
        columns: dict[str, str],
        primary_key: str | None = None,
        if_not_exists: bool = True,
    ) -> bool:
        """Create a new table."""
        return self.schema.create_table(table_name, columns, primary_key, if_not_exists)

    def drop_table(self, table_name: str, if_exists: bool = True) -> bool:
        """Drop a table."""
        return self.schema.drop_table(table_name, if_exists)

    def add_column(
        self,
        table_name: str,
        column_name: str,
        column_type: str,
        default: Any = None,
        notnull: bool = False,
    ) -> bool:
        """Add a column to an existing table."""
        return self.schema.add_column(table_name, column_name, column_type, default, notnull)

    def drop_column(self, table_name: str, column_name: str) -> bool:
        """Drop a column from a table."""
        return self.schema.drop_column(table_name, column_name)

    def rename_table(self, old_name: str, new_name: str) -> bool:
        """Rename a table."""
        return self.schema.rename_table(old_name, new_name)

    def rename_column(self, table_name: str, old_name: str, new_name: str) -> bool:
        """Rename a column."""
        return self.schema.rename_column(table_name, old_name, new_name)

    def create_index(
        self,
        index_name: str,
        table_name: str,
        columns: list[str],
        unique: bool = False,
    ) -> bool:
        """Create an index."""
        return self.schema.create_index(index_name, table_name, columns, unique)

    def drop_index(self, index_name: str) -> bool:
        """Drop an index."""
        return self.schema.drop_index(index_name)

    def execute_query(
        self,
        sql: str,
        params: tuple | None = None,
        limit: int = MAX_QUERY_ROWS,
    ) -> list[dict[str, Any]]:
        """Execute a SELECT query."""
        return self.query.execute_query(sql, params, limit)

    def execute_dml(
        self,
        sql: str,
        params: tuple | None = None,
        require_confirmation: bool = True,
    ) -> int:
        """Execute a DML statement."""
        return self.query.execute_dml(sql, params, require_confirmation)

    def execute_transaction(self, statements: list[tuple[str, tuple]]) -> list[int]:
        """Execute multiple statements in a transaction."""
        return self.query.execute_transaction(statements)

    def explain_query(self, sql: str, params: tuple | None = None) -> dict[str, Any]:
        """Get query plan for a SELECT statement."""
        return self.query.explain_query(sql, params)

    def export_table(
        self,
        table_name: str,
        format: str = "json",
        path: str | None = None,
        include_header: bool = True,
    ) -> str:
        """
        Export a table to a file.

        Args:
            table_name: Table to export.
            format: Output format — "json", "csv", or "sql".
            path: Output file path. Defaults to table_name.<format>.
            include_header: For CSV, include column headers.

        Returns:
            Path to the exported file.
        """
        if path is None:
            path = f"{table_name}.{format}"

        # Get all data
        rows = self.execute_query(f"SELECT * FROM {table_name}")
        if not rows:
            log.warning("Table '%s' is empty — nothing to export", table_name)
            return path

        if format == "json":
            with open(path, "w") as f:
                json.dump(rows, f, indent=2, default=str)
        elif format == "csv":
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                if include_header:
                    writer.writeheader()
                writer.writerows(rows)
        elif format == "sql":
            with open(path, "w") as f:
                columns = list(rows[0].keys())
                for row in rows:
                    values = []
                    for col in columns:
                        val = row[col]
                        if val is None:
                            values.append("NULL")
                        elif isinstance(val, str):
                            escaped = val.replace("'", "''")
                            values.append(f"'{escaped}'")
                        else:
                            values.append(str(val))
                    f.write(
                        f"INSERT INTO {table_name} ({', '.join(columns)}) "
                        f"VALUES ({', '.join(values)});\n"
                    )
        else:
            raise ValueError(f"Unsupported format: {format}")

        log.info("Exported %d rows from '%s' to %s (%s)", len(rows), table_name, path, format)
        return path

    def import_table(
        self,
        table_name: str,
        format: str,
        path: str,
        mode: str = "insert",
        clear_first: bool = False,
    ) -> int:
        """
        Import data into a table.

        Args:
            table_name: Target table.
            format: Input format — "json", "csv", or "sql".
            path: Input file path.
            mode: "insert" (append) or "replace" (truncate then insert).
            clear_first: If True, clear the table before importing.

        Returns:
            Number of rows imported.
        """
        if clear_first or mode == "replace":
            self.execute_dml(f"DELETE FROM {table_name}")

        if format == "json":
            data = json.loads(Path(path).read_text())
            if not data:
                return 0

            # Get columns from first row
            columns = list(data[0].keys())
            placeholders = ", ".join(["?"] * len(columns))
            col_list = ", ".join(columns)

            rows_imported = 0
            for row in data:
                values = [row.get(col) for col in columns]
                self.execute_dml(
                    f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})",
                    tuple(values),
                )
                rows_imported += 1

        elif format == "csv":
            with open(path) as f:
                reader = csv.DictReader(f)
                rows_imported = 0
                for row in reader:
                    columns = list(row.keys())
                    placeholders = ", ".join(["?"] * len(columns))
                    col_list = ", ".join(columns)
                    values = [row.get(col) for col in columns]
                    self.execute_dml(
                        f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})",
                        tuple(values),
                    )
                    rows_imported += 1

        elif format == "sql":
            sql_content = Path(path).read_text()
            statements = [s.strip() for s in sql_content.split(";") if s.strip()]
            rows_imported = 0
            for stmt in statements:
                if stmt.upper().startswith("INSERT"):
                    self.execute_dml(stmt)
                    rows_imported += 1

        else:
            raise ValueError(f"Unsupported format: {format}")

        log.info("Imported %d rows into '%s' from %s (%s)", rows_imported, table_name, path, format)
        return rows_imported

    def backup(
        self,
        backup_path: str | None = None,
        compress: bool = False,
        include_metadata: bool = True,
    ) -> BackupInfo:
        """Create a database backup. Delegates to BackupManager."""
        return self.backup_mgr.backup(backup_path, compress, include_metadata)

    def restore(self, backup_path: str, verify: bool = True) -> bool:
        """Restore the database from a backup. Delegates to BackupManager."""
        return self.backup_mgr.restore(backup_path, verify)

    def list_backups(self) -> list[BackupInfo]:
        """List all available backups. Delegates to BackupManager."""
        return self.backup_mgr.list_backups()

    def cleanup_old_backups(self, retention_days: int = BACKUP_RETENTION_DAYS) -> int:
        """Remove backups older than retention_days. Delegates to BackupManager."""
        return self.backup_mgr.cleanup_old_backups(retention_days)

    def get_stats(self) -> dict[str, Any]:
        """Get database statistics."""
        snapshot = self.introspect()
        total_rows = sum(t.row_count for t in snapshot.tables.values())
        total_size = sum(t.size_bytes for t in snapshot.tables.values())

        return {
            "db_path": str(self.db_path),
            "table_count": len(snapshot.tables),
            "total_rows": total_rows,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "tables": {
                name: {
                    "row_count": t.row_count,
                    "column_count": len(t.columns),
                    "index_count": len(t.indexes),
                    "size_bytes": t.size_bytes,
                }
                for name, t in snapshot.tables.items()
            },
        }

    # ── Schema Evolution Methods ─────────────────────────────────────────

    def diff_schema(
        self,
        desired_schema: dict[str, Any],
        current_schema: dict[str, Any] | None = None,
    ) -> Any:
        """Diff desired schema against current. Delegates to SchemaEvolutionEngine."""
        return self.evolution.diff_schema(desired_schema, current_schema)

    def generate_migration(
        self,
        diff: Any,
    ) -> str:
        """Generate SQL from a SchemaDiff."""
        return self.evolution.generate_migration(diff)

    def generate_migration_plan(
        self,
        desired_schema: dict[str, Any],
        current_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a full migration plan with SQL and metadata."""
        return self.evolution.generate_migration_plan(desired_schema, current_schema)

    def apply_migration(
        self,
        migration_id: str,
        version: int,
        name: str,
        sql: str,
        checksum: str = "",
    ) -> bool:
        """Apply a versioned migration."""
        return self.evolution.apply_migration(migration_id, version, name, sql, checksum)

    def rollback_migration(self, migration_id: str) -> bool:
        """Roll back a migration."""
        return self.evolution.rollback_migration(migration_id)

    def get_current_version(self) -> int:
        """Get current schema version."""
        return self.evolution.get_current_version()

    def get_migration_history(self) -> list[dict]:
        """Get migration history."""
        return self.evolution.get_migration_history()

    def detect_relationships(self) -> list[Any]:
        """Detect relationships between tables."""
        return self.evolution.detect_relationships()

    def analyze_normalization(self) -> list[Any]:
        """Analyze schema for normalization issues."""
        return self.evolution.analyze_normalization()

    def generate_docs(self, title: str = "Tektos Database Schema") -> Any:
        """Generate schema documentation."""
        return self.evolution.generate_docs(title)

    def to_markdown(self, title: str = "Tektos Database Schema") -> str:
        """Generate schema documentation as markdown."""
        return self.evolution.to_markdown(title)

    def check_health(self) -> Any:
        """Check database health."""
        return self.evolution.check_health()

    def get_health_history(self) -> list[dict]:
        """Get health check history."""
        return self.evolution.get_health_history()

    def optimize(self) -> dict[str, Any]:
        """
        Run database optimization: VACUUM, rebuild indexes, analyze.

        Returns:
            Dict with optimization results.
        """
        results = {}

        # VACUUM — rebuild the database file
        with self._connect() as conn:
            conn.execute("VACUUM")
            results["vacuum"] = "completed"

            # ANALYZE — update query planner statistics
            conn.execute("ANALYZE")
            results["analyze"] = "completed"

        # Run analysis to get post-optimization stats
        analysis = self.analyze_all()
        results["tables_analyzed"] = len(analysis)
        results["total_rows"] = sum(a.row_count for a in analysis.values())
        results["suggestions"] = [s for a in analysis.values() for s in a.suggestions]

        # Run evolution-based optimization
        evolution_results = self.evolution.optimize()
        results["normalization_issues"] = evolution_results.get("normalization_issues", 0)
        results["relationships_detected"] = evolution_results.get("relationships_detected", 0)
        results["health_score"] = evolution_results.get("health_score", 100)
        results["evolution_suggestions"] = evolution_results.get("suggestions", [])

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


def create_manager(db_path: str | Path, backup_dir: str | None = None) -> DatabaseManager:
    """Create a DatabaseManager instance."""
    return DatabaseManager(db_path, backup_dir)
