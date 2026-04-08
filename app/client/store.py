"""Project client-side data store.

Lightweight store for the client. The client's DB is optional
(disabled by default). Useful for local data logging and
debugging on the Pi itself.
"""

import logging
from typing import Any

from base.db.sqlite import Database
from base.config import DatabaseConfig
from app.models.tables import CLIENT_TABLES

logger = logging.getLogger(__name__)


class ClientStore:
    """Client-side database operations.

    Args:
        db_config: Database connection settings.
    """

    def __init__(self, db_config: DatabaseConfig) -> None:
        self._db = Database(db_config)

    @property
    def db(self) -> Database:
        return self._db

    # ======================== Lifecycle ======================== #

    async def start(self) -> None:
        """Connect and ensure all tables exist."""
        await self._db.connect()
        if not self._db.is_connected:
            return

        for name, schema in CLIENT_TABLES:
            await self._db.create_table(name, schema)
        logger.info("ClientStore ready — %d tables initialised", len(CLIENT_TABLES))

    async def stop(self) -> None:
        await self._db.close()

    # ======================== Project-Specific Methods ======================== #

    # PROJECT-SPECIFIC: Add your client-side DB methods here, e.g.:
    #
    # async def log_reading(self, data: dict[str, Any]) -> None:
    #     await self._db.insert("sensor_readings", data)
    #
    # async def get_recent_readings(self, limit: int = 100) -> list[dict[str, Any]]:
    #     return await self._db.fetch_all(
    #         "SELECT * FROM sensor_readings ORDER BY id DESC LIMIT ?", (limit,)
    #     )
