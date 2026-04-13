"""Project Client Runtime.

Self-contained client that manages its own MQTT connection, heartbeat,
host tracking, database, and ESP32 board management. Instantiated from
config and started with a single `run()` call.
"""

import asyncio
import logging
import time

from base.comms import MQTTClient, TopicManager, HeartbeatLoop, build_envelope
from base.client import HostTracker
from base.host.state import PeerState
from base.esp import ESPRegistry, HandshakeManager, FlashManager
from base.esp.serial import ESPSerial
from app.models.config import ProjectClientConfig
from app.models.messages import ProjectMessageType
from app.client.store import ClientStore
from app.client.esp_manager import ESPManager

logger = logging.getLogger(__name__)


class ClientRuntime:
    """Encapsulates the full client lifecycle.

    Args:
        config: Validated ProjectClientConfig.
    """

    def __init__(self, config: ProjectClientConfig) -> None:
        self._config  = config
        self._start_t = time.time()

        self._topics = TopicManager(config.mqtt.topic_prefix)
        self._mqtt   = MQTTClient(config.mqtt, client_id=f"client-{config.pid}")
        self._store  = ClientStore(config.database)

        self._host_tracker = HostTracker(timeout=15.0, offline_after=30.0)

        self._heartbeat = HeartbeatLoop(
            mqtt=self._mqtt,
            sender=config.pid,
            topic=self._topics.client_status(config.pid),
            interval=5.0,
            payload_fn=self._build_heartbeat,
        )

        # ESP subsystem.
        self._esp_registry = ESPRegistry(timeout=15.0)
        self._esp_handshake = HandshakeManager(
            registry=self._esp_registry,
            config=config.esp,
        )
        self._esp_flash = FlashManager(esp_dir=config.esp.esp_dir)

        # Boards are populated dynamically by the port watcher.
        self._esp_boards:      list[ESPSerial]          = []
        self._esp_board_tasks: dict[int, asyncio.Task]  = {}

        self._esp_manager = ESPManager(
            config=config,
            mqtt=self._mqtt,
            topics=self._topics,
            pid=config.pid,
            registry=self._esp_registry,
        )

    # ======================== Properties ======================== #

    @property
    def pid(self) -> str:
        return self._config.pid

    @property
    def host_state(self) -> PeerState:
        return self._host_tracker.state

    # ======================== Lifecycle ======================== #

    async def run(self) -> None:
        """Start all client subsystems and run until cancelled."""
        # Database.
        await self._store.start()

        # State change callbacks.
        self._host_tracker.on_state_change(self._on_host_state_change)
        self._esp_registry.on_state_change(self._on_esp_state_change)

        # MQTT subscriptions.
        self._mqtt.on(self._topics.host_status(),              self._on_host_heartbeat)
        self._mqtt.on(self._topics.host_command(),             self._on_command)
        self._mqtt.on(self._topics.host_command_to(self.pid),  self._on_command)

        # Connect to broker.
        await self._mqtt.start()
        logger.info("Client %s online — ESP port watcher starting", self.pid)

        # Build the fixed task set. Board tasks are created dynamically via
        # _on_board_discovered as the port watcher finds new devices.
        tasks = [
            asyncio.create_task(self._heartbeat.run(),         name="heartbeat"),
            asyncio.create_task(self._host_tracker.run(),      name="host-tracker"),
            asyncio.create_task(self._esp_registry.run(),      name="esp-registry"),
            asyncio.create_task(self._esp_status_loop(),       name="esp-status"),
            asyncio.create_task(
                self._esp_handshake.watch_loop(self._on_board_discovered),
                name="esp-watcher",
            ),
        ]

        try:
            await asyncio.gather(*tasks)
        finally:
            # Cancel board tasks before tearing down shared resources.
            for task in self._esp_board_tasks.values():
                task.cancel()
            self._heartbeat.stop()
            await self._store.stop()
            await self._mqtt.stop()
            logger.info("Client %s shut down", self.pid)

    # ======================== Board Discovery Callback ======================== #

    async def _on_board_discovered(self, board: ESPSerial) -> None:
        """Called by the port watcher for each newly found ESP board.

        Wires data/control handlers, appends to the board list, and starts
        the board's read_loop as an independent asyncio task.
        """
        board.on_control(self._esp_manager.on_control)
        board.on_data(self._esp_manager.on_data)

        # Reset sequence stats on every (re)connect so frames sent by the
        # firmware while the serial port was closed are not counted as drops.
        # on_running callbacks are awaited before _read_frames starts, so
        # the reset is guaranteed to complete before the first frame arrives.
        async def _on_running(board_id: int) -> None:
            self._esp_manager.reset_board(board_id)

        board.on_running(_on_running)

        self._esp_boards.append(board)

        task = asyncio.create_task(
            board.read_loop(),
            name=f"esp-board-{board.board_id}",
        )
        self._esp_board_tasks[board.board_id] = task

        logger.info(
            "Board %d started (port=%s) — %d board(s) active",
            board.board_id, board.port, len(self._esp_boards),
        )

    # ======================== ESP Periodic Tasks ======================== #

    async def _esp_status_loop(self) -> None:
        """Periodically poll each running board for status and publish
        a summary to the host via MQTT."""
        interval = self._config.esp.heartbeat_interval
        logger.info("ESP status loop started (interval=%.1fs)", interval)

        while True:
            await asyncio.sleep(interval)

            for board in self._esp_boards:
                if board.is_connected:
                    from base.esp.protocol import build_command
                    await board.write(build_command("status"))

            # Publish ESP board summary to host.
            if self._esp_registry.total_count > 0:
                boards_list = [
                    {
                        "board_id":  b.board_id,
                        "port":      b.port,
                        "state":     b.state.value,
                        "last_seen": b.last_seen,
                    }
                    for b in self._esp_registry.boards.values()
                ]
                envelope = build_envelope(
                    sender=self.pid,
                    msg_type=ProjectMessageType.ESP_STATUS,
                    payload={
                        "pid":     self.pid,
                        "boards":  boards_list,
                        "running": self._esp_registry.running_count,
                        "total":   self._esp_registry.total_count,
                    },
                )
                await self._mqtt.publish(self._topics.client_data(self.pid), envelope)

    # ======================== MQTT Handlers ======================== #

    async def _on_host_heartbeat(self, topic: str, payload: dict) -> None:
        """Process a heartbeat from the host."""
        self._host_tracker.heartbeat_received(payload.get("payload", {}))

    async def _on_command(self, topic: str, payload: dict) -> None:
        """Process a command from the host."""
        msg_type = payload.get("msg_type", "unknown")
        data     = payload.get("payload", {})
        logger.info("Command received: %s", msg_type)

        # ── ESP board control ── #

        if msg_type == ProjectMessageType.FLASH_REQUEST:
            ports   = data.get("ports", [])
            targets = ports if ports else [b.port for b in self._esp_boards]
            results = await self._esp_flash.flash_all(targets)
            envelope = build_envelope(
                sender=self.pid,
                msg_type=ProjectMessageType.FLASH_RESULT,
                payload={"pid": self.pid, "results": results},
            )
            await self._mqtt.publish(self._topics.client_data(self.pid), envelope)

        elif msg_type == ProjectMessageType.ESP_COMMAND:
            cmd       = data.get("cmd", "")
            board_ids = data.get("board_ids", [])
            args      = data.get("args", {})
            if not cmd:
                return
            from base.esp.protocol import build_command
            frame   = build_command(cmd, **args)
            targets = (
                [b for b in self._esp_boards if b.board_id in board_ids]
                if board_ids else self._esp_boards
            )
            for board in targets:
                await board.write(frame)

        elif msg_type == ProjectMessageType.ESP_REBOOT:
            # Force a disconnect → reconnect → re-handshake on specific boards.
            board_ids = data.get("board_ids", [])
            targets = (
                [b for b in self._esp_boards if b.board_id in board_ids]
                if board_ids else self._esp_boards
            )
            for board in targets:
                logger.info("Reboot requested for board %d", board.board_id)
                asyncio.create_task(board.restart())

        elif msg_type == "clock_sync_esp":
            # Sync Pi's current time to all running boards.
            ts_ns = time.time_ns()
            from base.esp.protocol import build_command
            frame = build_command("clock_sync", ts=ts_ns)
            for board in self._esp_boards:
                await board.write(frame)

        # ── Standard commands ── #

        elif msg_type == "reboot":
            logger.warning("Reboot command received")
        elif msg_type == "shutdown":
            logger.warning("Shutdown command received")

        # PROJECT-SPECIFIC: Handle your own commands here, e.g.:
        # elif msg_type == "start_scan":
        #     await self._start_scanning(data)

    # ======================== State Callbacks ======================== #

    async def _on_host_state_change(self, old: PeerState, new: PeerState) -> None:
        if new == PeerState.ONLINE:
            logger.info("Host is ONLINE — full communication active")
        elif new == PeerState.STALE:
            logger.warning("Host heartbeat overdue — connection may be degraded")
        elif new == PeerState.OFFLINE:
            logger.error("Host is OFFLINE — operating in standalone mode")

    async def _on_esp_state_change(self, board_id: int, old, new) -> None:
        logger.info("ESP board %d: %s -> %s", board_id, old.value, new.value)

    # ======================== Heartbeat ======================== #

    def _build_heartbeat(self) -> dict:
        """Build the client heartbeat payload."""
        return {
            "pid":         self.pid,
            "uptime":      round(time.time() - self._start_t, 1),
            "host_status": self._host_tracker.state.value,
            "esp_running": self._esp_registry.running_count,
            "esp_total":   self._esp_registry.total_count,
            "esp_boards":  self._esp_registry.summary(),
            # PROJECT-SPECIFIC: Add your status fields here, e.g.:
            # "sensors_active": self._active_sensor_count,
        }
