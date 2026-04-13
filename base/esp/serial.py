"""Async serial connection to a single ESP board.

Wraps pyserial-asyncio to integrate cleanly with the existing asyncio
event loop. Each instance manages one physical board:

  - Connects to the board's udev symlink (/dev/esp_port_N).
  - Runs the full INIT → ACK → START handshake on every (re)connect,
    so board re-initialisation after a disconnect is automatic.
  - Parses the mixed binary/JSON frame stream and dispatches to handlers.
  - Reconnects automatically after disconnection.

Usage:
    board = ESPSerial(board_id=0, port="/dev/esp_port_0")
    board.on_control(my_control_handler)
    board.on_data(my_data_handler)
    board.on_running(my_running_callback)
    board.on_disconnect(my_disconnect_callback)
    asyncio.create_task(board.read_loop())
"""

import asyncio
import logging
from typing import Any, Callable, Awaitable

import serial_asyncio

from base.esp.protocol import (
    MAGIC_1, MAGIC_2, HEADER_SIZE,
    build_init, build_start,
    parse_control, parse_binary_length,
)

logger = logging.getLogger(__name__)

# Callback type aliases.
ControlHandler  = Callable[[int, dict[str, Any]], Awaitable[None]]
DataHandler     = Callable[[int, bytes], Awaitable[None]]
EventCallback   = Callable[[int], Awaitable[None]]

_HANDSHAKE_TIMEOUT = 10.0   # seconds to wait for ACK from the board
_READ_CHUNK        = 512    # bytes per serial read call


class ESPSerial:
    """Async serial connection to one ESP board.

    Args:
        board_id:           Session-scoped ID assigned by the Pi.
        port:               Device path (e.g. '/dev/esp_port_0').
        baud_rate:          Serial baud rate.
        reconnect_interval: Seconds between reconnect attempts on failure.
    """

    def __init__(
        self,
        board_id: int,
        port: str,
        baud_rate: int = 921600,
        reconnect_interval: float = 5.0,
    ) -> None:
        self._board_id           = board_id
        self._port               = port
        self._baud_rate          = baud_rate
        self._reconnect_interval = reconnect_interval

        self._writer: asyncio.StreamWriter | None = None
        self._connected = False

        # Handler registries.
        self._control_handlers: list[ControlHandler] = []
        self._data_handlers:    list[DataHandler]    = []
        self._on_running:       list[EventCallback]  = []
        self._on_disconnect:    list[EventCallback]  = []

    # ======================== Properties ======================== #

    @property
    def board_id(self) -> int:
        return self._board_id

    @property
    def port(self) -> str:
        return self._port

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ======================== Handler Registration ======================== #

    def on_control(self, handler: ControlHandler) -> None:
        """Register a handler for incoming JSON control frames.

        Signature: async (board_id, msg_dict) -> None
        """
        self._control_handlers.append(handler)

    def on_data(self, handler: DataHandler) -> None:
        """Register a handler for incoming binary data frames.

        Signature: async (board_id, payload_bytes) -> None
        """
        self._data_handlers.append(handler)

    def on_running(self, callback: EventCallback) -> None:
        """Register a callback fired when the board transitions to RUNNING.

        This fires after START is sent and the board begins its task.
        Fires again on every successful reconnect + re-handshake.

        Signature: async (board_id) -> None
        """
        self._on_running.append(callback)

    def on_disconnect(self, callback: EventCallback) -> None:
        """Register a callback fired when the serial connection drops.

        Signature: async (board_id) -> None
        """
        self._on_disconnect.append(callback)

    # ======================== Write ======================== #

    async def write(self, data: bytes) -> None:
        """Send raw bytes to the board. No-op if not connected."""
        if not self._writer or not self._connected:
            logger.warning("Board %d: write skipped (not connected)", self._board_id)
            return
        try:
            self._writer.write(data)
            await self._writer.drain()
        except Exception as e:
            logger.error("Board %d: write failed: %s", self._board_id, e)

    # ======================== Main Loop ======================== #

    async def read_loop(self) -> None:
        """Open the serial connection, run handshake, dispatch frames.

        Reconnects automatically on any error or disconnect. The full
        handshake (INIT → ACK → START) reruns on every reconnect, ensuring
        the board always re-initialises cleanly.

        Run this as a long-lived asyncio task.
        """
        while True:
            try:
                await self._connect_and_run()
            except Exception as e:
                logger.error("Board %d: connection error: %s", self._board_id, e)

            if self._connected:
                self._connected = False
                logger.warning(
                    "Board %d: disconnected — retrying in %.1fs",
                    self._board_id, self._reconnect_interval,
                )
                for cb in self._on_disconnect:
                    asyncio.create_task(cb(self._board_id))

            await asyncio.sleep(self._reconnect_interval)

    # ======================== Connection Lifecycle ======================== #

    async def _connect_and_run(self) -> None:
        """Open serial, handshake, then run the frame read loop."""
        logger.info(
            "Board %d: opening %s at %d baud",
            self._board_id, self._port, self._baud_rate,
        )
        reader, writer = await serial_asyncio.open_serial_connection(
            url=self._port,
            baudrate=self._baud_rate,
        )
        self._writer    = writer
        self._connected = True
        logger.info("Board %d: serial open", self._board_id)

        # Run the full handshake before entering the data loop.
        await self._run_handshake(reader)

        # Handshake complete — board is now running.
        logger.info("Board %d: handshake complete — RUNNING", self._board_id)
        for cb in self._on_running:
            asyncio.create_task(cb(self._board_id))

        # Enter the continuous frame read loop.
        await self._read_frames(reader)

    async def _run_handshake(self, reader: asyncio.StreamReader) -> None:
        """Send INIT, wait for ACK, then send START.

        Reads directly from the StreamReader (line-by-line) since the board
        only sends JSON control lines during the handshake phase.

        Raises TimeoutError if ACK is not received within the timeout.
        """
        # Explicitly toggle DTR to force a clean board reset via the CH340 EN line.
        #
        # serial_asyncio opens the port with dtr=None (no state change), so on
        # the second and subsequent connects the board is still alive in its run
        # loop — it never sees a reset and never enters run_handshake() again.
        #
        # Driving DTR False then True creates a HIGH→LOW transition on the CH340
        # DTR output pin.  The 100 µF capacitor on the EN line converts this to a
        # brief negative pulse that resets the ESP32.  The 100 ms LOW hold is more
        # than enough; the capacitor RC time constant is only ~10 ms.
        try:
            s = self._writer.transport._serial  # type: ignore[attr-defined]
            s.dtr = False
            await asyncio.sleep(0.1)
            s.dtr = True
            logger.info("Board %d: DTR toggled — board reset triggered", self._board_id)
        except Exception as exc:
            logger.warning(
                "Board %d: DTR toggle failed (%s) — relying on hardware reset state",
                self._board_id, exc,
            )

        # Wait for the full ESP32-S3 boot cycle before sending INIT.
        # On fresh power-on the board is already running by the time the Pi
        # starts, so the delay is just a safety margin.  When DTR is toggled
        # above the board actually resets, and the full ROM→bootloader→firmware
        # boot needs time.  6.5 s gives comfortable margin for that cold-reset
        # path while still fitting well within the 10 s ACK timeout.
        # If INIT is sent but ACK never arrives, increase this value first.
        await asyncio.sleep(6.5)

        # Send INIT with our assigned board ID.
        await self.write(build_init(self._board_id))
        logger.info("Board %d: INIT sent (id=%d)", self._board_id, self._board_id)

        # Wait for ACK — the board echoes our ID back to confirm.
        try:
            async with asyncio.timeout(_HANDSHAKE_TIMEOUT):
                while True:
                    raw = await reader.readline()
                    if not raw:
                        raise ConnectionError(f"Board {self._board_id}: EOF during handshake")
                    msg = parse_control(raw.decode(errors="replace"))
                    if (
                        msg
                        and msg.get("type") == "ack"
                        and msg.get("id") == self._board_id
                    ):
                        logger.info("Board %d: ACK received", self._board_id)
                        break
        except TimeoutError:
            raise TimeoutError(
                f"Board {self._board_id}: no ACK within {_HANDSHAKE_TIMEOUT}s"
            )

        # Send START — board exits its wait loop and begins its task.
        await self.write(build_start())
        logger.info("Board %d: START sent", self._board_id)

    # ======================== Frame Reader ======================== #

    async def _read_frames(self, reader: asyncio.StreamReader) -> None:
        """Parse the incoming byte stream into control and data frames.

        Handles a mixed stream: binary data frames and JSON control lines
        can appear in any order. Uses a leading-byte heuristic to route:
          0xAA → binary frame path
          '{'  → JSON line path
          else → resync (discard one byte and try again)
        """
        buf = bytearray()

        while True:
            chunk = await reader.read(_READ_CHUNK)
            if not chunk:
                logger.info("Board %d: serial EOF", self._board_id)
                return
            buf.extend(chunk)

            while buf:
                # ── Binary frame ──────────────────────────────────────────── #
                if buf[0] == MAGIC_1:
                    # Need at least the full header to determine payload length.
                    if len(buf) < HEADER_SIZE:
                        break

                    # Validate second magic byte.
                    if buf[1] != MAGIC_2:
                        logger.debug("Board %d: bad magic[1]=0x%02x — resync", self._board_id, buf[1])
                        buf.pop(0)
                        continue

                    payload_len = parse_binary_length(buf)
                    total       = HEADER_SIZE + payload_len

                    if len(buf) < total:
                        break  # Wait for the full payload.

                    payload = bytes(buf[HEADER_SIZE:total])
                    del buf[:total]

                    for handler in self._data_handlers:
                        await handler(self._board_id, payload)

                # ── JSON control line ─────────────────────────────────────── #
                elif buf[0] == ord("{"):
                    newline = buf.find(b"\n")
                    if newline == -1:
                        break  # Wait for the newline terminator.

                    line = buf[:newline].decode(errors="replace")
                    del buf[:newline + 1]

                    msg = parse_control(line)
                    if msg:
                        for handler in self._control_handlers:
                            await handler(self._board_id, msg)
                    else:
                        logger.debug("Board %d: malformed control line: %s", self._board_id, line)

                # ── Unknown byte — resync ─────────────────────────────────── #
                else:
                    logger.debug("Board %d: resync — discarding 0x%02x", self._board_id, buf[0])
                    buf.pop(0)
