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
    build_init, build_start, build_stop,
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

    # ======================== Write / Restart ======================== #

    async def restart(self) -> None:
        """Force a disconnect → reconnect → re-handshake cycle for this board.

        Sends a STOP frame to the firmware so it turns its LED off immediately,
        then closes the serial writer. The active _read_frames loop sees EOF
        and returns. The outer read_loop fires disconnect callbacks, sleeps for
        reconnect_interval, re-opens the port, and re-runs _run_handshake —
        sending a fresh INIT to the firmware.

        The firmware handles the re-INIT in handle_command(): it pauses
        data_task, ACKs, waits for START, then resumes and re-enables the LED.
        """
        if self._writer:
            try:
                self._writer.write(build_stop())
                await self._writer.drain()
            except Exception:
                pass
            try:
                self._writer.close()
            except Exception:
                pass

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
        # Await callbacks synchronously so any state reset (e.g. sequence
        # counter) is guaranteed to complete before the first data frame
        # arrives from _read_frames.
        logger.info("Board %d: handshake complete — RUNNING", self._board_id)
        for cb in self._on_running:
            await cb(self._board_id)

        # Enter the continuous frame read loop.
        await self._read_frames(reader)

    async def _run_handshake(self, reader: asyncio.StreamReader) -> None:
        """Send INIT, wait for ACK, then send START.

        Uses a mixed-stream scanner (same approach as _read_frames) so that
        binary data frames from a still-running data_task don't bury the ACK
        JSON line.  Non-'{' bytes are silently discarded; only complete JSON
        lines are parsed.

        Raises TimeoutError if ACK is not received within the timeout.
        """
        # Opening the serial port asserts DTR which resets the ESP32 via the
        # CH340's EN line.  Wait for the full boot cycle to complete before
        # sending INIT, otherwise the message is consumed by the ROM
        # bootloader and the board never sees it.
        #
        # 3.5 s was measured on ESP32-S3-WROOM-1U with a CH340 bridge at
        # 921600 baud.  If INIT is sent but ACK never arrives, increase this
        # value first — the ROM bootloader takes longer on debug/slow builds.
        await asyncio.sleep(3.5)

        # Send INIT with our assigned board ID.
        await self.write(build_init(self._board_id))
        logger.info("Board %d: INIT sent (id=%d)", self._board_id, self._board_id)

        # Wait for ACK — the board echoes our ID back to confirm.
        #
        # The board may be mid-run (data_task sending binary frames) when INIT
        # arrives.  Those frames accumulate in the read buffer and would cause
        # readline() to return a blob of binary garbage concatenated with the
        # ACK JSON, making json.loads() fail.  Instead, scan the incoming bytes
        # directly: discard anything that isn't '{', then capture the complete
        # JSON line and check it for the expected ACK.
        #
        # We re-send INIT every 2 s if no ACK arrives.  This handles the race
        # where the firmware is in the handle_command() wait-for-START inner
        # loop when our INIT arrives: the inner loop re-ACKs on a second INIT,
        # so retrying here ensures we always break the deadlock.
        buf          = bytearray()
        ack_received = False
        deadline     = asyncio.get_event_loop().time() + _HANDSHAKE_TIMEOUT
        _RETRY_INTERVAL = 2.0

        while not ack_received:
            now = asyncio.get_event_loop().time()
            if now >= deadline:
                raise TimeoutError(
                    f"Board {self._board_id}: no ACK within {_HANDSHAKE_TIMEOUT}s"
                )

            read_timeout = min(_RETRY_INTERVAL, deadline - now)
            try:
                chunk = await asyncio.wait_for(reader.read(_READ_CHUNK), timeout=read_timeout)
            except asyncio.TimeoutError:
                # No data for 2 s — re-send INIT and keep waiting.
                if asyncio.get_event_loop().time() < deadline:
                    logger.info("Board %d: no ACK yet, retrying INIT", self._board_id)
                    await self.write(build_init(self._board_id))
                continue

            if not chunk:
                raise ConnectionError(f"Board {self._board_id}: EOF during handshake")
            buf.extend(chunk)

            while buf:
                if buf[0] != ord("{"):
                    del buf[:1]   # discard binary frame byte
                    continue

                newline = buf.find(b"\n")
                if newline == -1:
                    break         # incomplete line — need more bytes

                line = buf[:newline].decode(errors="replace")
                del buf[:newline + 1]

                msg = parse_control(line)
                if (
                    msg
                    and msg.get("type") == "ack"
                    and msg.get("id") == self._board_id
                ):
                    logger.info("Board %d: ACK received", self._board_id)
                    ack_received = True
                    break

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
