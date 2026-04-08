"""Async MQTT client wrapper with auto-reconnect.

Built on paho-mqtt v2. Provides a clean interface for publish/subscribe
with automatic reconnection handling. Designed to be reusable across
all projects that use the base framework.
"""

import asyncio
import json
import logging
from typing import Any, Callable, Awaitable

import paho.mqtt.client as paho

from base.config import MQTTConfig

logger = logging.getLogger(__name__)

# Type alias for message handler callbacks.
MessageHandler = Callable[[str, dict[str, Any]], Awaitable[None]]


class MQTTClient:
    """Async MQTT client with auto-reconnect and structured message handling.

    Args:
        config: MQTTConfig with broker host, port, keepalive, etc.
        client_id: Unique identifier for this MQTT client instance.
    """

    def __init__(self, config: MQTTConfig, client_id: str) -> None:
        self._config = config
        self._client_id = client_id
        self._connected = asyncio.Event()
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

        # Build the paho client.
        self._client = paho.Client(
            callback_api_version=paho.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(
            min_delay=max(1, int(self._config.reconnect_interval)),
            max_delay=max(30, int(self._config.reconnect_interval * 10)),
        )

    # ======================== Properties ======================== #

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    @property
    def client_id(self) -> str:
        return self._client_id

    # ======================== Lifecycle ======================== #

    async def start(self) -> None:
        """Connect to the broker and begin the network loop."""
        self._loop = asyncio.get_running_loop()
        logger.info(
            "MQTT connecting to %s:%s as '%s'",
            self._config.host,
            self._config.port,
            self._client_id,
        )
        self._client.connect_async(
            self._config.host,
            self._config.port,
            self._config.keepalive,
        )
        self._client.loop_start()
        await self._connected.wait()

    async def stop(self) -> None:
        """Disconnect cleanly and stop the network loop."""
        logger.info("MQTT disconnecting '%s'", self._client_id)
        self._client.disconnect()
        self._client.loop_stop()
        self._connected.clear()

    # ======================== Publish ======================== #

    async def publish(self, topic: str, payload: dict[str, Any], qos: int = 1) -> None:
        """Publish a JSON-encoded payload to a topic.

        Args:
            topic: Full MQTT topic string.
            payload: Dictionary that will be JSON-serialised.
            qos: MQTT quality of service (0, 1, or 2).
        """
        if not self.is_connected:
            logger.warning("Publish attempted while disconnected — dropping message")
            return

        raw = json.dumps(payload)
        self._client.publish(topic, raw, qos=qos)
        logger.debug("PUB  %s  (%d bytes)", topic, len(raw))

    # ======================== Subscribe ======================== #

    def on(self, topic: str, handler: MessageHandler) -> None:
        """Register an async handler for a topic pattern.

        Args:
            topic: MQTT topic (supports + and # wildcards).
            handler: Async callable(topic, payload_dict).
        """
        if topic not in self._handlers:
            self._handlers[topic] = []
            if self.is_connected:
                self._client.subscribe(topic, qos=1)
        self._handlers[topic].append(handler)

    # ======================== Paho Callbacks ======================== #

    def _on_connect(
        self,
        client: paho.Client,
        userdata: Any,
        flags: Any,
        rc: Any,
        properties: Any = None,
    ) -> None:
        if hasattr(rc, "value"):
            code = rc.value
        else:
            code = int(rc)

        if code == 0:
            logger.info("MQTT connected to %s:%s", self._config.host, self._config.port)
            # Re-subscribe to all registered topics on (re)connect.
            for topic in self._handlers:
                client.subscribe(topic, qos=1)
            if self._loop:
                self._loop.call_soon_threadsafe(self._connected.set)
        else:
            logger.error("MQTT connection failed (rc=%s)", rc)

    def _on_disconnect(
        self,
        client: paho.Client,
        userdata: Any,
        flags: Any = None,
        rc: Any = None,
        properties: Any = None,
    ) -> None:
        logger.warning("MQTT disconnected (rc=%s) — will auto-reconnect", rc)
        if self._loop:
            self._loop.call_soon_threadsafe(self._connected.clear)

    def _on_message(
        self,
        client: paho.Client,
        userdata: Any,
        msg: paho.MQTTMessage,
    ) -> None:
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Bad payload on %s — skipping", msg.topic)
            return

        logger.debug("SUB  %s  (%d bytes)", msg.topic, len(msg.payload))

        # Dispatch to matching handlers.
        for pattern, handlers in self._handlers.items():
            if self._topic_matches(pattern, msg.topic):
                for handler in handlers:
                    if self._loop:
                        asyncio.run_coroutine_threadsafe(
                            handler(msg.topic, payload), self._loop
                        )

    # ======================== Helpers ======================== #

    @staticmethod
    def _topic_matches(pattern: str, topic: str) -> bool:
        """Check if a topic matches an MQTT wildcard pattern."""
        pat_parts = pattern.split("/")
        top_parts = topic.split("/")

        for i, pat in enumerate(pat_parts):
            if pat == "#":
                return True
            if i >= len(top_parts):
                return False
            if pat != "+" and pat != top_parts[i]:
                return False

        return len(pat_parts) == len(top_parts)
