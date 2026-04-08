"""Base message envelope used by all projects.

Every message published over MQTT is wrapped in an Envelope. This gives
a consistent structure for routing, logging, and debugging regardless
of what the actual payload contains.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    """Base message types shared across all projects.

    Projects extend this by defining their own Enum that includes
    these base types plus project-specific ones.
    """
    # Status
    HEARTBEAT   = "heartbeat"
    STATUS      = "status"

    # Control
    COMMAND     = "command"
    RESPONSE    = "response"

    # Data
    DATA        = "data"

    # System
    CLOCK_SYNC  = "clock_sync"
    REBOOT      = "reboot"
    SHUTDOWN    = "shutdown"


class Envelope(BaseModel):
    """Standard message wrapper for all MQTT communication.

    Attributes:
        sender: Identifier of the sender (pid for clients, 'host' for host).
        msg_type: The type/category of this message.
        timestamp: UTC timestamp of when the message was created.
        payload: The actual data — structure depends on msg_type.
    """
    sender: str
    msg_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a dict suitable for JSON / MQTT publish."""
        return {
            "sender": self.sender,
            "msg_type": self.msg_type,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Envelope":
        """Reconstruct an Envelope from a received dict."""
        return cls(**data)


def build_envelope(
    sender: str,
    msg_type: str | MessageType,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience function to create and serialise an Envelope in one step."""
    if isinstance(msg_type, MessageType):
        msg_type = msg_type.value
    return Envelope(
        sender=sender,
        msg_type=msg_type,
        payload=payload or {},
    ).to_dict()
