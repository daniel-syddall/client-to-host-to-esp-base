"""Pi <-> ESP serial communication protocol.

Two-tier protocol matching what the ESP firmware implements:

  Control channel — JSON lines (newline-terminated).
    Used for: handshake, commands, acks, status.
    Low frequency, human-readable.

  Data channel — Binary frames.
    Used for: streamed data payloads from ESP to Pi.
    High throughput, compact. Carries 64-bit nanosecond timestamps natively.

Binary frame layout:
    [0xAA] [0x55] [length: uint16 little-endian] [payload bytes ...]
    ───────────── header (4 bytes) ──────────────

The payload format inside a data frame is project-specific. The baseplate
does not interpret it — raw bytes are handed to the project's data handler.
"""

import json
import struct
from typing import Any


# ======================== Constants ======================== #

MAGIC_1     = 0xAA
MAGIC_2     = 0x55
HEADER_SIZE = 4          # 2 magic bytes + 2 length bytes


# ======================== Control Frames (JSON) ======================== #

def build_init(board_id: int) -> bytes:
    """Build the INIT handshake frame sent to a board."""
    return (json.dumps({"type": "init", "id": board_id}) + "\n").encode()


def build_start() -> bytes:
    """Build the START frame — board begins its task on receipt."""
    return (json.dumps({"type": "start"}) + "\n").encode()


def build_stop() -> bytes:
    """Build the STOP frame — board turns off its LED and pauses its task.

    Send this before closing the serial connection so the firmware reacts
    immediately rather than waiting for the watchdog timeout.
    """
    return (json.dumps({"type": "stop"}) + "\n").encode()


def build_command(cmd: str, **kwargs: Any) -> bytes:
    """Build a generic JSON command frame.

    Args:
        cmd: Command name (e.g. 'clock_sync', 'stop', 'status').
        **kwargs: Additional key-value pairs merged into the frame.
    """
    payload: dict[str, Any] = {"type": "cmd", "cmd": cmd}
    payload.update(kwargs)
    return (json.dumps(payload) + "\n").encode()


def parse_control(line: str) -> dict[str, Any] | None:
    """Parse a received JSON control line.

    Returns None if the line is not valid JSON.
    """
    try:
        return json.loads(line.strip())
    except (json.JSONDecodeError, ValueError):
        return None


# ======================== Data Frames (Binary) ======================== #

def build_data_frame(payload: bytes) -> bytes:
    """Wrap raw bytes in a binary data frame for sending to the ESP.

    Args:
        payload: Raw bytes. Format is project-defined.
    """
    header = struct.pack("<BBH", MAGIC_1, MAGIC_2, len(payload))
    return header + payload


def is_binary_header(buf: bytes | bytearray) -> bool:
    """Return True if the buffer starts with the binary frame magic bytes."""
    return len(buf) >= 2 and buf[0] == MAGIC_1 and buf[1] == MAGIC_2


def parse_binary_length(header: bytes | bytearray) -> int | None:
    """Extract the payload length from a 4-byte binary frame header.

    Returns None if the header is too short.
    """
    if len(header) < HEADER_SIZE:
        return None
    _, _, length = struct.unpack("<BBH", bytes(header[:HEADER_SIZE]))
    return length
