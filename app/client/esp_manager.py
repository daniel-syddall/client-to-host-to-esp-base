"""Project-specific ESP board data handler.

This is the primary extension point for ESP data processing.
Register this manager's handlers on each ESPSerial board instance:

    board.on_control(self._esp_manager.on_control)
    board.on_data(self._esp_manager.on_data)

The manager receives parsed frames from the serial layer and decides
what to do with them — parse the binary payload, correlate records
across boards, forward to the host, store locally, etc.

This file is project-specific. The baseplate does not dictate
the binary data format or what processing is applied.
"""

import logging
from typing import Any

from base.comms import MQTTClient, TopicManager, build_envelope
from base.esp import ESPRegistry
from app.models.config import ProjectClientConfig
from app.models.messages import ProjectMessageType

logger = logging.getLogger(__name__)


class ESPManager:
    """Handles incoming frames from ESP boards and outgoing data to the host.

    Args:
        config: Full client config (access esp, mqtt, etc.)
        mqtt:   Active MQTT client for forwarding data to the host.
        topics: TopicManager for building MQTT topic strings.
        pid:    This client's PID, stamped on forwarded messages.
    """

    def __init__(
        self,
        config:    ProjectClientConfig,
        mqtt:      MQTTClient,
        topics:    TopicManager,
        pid:       str,
        registry:  ESPRegistry | None = None,
    ) -> None:
        self._config    = config
        self._mqtt      = mqtt
        self._topics    = topics
        self._pid       = pid
        self._registry  = registry

    # ======================== Control Frame Handler ======================== #

    async def on_control(self, board_id: int, msg: dict[str, Any]) -> None:
        """Handle an incoming JSON control frame from a board.

        Called for every non-handshake control message the board sends
        (status reports, acks for commands, etc.).

        Args:
            board_id: Session ID of the board that sent the frame.
            msg:      Parsed JSON dict.
        """
        msg_type = msg.get("type", "unknown")

        if msg_type == "status":
            # Board is responding to a status poll.
            logger.info(
                "ESP board %d status: running=%s",
                board_id, msg.get("running"),
            )
            if self._registry:
                self._registry.heartbeat_received(board_id, msg)

        # PROJECT-SPECIFIC: Add your own control message types here, e.g.:
        #
        # elif msg_type == "alert":
        #     logger.warning("Board %d alert: %s", board_id, msg)
        #     await self._forward_alert(board_id, msg)

    # ======================== Data Frame Handler ======================== #

    async def on_data(self, board_id: int, payload: bytes) -> None:
        """Handle an incoming binary data frame from a board.

        The payload format is project-defined. Parse it here according to
        the binary layout you defined in esp/main.c's send_data_frame() calls.

        Args:
            board_id: Session ID of the board that sent the frame.
            payload:  Raw binary payload bytes (everything after the frame header).
        """
        # PROJECT-SPECIFIC: Parse your binary payload and process it.
        #
        # Example — 4-byte big-endian sequence number:
        #   if len(payload) >= 4:
        #       seq = int.from_bytes(payload[:4], "big")
        #       logger.debug("Board %d seq=%d", board_id, seq)
        #
        # Example — Nanosecond-timestamp record:
        #   if len(payload) >= 12:
        #       ts_ns    = int.from_bytes(payload[0:8],  "little")  # uint64
        #       channel  = int.from_bytes(payload[8:10], "little")  # uint16
        #       rssi     = int.from_bytes(payload[10:12],"little")  # int16 signed
        #       record = {"board_id": board_id, "ts_ns": ts_ns, "ch": channel, "rssi": rssi}
        #       await self._forward_data(record)
        #
        # Example — Correlation across boards:
        #   await self._correlate(board_id, payload)

        logger.debug("Board %d data frame: %d bytes", board_id, len(payload))

        # PROJECT-SPECIFIC: Replace the line above with real handling.

    # ======================== Helpers ======================== #

    async def _forward_data(self, data: dict[str, Any]) -> None:
        """Forward a processed data record to the host via MQTT."""
        envelope = build_envelope(
            sender=self._pid,
            msg_type=ProjectMessageType.ESP_DATA,
            payload=data,
        )
        await self._mqtt.publish(self._topics.client_data(self._pid), envelope)
