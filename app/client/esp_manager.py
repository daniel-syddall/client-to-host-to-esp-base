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
import time
from typing import Any

from base.comms import MQTTClient, TopicManager, build_envelope
from base.esp import ESPRegistry
from app.models.config import ProjectClientConfig
from app.models.messages import ProjectMessageType

logger = logging.getLogger(__name__)

# Sequence gap larger than this (frames) is treated as the board having kept
# running while the client was stopped, rather than actual dropped frames.
# 100 frames = 10 seconds at 10 Hz — comfortably covers a normal restart.
_RECONNECT_GAP = 100


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
        # Per-board data validation state (populated lazily on first frame).
        self._board_stats: dict[int, dict] = {}

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
        # PROJECT-SPECIFIC: Replace this block with real payload parsing.
        #
        # Example — Nanosecond-timestamp record:
        #   if len(payload) >= 12:
        #       ts_ns    = int.from_bytes(payload[0:8],  "little")  # uint64
        #       channel  = int.from_bytes(payload[8:10], "little")  # uint16
        #       rssi     = int.from_bytes(payload[10:12],"little")  # int16 signed
        #       record = {"board_id": board_id, "ts_ns": ts_ns, "ch": channel, "rssi": rssi}
        #       await self._forward_data(record)

        now   = time.monotonic()
        stats = self._board_stats.setdefault(board_id, {
            "last_seq":      None,
            "frames":        0,
            "drops":         0,
            "session_start": now,
        })

        # ── Payload format check ──────────────────────────────────────────── #
        # Baseplate test firmware sends exactly 4 bytes (big-endian uint32 seq).
        # A different size means the wrong firmware is flashed.
        if len(payload) != 4:
            logger.warning(
                "Board %d: unexpected payload size %d B (expected 4 B) "
                "— check that the correct firmware is flashed",
                board_id, len(payload),
            )
            return

        seq = int.from_bytes(payload[:4], "big")
        stats["frames"] += 1

        # ── Continuity check ──────────────────────────────────────────────── #
        last = stats["last_seq"]
        if last is not None:
            gap = seq - last - 1

            if gap > _RECONNECT_GAP:
                # The firmware kept running while the client was stopped.
                logger.info(
                    "Board %d: seq resumed at %d after reconnect "
                    "(%d frames counted while client was down)",
                    board_id, seq, gap,
                )
                stats["frames"]        = 1
                stats["drops"]         = 0
                stats["session_start"] = now
                await self._forward_data({
                    "board_id": board_id,
                    "event":    "reconnect",
                    "seq":      seq,
                    "gap":      gap,
                    "ts":       time.time(),
                })

            elif gap > 0:
                # Small positive gap — genuine frame drops on the link.
                stats["drops"] += gap
                logger.warning(
                    "Board %d: %d frame(s) dropped (seq %d → %d)",
                    board_id, gap, last, seq,
                )
                await self._forward_data({
                    "board_id": board_id,
                    "event":    "drop",
                    "seq":      seq,
                    "gap":      gap,
                    "ts":       time.time(),
                })

            elif gap < 0:
                # Seq went backwards — firmware rebooted (power cycle or reset).
                logger.info(
                    "Board %d: seq reset %d → %d — firmware rebooted",
                    board_id, last, seq,
                )
                stats["frames"]        = 1
                stats["drops"]         = 0
                stats["session_start"] = now
                await self._forward_data({
                    "board_id":   board_id,
                    "event":      "reboot",
                    "seq":        seq,
                    "last_seq":   last,
                    "ts":         time.time(),
                })

        stats["last_seq"] = seq
        logger.debug("Board %d seq=%d", board_id, seq)

        # ── Periodic health report (every 100 frames ≈ 10 s) ─────────────── #
        if seq % 100 == 0:
            elapsed  = now - stats["session_start"]
            rate     = stats["frames"] / elapsed if elapsed > 0 else 0.0
            total    = stats["frames"] + stats["drops"]
            drop_pct = 100.0 * stats["drops"] / total if total > 0 else 0.0
            logger.info(
                "Board %d | seq=%-6d  rate=%4.1f Hz  "
                "frames=%d  drops=%d (%.1f%%)",
                board_id, seq, rate, stats["frames"], stats["drops"], drop_pct,
            )
            await self._forward_data({
                "board_id": board_id,
                "event":    "health",
                "seq":      seq,
                "frames":   stats["frames"],
                "drops":    stats["drops"],
                "rate":     round(rate, 2),
                "drop_pct": round(drop_pct, 1),
                "ts":       time.time(),
            })

    # ======================== Reconnect ======================== #

    def reset_board(self, board_id: int) -> None:
        """Reset per-board sequence tracking after a reconnect.

        Called synchronously before the first data frame arrives so the gap
        caused by frames the firmware sent while the serial port was closed
        is not reported as dropped frames.
        Only acts if the board has existing stats — i.e. this is a reconnect,
        not an initial connect.
        """
        if board_id not in self._board_stats:
            return
        self._board_stats[board_id].update({
            "last_seq":      None,
            "frames":        0,
            "drops":         0,
            "session_start": time.monotonic(),
        })
        logger.info("Board %d: stats reset after reconnect", board_id)

    # ======================== Helpers ======================== #

    async def _forward_data(self, data: dict[str, Any]) -> None:
        """Forward a processed data record to the host via MQTT."""
        envelope = build_envelope(
            sender=self._pid,
            msg_type=ProjectMessageType.ESP_DATA,
            payload=data,
        )
        await self._mqtt.publish(self._topics.client_data(self._pid), envelope)
