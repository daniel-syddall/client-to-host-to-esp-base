"""Project-specific message types and payload models.

Define the data structures your project sends over MQTT.
These extend the base Envelope system with your own payload shapes.
"""

from enum import Enum
from pydantic import BaseModel


# ======================== Project Message Types ======================== #

class ProjectMessageType(str, Enum):
    """Message types for this project.

    Includes all base types plus ESP board management types.
    Add further project-specific types in the section below.
    """

    # ── Base types (mirrored from base.comms.MessageType) ── #
    HEARTBEAT  = "heartbeat"
    STATUS     = "status"
    COMMAND    = "command"
    RESPONSE   = "response"
    DATA       = "data"
    CLOCK_SYNC = "clock_sync"
    REBOOT     = "shutdown"
    SHUTDOWN   = "reboot"

    # ── ESP board management ── #
    ESP_STATUS    = "esp_status"     # Pi → Host: summary of connected board states.
    ESP_DATA      = "esp_data"       # Pi → Host: processed data forwarded from a board.
    FLASH_REQUEST = "flash_request"  # Host → Pi: trigger firmware flash on boards.
    FLASH_RESULT  = "flash_result"   # Pi → Host: per-board flash outcome.
    ESP_COMMAND   = "esp_command"    # Host → Pi: relay a command to specific board(s).
    ESP_REBOOT    = "esp_reboot"     # Host → Pi: force reconnect/re-handshake on board(s).

    # ── PROJECT-SPECIFIC: Add your message types here, e.g.: ── #
    # SENSOR_DATA = "sensor_data"
    # ALERT       = "alert"


# ======================== ESP Status Payloads ======================== #

class ESPBoardStatus(BaseModel):
    """Live status snapshot for one ESP board, reported by the Pi."""
    board_id:  int
    port:      str
    state:     str   # BoardState value string
    last_seen: float = 0.0


class ESPStatusPayload(BaseModel):
    """Payload for ESP_STATUS messages (Pi → Host).

    Included in the Pi's heartbeat so the host always has a current
    picture of board health without a separate request.
    """
    pid:     str
    boards:  list[ESPBoardStatus] = []
    running: int = 0
    total:   int = 0


# ======================== Flash Payloads ======================== #

class FlashRequestPayload(BaseModel):
    """Payload for FLASH_REQUEST (Host → Pi).

    If ports is empty, the Pi flashes all connected boards.
    """
    ports: list[str] = []   # e.g. ['/dev/esp_port_0'] — empty = all


class FlashResultPayload(BaseModel):
    """Payload for FLASH_RESULT (Pi → Host)."""
    pid:     str
    results: dict[str, bool]  # {port: success}


# ======================== ESP Command Payload ======================== #

class ESPCommandPayload(BaseModel):
    """Payload for ESP_COMMAND (Host → Pi).

    The Pi relays cmd to the specified board(s) over serial.
    If board_ids is empty, the command is sent to all running boards.
    """
    cmd:       str
    board_ids: list[int]       = []
    args:      dict            = {}


# ======================== Client / Host Status Payloads ======================== #

class ClientStatus(BaseModel):
    """Heartbeat payload from a client. Includes ESP board summary."""
    pid:          str
    uptime:       float = 0.0
    esp_running:  int   = 0
    esp_total:    int   = 0
    esp_boards:   dict  = {}   # {board_id_str: state_str}


class HostStatus(BaseModel):
    """Heartbeat payload from the host."""
    clients_connected: int   = 0
    clients_expected:  int   = 0
    uptime:            float = 0.0


# ======================== PROJECT-SPECIFIC Data Payloads ======================== #

# Define your data models here, e.g.:
#
# class SensorReading(BaseModel):
#     board_id:  int
#     value:     float
#     unit:      str = ""
#     timestamp: int = 0    # nanoseconds (from ESP CCOUNT timer)
