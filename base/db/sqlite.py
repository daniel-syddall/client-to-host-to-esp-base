"""Async SQLite wrapper built on aiosqlite.

Provides a clean interface for database operations with automatic
connection management, WAL mode for concurrent reads, and helper
methods for common patterns. Designed to be reusable across all
projects that use the base framework.
"""

import logging
from pathlib import Path
from typing import Any

import aiosqlite

from base.config import DatabaseConfig

logger = logging.getLogger(__name__)


class Database:
    """Async SQLite database with connection management.

    Args:
        config: DatabaseConfig with enabled flag, filename, and path.
    """

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._db_path = Path(config.path) / config.filename
        self._conn: aiosqlite.Connection | None = None

    # ======================== Properties ======================== #

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def path(self) -> Path:
        return self._db_path

    @property
    def is_connected(self) -> bool:
        return self._conn is not None

    # ======================== Lifecycle ======================== #

    async def connect(self) -> None:
        """Open the database connection.

        Creates the data directory and database file if they don't exist.
        Enables WAL mode for better concurrent read performance.
        """
        if not self._config.enabled:
            logger.info("Database disabled in config — skipping connect")
            return

        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = await aiosqlite.connect(str(self._db_path))
        self._conn.row_factory = aiosqlite.Row

        # WAL mode: allows reads while writing, better for our use case.
        await self._conn.execute("PRAGMA journal_mode=WAL")
        # Foreign keys on by default.
        await self._conn.execute("PRAGMA foreign_keys=ON")

        logger.info("Database connected: %s", self._db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Database closed: %s", self._db_path)

    # ======================== Table Management ======================== #

    async def create_table(self, name: str, schema: str) -> None:
        """Create a table if it doesn't exist.

        Args:
            name: Table name.
            schema: Column definitions (everything inside the parentheses).

        Example:
            await db.create_table("sensors", '''
                sensor_id TEXT PRIMARY KEY,
                name TEXT DEFAULT '',
                value REAL DEFAULT 0,
                unit TEXT DEFAULT '',
                first_seen TEXT,
                last_seen TEXT
            ''')
        """
        if not self._conn:
            return
        sql = f"CREATE TABLE IF NOT EXISTS {name} ({schema})"
        await self._conn.execute(sql)
        await self._conn.commit()
        logger.debug("Table ensured: %s", name)

    async def drop_table(self, name: str) -> None:
        """Drop a table if it exists."""
        if not self._conn:
            return
        await self._conn.execute(f"DROP TABLE IF EXISTS {name}")
        await self._conn.commit()

    async def table_exists(self, name: str) -> bool:
        """Check if a table exists."""
        if not self._conn:
            return False
        cursor = await self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        )
        return await cursor.fetchone() is not None

    # ======================== Write Operations ======================== #

    async def execute(self, sql: str, params: tuple = ()) -> None:
        """Execute a single SQL statement (INSERT, UPDATE, DELETE, etc.)."""
        if not self._conn:
            return
        await self._conn.execute(sql, params)
        await self._conn.commit()

    async def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        """Execute a SQL statement with multiple parameter sets (batch insert)."""
        if not self._conn:
            return
        await self._conn.executemany(sql, params_list)
        await self._conn.commit()

    async def insert(self, table: str, data: dict[str, Any]) -> None:
        """Insert a single row from a dictionary.

        Args:
            table: Table name.
            data: Column-value mapping.
        """
        if not self._conn:
            return
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        await self._conn.execute(sql, tuple(data.values()))
        await self._conn.commit()

    async def upsert(self, table: str, data: dict[str, Any], conflict_column: str) -> None:
        """Insert or update a row on conflict.

        Args:
            table: Table name.
            data: Column-value mapping.
            conflict_column: Column to detect conflicts on (typically the PK).
        """
        if not self._conn:
            return
        columns = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        updates = ", ".join(f"{k}=excluded.{k}" for k in data if k != conflict_column)
        sql = (
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT({conflict_column}) DO UPDATE SET {updates}"
        )
        await self._conn.execute(sql, tuple(data.values()))
        await self._conn.commit()

    # ======================== Read Operations ======================== #

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        """Fetch a single row as a dictionary."""
        if not self._conn:
            return None
        cursor = await self._conn.execute(sql, params)
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Fetch all matching rows as a list of dictionaries."""
        if not self._conn:
            return []
        cursor = await self._conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def count(self, table: str, where: str = "", params: tuple = ()) -> int:
        """Count rows in a table with optional WHERE clause."""
        if not self._conn:
            return 0
        sql = f"SELECT COUNT(*) as cnt FROM {table}"
        if where:
            sql += f" WHERE {where}"
        result = await self.fetch_one(sql, params)
        return result["cnt"] if result else 0

    # ======================== Maintenance ======================== #

    async def prune(self, table: str, max_rows: int, order_column: str = "rowid") -> int:
        """Delete oldest rows if table exceeds max_rows.

        Keeps the newest max_rows entries based on order_column.
        Returns the number of rows deleted.
        """
        if not self._conn:
            return 0

        current = await self.count(table)
        if current <= max_rows:
            return 0

        excess = current - max_rows
        sql = (
            f"DELETE FROM {table} WHERE rowid IN "
            f"(SELECT rowid FROM {table} ORDER BY {order_column} ASC LIMIT ?)"
        )
        await self._conn.execute(sql, (excess,))
        await self._conn.commit()
        logger.debug("Pruned %d rows from %s", excess, table)
        return excess

    async def size_mb(self) -> float:
        """Get the database file size in megabytes."""
        if self._db_path.exists():
            return self._db_path.stat().st_size / (1024 * 1024)
        return 0.0
