"""ESP board discovery and session initialisation.

Scans for connected boards via their udev symlinks, creates ESPSerial
instances, and registers them in the ESPRegistry. The actual per-board
handshake (INIT → ACK → START) is handled internally by ESPSerial —
this module is purely responsible for discovery and wiring.

Typical usage in the client runtime:

    manager = HandshakeManager(registry=self._esp_registry, config=config.esp)

    # Pass a callback; watch_loop calls it for every board as it appears.
    asyncio.create_task(
        manager.watch_loop(self._on_board_discovered)
    )
"""

import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable

from base.esp.serial import ESPSerial
from base.esp.registry import ESPRegistry, BoardState
from app.models.config import ESPConfig

logger = logging.getLogger(__name__)

_SYMLINK_PREFIX = "/dev/esp_port_"
_MAX_PORTS      = 16

# Type alias for the board-discovered callback.
BoardAddedCallback = Callable[[ESPSerial], Awaitable[None]]


class HandshakeManager:
    """Discovers connected ESP boards and creates ready-to-run ESPSerial instances.

    Args:
        registry: ESPRegistry to register discovered boards into.
        config:   ESPConfig containing port definitions and baud rate.
    """

    def __init__(self, registry: ESPRegistry, config: ESPConfig) -> None:
        self._registry    = registry
        self._config      = config
        self._known_ports: set[str] = set()
        self._next_id:     int      = 0

    # ======================== Dynamic Discovery ======================== #

    async def watch_loop(
        self,
        on_board_added: BoardAddedCallback,
        scan_interval:  float = 5.0,
    ) -> None:
        """Discover boards at startup then watch for new ports being plugged in.

        On each scan interval, resolves the current set of available port
        paths. Any path that has not been seen before triggers a new
        ESPSerial instance which is registered and passed to on_board_added.

        Boards that disappear mid-run are handled by ESPSerial.read_loop()
        internally — it keeps retrying the same port path until the device
        comes back.

        Args:
            on_board_added: Async callback invoked for each newly discovered
                            board. Signature: async (board: ESPSerial) -> None
            scan_interval:  Seconds between port scans. Default 5.0.
        """
        logger.info("ESP port watcher started (scan_interval=%.1fs)", scan_interval)
        while True:
            ports = self._resolve_ports()
            for port, baud in sorted(ports):
                if port in self._known_ports:
                    continue

                board_id = self._next_id
                self._next_id += 1
                self._known_ports.add(port)

                board = ESPSerial(
                    board_id=board_id,
                    port=port,
                    baud_rate=baud,
                )
                self._registry.register(board_id, port)
                self._wire_registry(board)

                logger.info(
                    "New ESP board discovered: id=%d port=%s",
                    board_id, port,
                )
                await on_board_added(board)

            await asyncio.sleep(scan_interval)

    # ======================== One-shot Discovery (legacy) ======================== #

    def discover(self) -> list[ESPSerial]:
        """Synchronous one-shot scan. Returns all currently connected boards.

        Prefer watch_loop() for new code — it handles hot-plug and initial
        discovery in a single coroutine.
        """
        ports = self._resolve_ports()

        if not ports:
            logger.warning(
                "No ESP boards found. "
                "Check udev rules and physical connections. "
                "Expected symlinks: %s{0..N}", _SYMLINK_PREFIX
            )
            return []

        logger.info("Discovered %d ESP board(s): %s", len(ports), [p for p, _ in ports])

        boards: list[ESPSerial] = []
        for port, baud in sorted(ports):
            if port in self._known_ports:
                continue
            board_id = self._next_id
            self._next_id += 1
            self._known_ports.add(port)

            board = ESPSerial(board_id=board_id, port=port, baud_rate=baud)
            self._registry.register(board_id, port)
            self._wire_registry(board)
            boards.append(board)

        return boards

    # ======================== Internal ======================== #

    def _resolve_ports(self) -> list[tuple[str, int]]:
        """Return (port_path, baud_rate) pairs for connected boards.

        Prefers explicit config entries; falls back to auto-discovery.
        """
        if self._config.ports:
            result = []
            for entry in self._config.ports:
                if Path(entry.symlink).exists():
                    result.append((entry.symlink, entry.baud_rate))
                else:
                    logger.debug("Configured port not present: %s", entry.symlink)
            return result

        # Auto-discover: scan /dev/esp_port_0 .. /dev/esp_port_N.
        default_baud = 921600
        result = []
        for i in range(_MAX_PORTS):
            path = Path(f"{_SYMLINK_PREFIX}{i}")
            if path.exists():
                result.append((str(path), default_baud))
        return result

    def _wire_registry(self, board: ESPSerial) -> None:
        """Connect ESPSerial events to ESPRegistry state transitions."""

        async def _on_running(board_id: int) -> None:
            self._registry.set_state(board_id, BoardState.RUNNING)

        async def _on_disconnect(board_id: int) -> None:
            self._registry.set_state(board_id, BoardState.DISCONNECTED)

        board.on_running(_on_running)
        board.on_disconnect(_on_disconnect)
