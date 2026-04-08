"""Reusable heartbeat publisher.

Runs as an asyncio task, periodically publishing a heartbeat envelope
to a given topic. The payload is built dynamically via a callback so
the data is always fresh (e.g. current CPU temp, packet counts, etc.).
"""

import asyncio
import logging
from typing import Any, Callable

from base.comms.mqtt import MQTTClient
from base.comms.messages import build_envelope, MessageType

logger = logging.getLogger(__name__)

# Callback that returns the current heartbeat payload dict.
PayloadBuilder = Callable[[], dict[str, Any]]


class HeartbeatLoop:
    """Publishes heartbeat messages at a fixed interval.

    Args:
        mqtt: The MQTT client to publish through.
        sender: Sender ID to stamp on each envelope (pid or 'host').
        topic: The MQTT topic to publish heartbeats to.
        interval: Seconds between heartbeats.
        payload_fn: Callable that returns the current payload dict.
    """

    def __init__(
        self,
        mqtt: MQTTClient,
        sender: str,
        topic: str,
        interval: float = 5.0,
        payload_fn: PayloadBuilder | None = None,
    ) -> None:
        self._mqtt = mqtt
        self._sender = sender
        self._topic = topic
        self._interval = interval
        self._payload_fn = payload_fn or (lambda: {})
        self._running = False
        self._beat_count = 0

    # ======================== Properties ======================== #

    @property
    def beat_count(self) -> int:
        return self._beat_count

    @property
    def is_running(self) -> bool:
        return self._running

    # ======================== Lifecycle ======================== #

    async def run(self) -> None:
        """Run the heartbeat loop. Call as an asyncio task."""
        self._running = True
        logger.info(
            "Heartbeat started: sender=%s topic=%s interval=%.1fs",
            self._sender, self._topic, self._interval,
        )

        try:
            while self._running:
                payload = self._payload_fn()
                envelope = build_envelope(
                    sender=self._sender,
                    msg_type=MessageType.HEARTBEAT,
                    payload=payload,
                )
                await self._mqtt.publish(self._topic, envelope)
                self._beat_count += 1
                await asyncio.sleep(self._interval)
        finally:
            self._running = False
            logger.info("Heartbeat stopped: sender=%s", self._sender)

    def stop(self) -> None:
        """Signal the heartbeat loop to stop."""
        self._running = False
