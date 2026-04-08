"""Base FastAPI server with lifecycle management.

Provides a thin wrapper around FastAPI + Uvicorn that integrates
with the async runtime. Designed to be extended by each project
with its own routes.
"""

import asyncio
import logging
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from base.config import APIConfig

logger = logging.getLogger(__name__)


class APIServer:
    """Managed FastAPI server that runs inside the existing async loop.

    Args:
        config: APIConfig with host, port, and enabled flag.
        title: Name shown in the auto-generated docs.
    """

    def __init__(self, config: APIConfig, title: str = "Base API") -> None:
        self._config = config
        self.app = FastAPI(title=title)
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self._server: uvicorn.Server | None = None

    # ======================== Properties ======================== #

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    # ======================== Static Files ======================== #

    def mount_static(self, directory: str | Path, route: str = "/static") -> None:
        """Mount a static file directory (CSS, JS, images)."""
        path = Path(directory)
        if path.exists():
            self.app.mount(route, StaticFiles(directory=str(path)), name="static")
            logger.info("Static files mounted: %s -> %s", path, route)

    # ======================== Lifecycle ======================== #

    async def start(self) -> None:
        """Start the Uvicorn server as an async task."""
        if not self._config.enabled:
            logger.info("API server disabled in config — skipping")
            return

        config = uvicorn.Config(
            app=self.app,
            host=self._config.host,
            port=self._config.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        logger.info("API server starting on %s:%s", self._config.host, self._config.port)
        await self._server.serve()

    async def stop(self) -> None:
        """Signal the server to shut down."""
        if self._server:
            self._server.should_exit = True
            logger.info("API server stopping")
