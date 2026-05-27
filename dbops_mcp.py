"""
DBOps MCP Server
=================
Production-grade MCP server providing database provisioning, querying,
migration, and administration tools via the FastMCP framework.

Tools:
  - provision_database     [REAL/SIMULATED]  Create a SQLite DB or simulate Postgres.
  - apply_migrations       [SIMULATED]       Run Alembic-style migrations.
  - run_query              [REAL]             Execute read-only SQL on a SQLite DB.
  - list_tables            [REAL]             List tables and columns in a SQLite DB.
  - clone_database         [REAL]             Copy a SQLite file for staging.
  - create_read_only_user  [SIMULATED]       Generate read-only user SQL for Postgres.
  - get_db_stats           [REAL]             Row counts, file size, index count.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("dbops_mcp")

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
mcp = FastMCP("DBOps Tools")


# ===========================  HELPER FUNCTIONS  ============================


def _resolve_db_path(db_path: str) -> Path:
    """Resolve and validate a database file path.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    p = Path(db_path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Database file not found: {p}")
    return p


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection in read-only mode via URI."""
    uri = f"file:{db_path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _is_read_only_query(query: str) -> bool:
    """Return True if the SQL query is a safe read-only SELECT statement."""
    normalized = query.strip().upper()
    # Reject anything that is not a SELECT (or WITH … SELECT)
    if not (normalized.startswith("SELECT") or normalized.startswith("WITH")):
        return False
    # Reject dangerous keywords anywhere in the query
    forbidden = {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
                 "REPLACE", "TRUNCATE", "ATTACH", "DETACH", "PRAGMA"}
    tokens = set(normalized.split())
    if tokens & forbidden:
        return False
    return True


# ==============================  TOOLS  ====================================


@mcp.tool()
def provision_database(db_name: str, engine: str = "sqlite") -> str:
    """Provision a new database.

    * **sqlite** (default): Creates a real SQLite file on disk with a
      ``_metadata`` housekeeping table.
    * **postgres**: Returns a [SIMULATED] mock connection string.

    Args:
        db_name: Logical name for the database (used as the filename stem
                 for SQLite).
        engine:  ``sqlite`` or ``postgres``.

    Returns:
        Connection details and status message.
    """
    if not db_name or not db_name.strip():
        return "Error: db_name must be a non-empty string."

    db_name = db_name.strip()
    engine = engine.strip().lower()

    if engine == "postgres":
        mock_host = "pg-cluster-01.internal.example.com"
        mock_port = 5432
        mock_user = "admin"
        mock_pass = uuid.uuid4().hex[:16]
        conn_str = f"postgresql://{mock_user}:{mock_pass}@{mock_host}:{mock_port}/{db_name}"
        logger.info("[SIMULATED] Provisioned Postgres database '%s'", db_name)
        return "\n".join([
            f"[SIMULATED] Postgres database '{db_name}' provisioned.",
            f"  Host           : {mock_host}",
            f"  Port           : {mock_port}",
            f"  User           : {mock_user}",
            f"  Connection URL : {conn_str}",
        ])

    if engine != "sqlite":
        return f"Error: unsupported engine '{engine}'. Supported: sqlite, postgres."

    db_path = Path(f"{db_name}.sqlite3").resolve()
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS _metadata "
            "(key TEXT PRIMARY KEY, value TEXT)"
        )
        cursor.execute(
            "INSERT OR REPLACE INTO _metadata (key, value) VALUES (?, ?)",
            ("created_by", "dbops_mcp"),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as exc:
        logger.error("Failed to provision SQLite database: %s", exc)
        return f"Error: could not create database — {exc}"

    logger.info("Provisioned SQLite database at %s", db_path)
    return "\n".join([
        f"SQLite database '{db_name}' provisioned successfully.",
        f"  Path           : {db_path}",
        f"  DATABASE_URL   : sqlite:///{db_path}",
    ])


@mcp.tool()
def apply_migrations(db_url: str, dry_run: bool = False) -> str:
    """[SIMULATED] Run Alembic-style database migrations.

    Args:
        db_url:  Database connection URL (e.g. ``sqlite:///mydb.sqlite3``).
        dry_run: If ``True``, only report what *would* change without applying.

    Returns:
        List of applied (or pending) migration IDs and a summary.
    """
    if not db_url or not db_url.strip():
        return "Error: db_url must be a non-empty string."

    migration_ids = [
        f"m_{uuid.uuid4().hex[:6]}" for _ in range(3)
    ]
    descriptions = [
        "Add users table",
        "Create index on users.email",
        "Add audit_log table",
    ]

    mode = "DRY-RUN" if dry_run else "APPLIED"
    logger.info("[SIMULATED] Migrations %s for %s", mode, db_url)

    lines = [
        f"[SIMULATED] Migration run ({mode}) against: {db_url}",
        "",
    ]
    for mid, desc in zip(migration_ids, descriptions):
        status = "pending" if dry_run else "applied"
        lines.append(f"  [{status}] {mid} — {desc}")

    lines += [
        "",
        f"  Total migrations: {len(migration_ids)}",
        f"  Status          : {'No changes made (dry run)' if dry_run else 'All migrations applied successfully'}",
    ]
    return "\n".join(lines)


@mcp.tool()
def run_query(db_path: str, query: str) -> str:
    """Execute a **read-only** SQL query against a SQLite database.

    Only ``SELECT`` (and ``WITH … SELECT``) statements are allowed. Any
    attempt to run ``INSERT``, ``UPDATE``, ``DELETE``, ``DROP``, etc. will
    be rejected.

    Args:
        db_path: Path to the SQLite database file.
        query:   The SQL query to execute.

    Returns:
        Query results formatted as a table string, or an error message.
    """
    if not query or not query.strip():
        return "Error: query must be a non-empty string."

    if not _is_read_only_query(query):
        logger.warning("Rejected unsafe query: %s", query[:120])
        return (
            "Error: only read-only queries (SELECT) are permitted. "
            "INSERT, UPDATE, DELETE, DROP, and similar statements are blocked."
        )

    try:
        path = _resolve_db_path(db_path)
    except FileNotFoundError as exc:
        return str(exc)

    try:
        conn = _connect_readonly(path)
        cursor = conn.cursor()
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        conn.close()
    except sqlite3.Error as exc:
        logger.error("Query execution failed: %s", exc)
        return f"Error: query failed — {exc}"

    if not rows:
        return "Query returned 0 rows."

    # Format as a simple text table
    col_widths = [len(c) for c in columns]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))

    header = " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(columns))
    separator = "-+-".join("-" * w for w in col_widths)
    data_lines = []
    for row in rows:
        data_lines.append(
            " | ".join(str(v).ljust(col_widths[i]) for i, v in enumerate(row))
        )

    result = "\n".join([header, separator] + data_lines)
    logger.info("Query returned %d row(s) from %s", len(rows), path.name)
    return f"Query returned {len(rows)} row(s):\n\n{result}"


@mcp.tool()
def list_tables(db_path: str) -> str:
    """List all tables and their columns (with types) in a SQLite database.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        Formatted listing of every table and its column definitions.
    """
    try:
        path = _resolve_db_path(db_path)
    except FileNotFoundError as exc:
        return str(exc)

    try:
        conn = _connect_readonly(path)
        cursor = conn.cursor()

        # Get all table names
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]

        if not tables:
            conn.close()
            return f"Database '{path.name}' contains no tables."

        lines = [f"=== Tables in {path.name} ===", ""]
        for table in tables:
            cursor.execute(f"PRAGMA table_info([{table}])")  # noqa: S608
            cols = cursor.fetchall()
            lines.append(f"  {table}")
            for col in cols:
                # col: (cid, name, type, notnull, default, pk)
                cid, col_name, col_type, notnull, default_val, pk = col
                extras = []
                if pk:
                    extras.append("PK")
                if notnull:
                    extras.append("NOT NULL")
                if default_val is not None:
                    extras.append(f"DEFAULT {default_val}")
                suffix = f"  ({', '.join(extras)})" if extras else ""
                lines.append(f"    - {col_name} : {col_type or 'ANY'}{suffix}")
            lines.append("")

        conn.close()
        logger.info("Listed %d table(s) in %s", len(tables), path.name)
        return "\n".join(lines)
    except sqlite3.Error as exc:
        logger.error("Failed to list tables: %s", exc)
        return f"Error: could not list tables — {exc}"


@mcp.tool()
def clone_database(source_db: str, target_name: str) -> str:
    """Clone a SQLite database by copying the file.

    Useful for creating a staging or test copy of a production database.

    Args:
        source_db:   Path to the source SQLite database file.
        target_name: Stem name for the cloned database (e.g. ``mydb_staging``).

    Returns:
        Confirmation with the path to the new clone.
    """
    if not target_name or not target_name.strip():
        return "Error: target_name must be a non-empty string."

    try:
        source_path = _resolve_db_path(source_db)
    except FileNotFoundError as exc:
        return str(exc)

    target_name = target_name.strip()
    target_path = source_path.parent / f"{target_name}.sqlite3"

    if target_path.exists():
        return f"Error: target file already exists at {target_path}. Choose a different name."

    try:
        shutil.copy2(str(source_path), str(target_path))
    except OSError as exc:
        logger.error("Failed to clone database: %s", exc)
        return f"Error: clone failed — {exc}"

    source_size = source_path.stat().st_size
    logger.info("Cloned %s -> %s (%d bytes)", source_path.name, target_path.name, source_size)
    return "\n".join([
        f"Database cloned successfully.",
        f"  Source : {source_path}",
        f"  Target : {target_path}",
        f"  Size   : {source_size:,} bytes",
    ])


@mcp.tool()
def create_read_only_user(db_name: str, username: str) -> str:
    """[SIMULATED] Generate SQL commands to create a read-only Postgres user.

    This tool does *not* execute the commands; it returns the SQL statements
    that a DBA would run.

    Args:
        db_name:  Name of the target Postgres database.
        username: Desired username for the read-only role.

    Returns:
        The SQL commands that would create and configure the user.
    """
    if not db_name or not db_name.strip():
        return "Error: db_name must be a non-empty string."
    if not username or not username.strip():
        return "Error: username must be a non-empty string."

    db_name = db_name.strip()
    username = username.strip()
    password = uuid.uuid4().hex[:16]

    logger.info("[SIMULATED] Generated read-only user SQL for '%s' on db '%s'", username, db_name)

    sql = "\n".join([
        f"-- [SIMULATED] Read-only user creation for Postgres database '{db_name}'",
        f"-- Run these commands as a superuser / database owner.",
        "",
        f"CREATE ROLE {username} WITH LOGIN PASSWORD '{password}';",
        f"GRANT CONNECT ON DATABASE {db_name} TO {username};",
        f"GRANT USAGE ON SCHEMA public TO {username};",
        f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {username};",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {username};",
    ])
    return f"[SIMULATED] SQL commands for read-only user '{username}':\n\n{sql}"


@mcp.tool()
def get_db_stats(db_path: str) -> str:
    """Gather statistics for a SQLite database.

    Returns row counts per table, total file size on disk, and the number
    of indexes defined.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        Formatted statistics report.
    """
    try:
        path = _resolve_db_path(db_path)
    except FileNotFoundError as exc:
        return str(exc)

    file_size = path.stat().st_size

    try:
        conn = _connect_readonly(path)
        cursor = conn.cursor()

        # Tables and row counts
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]

        table_stats: list[tuple[str, int]] = []
        total_rows = 0
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM [{table}]")  # noqa: S608
            count = cursor.fetchone()[0]
            table_stats.append((table, count))
            total_rows += count

        # Indexes
        cursor.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index'"
        )
        num_indexes = cursor.fetchone()[0]

        conn.close()
    except sqlite3.Error as exc:
        logger.error("Failed to gather db stats: %s", exc)
        return f"Error: could not read database stats — {exc}"

    # Format human-readable size
    if file_size >= 1_048_576:
        size_str = f"{file_size / 1_048_576:.2f} MB"
    elif file_size >= 1024:
        size_str = f"{file_size / 1024:.1f} KB"
    else:
        size_str = f"{file_size} bytes"

    lines = [
        f"=== Database Stats: {path.name} ===",
        f"  File size    : {size_str} ({file_size:,} bytes)",
        f"  Tables       : {len(tables)}",
        f"  Total rows   : {total_rows:,}",
        f"  Indexes      : {num_indexes}",
        "",
        "  Row counts per table:",
    ]
    for table, count in table_stats:
        lines.append(f"    {table}: {count:,}")

    logger.info("Stats for %s — %d table(s), %d row(s), %s",
                path.name, len(tables), total_rows, size_str)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()
