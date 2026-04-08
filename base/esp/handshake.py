"""ESP board discovery and session initialisation.

Scans for connected boards via their udev symlinks, creates ESPSerial
instances, and registers them in the ESPRegistry. The actual per-board
handshake (INIT → ACK → START) is handled internally by ESPSerial —
this module is purely responsible for discovery and wiring.

Typical usage in the client runtime:

    manager = HandshakeManager(registry=self._esp_registry, config=config.esp)
    self._esp_boards = manager.discover()

    # Then in asyncio.gather():
    *[b.read_loop() for b in self._esp_boards],
"""

import logging
from pathlib import Path

from base.esp.serial import ESPSerial
from base.esp.registry import ESPRegistry, BoardState
from app.models.config import ESPConfig

logger = logging.getLogger(__name__)

_SYMLINK_PREFIX = "/dev/esp_port_"
_MAX_PORTS      = 16


class HandshakeManager:
    """Discovers connected ESP boards and creates ready-to-run ESPSerial instances.

    Args:
        registry: ESPRegistry to register discovered boards into.
        config:   ESPConfig containing port definitions and baud rate.
    """

    def __init__(self, registry: ESPRegistry, config: ESPConfig) -> None:
        self._registry = registry
        self._config   = config

    def discover(self) -> list[ESPSerial]:
        """Scan for connected boards and return configured ESPSerial instances.

        Each returned instance is ready for `asyncio.create_task(board.read_loop())`.
        Boards are assigned IDs 0..N in symlink order (/dev/esp_port_0 first).

        If explicit ports are defined in config.esp.ports, those are used.
        Otherwise, all present /dev/esp_port_* symlinks are used.
        """
        ports = self._resolve_ports()

        if not ports:
            logger.warning(
                "No ESP boards found. "
                "Check udev rules and physical connections. "
                "Expected symlinks: %s{0..N}", _SYMLINK_PREFIX
            )
            return []

        logger.info("Discovered %d ESP board(s): %s", len(ports), ports)

        boards: list[ESPSerial] = []
        for board_id, (port, baud) in enumerate(ports):
            board = ESPSerial(
                board_id=board_id,
                port=port,
                baud_rate=baud,
            )
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
            # Use the ports declared in config — filter to those present.
            result = []
            for entry in self._config.ports:
                if Path(entry.symlink).exists():
                    result.append((entry.symlink, entry.baud_rate))
                else:
                    logger.warning("Configured port not present: %s", entry.symlink)
            return result

        # Auto-discover: scan /dev/esp_port_0 .. /dev/esp_port_N.
        result = []
        default_baud = (
            self._config.ports[0].baud_rate
            if self._config.ports
            else 921600
        )
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
