"""Project host-side data store.

Provides typed methods for storing and querying project data
on the host. Built on top of the base Database class.
"""

import logging
from typing import Any

from base.db.sqlite import Database
from base.config import DatabaseConfig
from app.models.tables import HOST_TABLES
from app.models.config import StorageConfig

logger = logging.getLogger(__name__)


class HostStore:
    """Host-side database operations.

    Args:
        db_config: Database connection settings.
        storage_config: Storage limits and toggle settings.
    """

    def __init__(self, db_config: DatabaseConfig, storage_config: StorageConfig) -> None:
        self._db = Database(db_config)
        self._storage = storage_config

    @property
    def db(self) -> Database:
        return self._db

    # ======================== Lifecycle ======================== #

    async def start(self) -> None:
        """Connect and ensure all tables exist."""
        await self._db.connect()
        if not self._db.is_connected:
            return

        for name, schema in HOST_TABLES:
            await self._db.create_table(name, schema)
        logger.info("HostStore ready — %d tables initialised", len(HOST_TABLES))

    async def stop(self) -> None:
        await self._db.close()

    # ======================== Project-Specific Methods ======================== #

    # PROJECT-SPECIFIC: Add your host-side DB methods here, e.g.:
    #
    # async def upsert_reading(self, data: dict[str, Any]) -> None:
    #     await self._db.upsert("sensor_readings", data, "sensor_id")
    #
    # async def get_all_readings(self) -> list[dict[str, Any]]:
    #     return await self._db.fetch_all(
    #         "SELECT * FROM sensor_readings ORDER BY timestamp DESC"
    #     )
    #
    # async def count_readings(self) -> int:
    #     return await self._db.count("sensor_readings")

    # ======================== Maintenance ======================== #

    async def prune_all(self) -> dict[str, int]:
        """Prune all tables to max_records. Returns {table: rows_deleted}.

        PROJECT-SPECIFIC: Add prune calls for each of your tables.
        """
        max_r = self._storage.max_records
        results = {}
        # Example:
        # results["sensor_readings"] = await self._db.prune("sensor_readings", max_r, "timestamp")
        pruned = {k: v for k, v in results.items() if v > 0}
        if pruned:
            logger.info("Pruned: %s", pruned)
        return results

    async def stats(self) -> dict[str, Any]:
        """Return a summary of current database contents.

        PROJECT-SPECIFIC: Add counts for each of your tables.
        """
        return {
            "db_size_mb": round(await self._db.size_mb(), 2),
            # Example:
            # "sensor_readings": await self.count_readings(),
        }
