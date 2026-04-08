"""ESP32 base module.

Provides reusable infrastructure for Pi-to-ESP board communication:
flashing, serial protocol, board state registry, and boot handshake.

Intended to be used by projects that integrate ESP32 boards into the
client-host baseplate. Projects supply the C firmware; this module
provides everything the Pi side needs to manage it.
"""

from base.esp.protocol  import build_init, build_start, build_command, build_data_frame, parse_control
from base.esp.registry  import ESPRegistry, BoardState, BoardStatus
from base.esp.serial    import ESPSerial
from base.esp.handshake import HandshakeManager
from base.esp.flash     import FlashManager

__all__ = [
    "build_init",
    "build_start",
    "build_command",
    "build_data_frame",
    "parse_control",
    "ESPRegistry",
    "BoardState",
    "BoardStatus",
    "ESPSerial",
    "HandshakeManager",
    "FlashManager",
]
