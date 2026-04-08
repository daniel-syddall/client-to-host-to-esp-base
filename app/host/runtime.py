"""Project Host Runtime.

Self-contained host that manages MQTT, client registry, database,
API server, remote SSH management, clock sync, and health checks.
Instantiated from config and started with a single `run()` call.
"""

import asyncio
import logging
from pathlib import Path

from base.comms import MQTTClient, TopicManager, HeartbeatLoop, build_envelope
from base.host import PeerRegistry, PeerState
from base.api import APIServer, base_router, init_base_routes
from base.config import save_config
from base.config.models import ClientEntry, SSHCredentials
from base.service.remote import RemoteClient
from app.models.config import ProjectHostConfig
from app.host.store import HostStore
from app.api.routes import router as project_router, init_project_routes

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent.parent.parent / "base" / "api" / "static"


class HostRuntime:
    """Encapsulates the full host lifecycle.

    Args:
        config: Validated ProjectHostConfig.
    """

    def __init__(self, config: ProjectHostConfig, config_path: Path | None = None) -> None:
        self._config = config
        self._config_path = config_path
        self._topics = TopicManager(config.mqtt.topic_prefix)
        self._mqtt = MQTTClient(config.mqtt, client_id="host")
        self._store = HostStore(config.database, config.storage)

        # Client registry.
        expected_pids = [c.pid for c in config.clients]
        self._registry = PeerRegistry(
            expected_pids=expected_pids,
            timeout=15.0,
            offline_after=30.0,
        )

        # Remote SSH clients.
        self._remotes: dict[str, RemoteClient] = {
            c.pid: RemoteClient(c.ssh) for c in config.clients
        }

        # Heartbeat.
        self._heartbeat = HeartbeatLoop(
            mqtt=self._mqtt,
            sender="host",
            topic=self._topics.host_status(),
            interval=5.0,
            payload_fn=self._build_heartbeat,
        )

        # API server.
        self._api = APIServer(config.api, title="Project API")

    # ======================== Properties ======================== #

    @property
    def registry(self) -> PeerRegistry:
        return self._registry

    @property
    def store(self) -> HostStore:
        return self._store

    # ======================== Lifecycle ======================== #

    async def run(self) -> None:
        """Start all host subsystems and run until cancelled."""
        # Database.
        await self._store.start()

        # Registry callbacks.
        self._registry.on_state_change(self._on_client_state_change)

        # MQTT subscriptions.
        self._mqtt.on(self._topics.all_client_status(), self._on_client_status)
        self._mqtt.on(self._topics.all_client_data(), self._on_client_data)
        self._mqtt.on(self._topics.all_client_responses(), self._on_client_response)

        # API setup.
        if self._api.enabled:
            self._setup_api()

        # Connect.
        await self._mqtt.start()
        logger.info(
            "Host online — expecting %d client(s): %s",
            self._registry.expected_count,
            list(self._registry.peers.keys()),
        )

        # Build task list.
        tasks = [
            self._heartbeat.run(),
            self._registry.run(),
        ]
        if self._store.db.is_connected:
            tasks.append(self._maintenance_loop())
        if self._api.enabled:
            tasks.append(self._api.start())
        if self._config.sync.clock_sync_interval > 0:
            tasks.append(self._clock_sync_loop())
        if self._config.sync.pi_check_interval > 0:
            tasks.append(self._pi_check_loop())

        try:
            await asyncio.gather(*tasks)
        finally:
            self._heartbeat.stop()
            await self._api.stop()
            await self._store.stop()
            await self._mqtt.stop()
            logger.info("Host shut down")

    # ======================== API Setup ======================== #

    def _setup_api(self) -> None:
        """Configure and mount all API routes."""
        # Base routes.
        init_base_routes(
            registry_fn=self._registry.summary,
            extras_fn=lambda: {},
        )
        self._api.app.include_router(base_router)

        # Project routes.
        init_project_routes(self._store, self._registry, self._mqtt, self._topics)
        self._api.app.include_router(project_router)

        # Remote management endpoints.
        self._add_remote_routes()

        # Client config CRUD endpoints.
        self._add_config_routes()

        # Dashboard.
        from fastapi.responses import FileResponse

        @self._api.app.get("/")
        async def dashboard():
            return FileResponse(str(STATIC_DIR / "index.html"))

        self._api.mount_static(STATIC_DIR)

    def _add_remote_routes(self) -> None:
        """Add SSH remote management API endpoints."""
        from fastapi import APIRouter, HTTPException
        from pydantic import BaseModel as _BaseModel
        remote_router = APIRouter(prefix="/api/remote", tags=["remote"])

        class AutobootRequest(_BaseModel):
            enabled: bool

        @remote_router.post("/reboot/{pid}")
        async def reboot_client(pid: str):
            rc = self._remotes.get(pid)
            if not rc:
                raise HTTPException(404, f"Client {pid} not found")
            success = await rc.reboot()
            return {"pid": pid, "action": "reboot", "success": success}

        @remote_router.post("/shutdown/{pid}")
        async def shutdown_client(pid: str):
            rc = self._remotes.get(pid)
            if not rc:
                raise HTTPException(404, f"Client {pid} not found")
            success = await rc.shutdown()
            return {"pid": pid, "action": "shutdown", "success": success}

        @remote_router.post("/sync-clock/{pid}")
        async def sync_clock_client(pid: str):
            rc = self._remotes.get(pid)
            if not rc:
                raise HTTPException(404, f"Client {pid} not found")
            success = await rc.sync_clock()
            return {"pid": pid, "action": "sync_clock", "success": success}

        @remote_router.get("/info/{pid}")
        async def client_info(pid: str):
            rc = self._remotes.get(pid)
            if not rc:
                raise HTTPException(404, f"Client {pid} not found")
            return await rc.get_system_info()

        @remote_router.post("/service-restart/{pid}/{service_name}")
        async def restart_service(pid: str, service_name: str):
            rc = self._remotes.get(pid)
            if not rc:
                raise HTTPException(404, f"Client {pid} not found")
            success = await rc.service_restart(service_name)
            return {"pid": pid, "service": service_name, "restarted": success}

        @remote_router.get("/autoboot/{pid}")
        async def get_autoboot(pid: str):
            rc = self._remotes.get(pid)
            if not rc:
                raise HTTPException(404, f"Client {pid} not found")
            client_cfg = next((c for c in self._config.clients if c.pid == pid), None)
            if not client_cfg or not client_cfg.container_name:
                raise HTTPException(400, f"No container_name configured for {pid}")
            enabled = await rc.get_autoboot(client_cfg.container_name)
            return {"pid": pid, "autoboot": enabled}

        @remote_router.post("/autoboot/{pid}")
        async def set_autoboot(pid: str, req: AutobootRequest):
            rc = self._remotes.get(pid)
            if not rc:
                raise HTTPException(404, f"Client {pid} not found")
            client_cfg = next((c for c in self._config.clients if c.pid == pid), None)
            if not client_cfg or not client_cfg.container_name:
                raise HTTPException(400, f"No container_name configured for {pid}")
            success = await rc.set_autoboot(client_cfg.container_name, req.enabled)
            return {"pid": pid, "autoboot": req.enabled, "success": success}

        self._api.app.include_router(remote_router)

    def _save_config(self) -> None:
        """Persist current in-memory config back to disk."""
        if not self._config_path:
            logger.warning("No config path set — client changes not persisted to disk")
            return
        save_config(self._config_path, self._config)
        logger.info("Config saved to %s", self._config_path)

    def _add_config_routes(self) -> None:
        """Add client CRUD endpoints for runtime configuration."""
        from fastapi import APIRouter, HTTPException
        from pydantic import BaseModel as _BM
        config_router = APIRouter(prefix="/api/config", tags=["config"])

        class SSHInput(_BM):
            ip: str
            user: str
            password: str

        class ClientInput(_BM):
            pid: str
            ssh: SSHInput

        def _derive(pid: str) -> tuple[str, str]:
            topic = f"{self._config.mqtt.topic_prefix}/client/{pid}"
            container = f"{self._config.project_name}-{pid}" if self._config.project_name else ""
            return topic, container

        @config_router.get("/clients")
        async def list_clients():
            return [c.model_dump() for c in self._config.clients]

        @config_router.post("/clients", status_code=201)
        async def add_client(req: ClientInput):
            if any(c.pid == req.pid for c in self._config.clients):
                raise HTTPException(409, f"Client '{req.pid}' already exists")
            topic, container = _derive(req.pid)
            entry = ClientEntry(
                pid=req.pid,
                mqtt_topic=topic,
                container_name=container,
                ssh=SSHCredentials(**req.ssh.model_dump()),
            )
            self._config.clients.append(entry)
            self._remotes[req.pid] = RemoteClient(entry.ssh)
            self._registry.add_peer(req.pid)
            self._save_config()
            return entry.model_dump()

        @config_router.put("/clients/{pid}")
        async def update_client(pid: str, req: ClientInput):
            entry = next((c for c in self._config.clients if c.pid == pid), None)
            if not entry:
                raise HTTPException(404, f"Client '{pid}' not found")
            # PID is immutable; re-derive topic/container in case project_name changed.
            entry.mqtt_topic, entry.container_name = _derive(pid)
            entry.ssh = SSHCredentials(**req.ssh.model_dump())
            self._remotes[pid] = RemoteClient(entry.ssh)
            self._save_config()
            return entry.model_dump()

        @config_router.delete("/clients/{pid}")
        async def delete_client(pid: str):
            logger.info("Delete client request: %s", pid)
            if not any(c.pid == pid for c in self._config.clients):
                raise HTTPException(404, f"Client '{pid}' not found")
            self._config.clients = [c for c in self._config.clients if c.pid != pid]
            self._remotes.pop(pid, None)
            self._registry.remove_peer(pid)
            self._save_config()
            logger.info("Client deleted: %s", pid)
            return {"deleted": pid}

        self._api.app.include_router(config_router)

    # ======================== MQTT Handlers ======================== #

    async def _on_client_status(self, topic: str, payload: dict) -> None:
        """Process a heartbeat from a client."""
        sender = payload.get("sender", "unknown")
        self._registry.heartbeat_received(sender, payload.get("payload", {}))

    async def _on_client_data(self, topic: str, payload: dict) -> None:
        """Process data from a client and store it."""
        sender = payload.get("sender", "unknown")
        msg_type = payload.get("msg_type", "unknown")
        data = payload.get("payload", {})
        logger.info("Data from %s: %s", sender, msg_type)

        # ── ESP data ── #

        if msg_type == "esp_status":
            # Update the peer's cached ESP board summary so the API can serve it.
            peer = self._registry.get(sender)
            if peer:
                peer.last_payload["esp_boards"]  = data.get("boards", [])
                peer.last_payload["esp_running"]  = data.get("running", 0)
                peer.last_payload["esp_total"]    = data.get("total", 0)

        elif msg_type == "flash_result":
            results = data.get("results", {})
            ok  = [p for p, s in results.items() if s]
            bad = [p for p, s in results.items() if not s]
            if bad:
                logger.error("Flash from %s — failed: %s", sender, bad)
            if ok:
                logger.info("Flash from %s — success: %s", sender, ok)

        # PROJECT-SPECIFIC: Handle your data types here, e.g.:
        # elif msg_type == "sensor_data" and "items" in data:
        #     await self._store.upsert_readings(data["items"])

    async def _on_client_response(self, topic: str, payload: dict) -> None:
        """Process a command response from a client."""
        sender = payload.get("sender", "unknown")
        msg_type = payload.get("msg_type", "unknown")
        logger.info("Response from %s: %s", sender, msg_type)

    # ======================== State Callbacks ======================== #

    async def _on_client_state_change(self, pid: str, old: PeerState, new: PeerState) -> None:
        if new == PeerState.ONLINE:
            logger.info("Client %s is ONLINE", pid)
        elif new == PeerState.STALE:
            logger.warning("Client %s heartbeat overdue", pid)
        elif new == PeerState.OFFLINE:
            logger.error("Client %s is OFFLINE", pid)
        logger.info("Registry: %s", self._registry.summary())

    # ======================== Periodic Loops ======================== #

    async def _maintenance_loop(self) -> None:
        """Periodic database maintenance."""
        interval = self._config.storage.checkpoint_interval
        logger.info("Maintenance loop started (interval=%.0fs)", interval)
        while True:
            await asyncio.sleep(interval)
            await self._store.prune_all()
            stats = await self._store.stats()
            logger.info("DB stats: %s", stats)

    async def _clock_sync_loop(self) -> None:
        """Periodically sync clocks on all online clients via SSH."""
        interval = self._config.sync.clock_sync_interval
        logger.info("Clock sync loop started (interval=%.0fs)", interval)
        while True:
            await asyncio.sleep(interval)
            for pid, remote in list(self._remotes.items()):
                peer = self._registry.get(pid)
                if peer and peer.state == PeerState.ONLINE:
                    try:
                        await remote.sync_clock()
                    except Exception as e:
                        logger.warning("Clock sync failed for %s: %s", pid, e)

    async def _pi_check_loop(self) -> None:
        """Periodically poll system info from all online clients via SSH."""
        interval = self._config.sync.pi_check_interval
        logger.info("Pi health check loop started (interval=%.0fs)", interval)
        while True:
            await asyncio.sleep(interval)
            for pid, remote in list(self._remotes.items()):
                peer = self._registry.get(pid)
                if peer and peer.state == PeerState.ONLINE:
                    try:
                        info = await remote.get_system_info()
                        logger.debug("Pi check %s: %s", pid, info)
                        peer.last_payload.update(info)
                    except Exception as e:
                        logger.warning("Pi check failed for %s: %s", pid, e)

    # ======================== Heartbeat ======================== #

    def _build_heartbeat(self) -> dict:
        """Build the host heartbeat payload."""
        return {
            "clients_connected": self._registry.online_count,
            "clients_expected": self._registry.expected_count,
            "registry": self._registry.summary(),
        }

    # ======================== Commands ======================== #

    async def send_command(self, pid: str, command: str, payload: dict | None = None) -> None:
        """Send a command to a specific client over MQTT."""
        envelope = build_envelope(sender="host", msg_type=command, payload=payload or {})
        await self._mqtt.publish(self._topics.host_command_to(pid), envelope)
        logger.info("Command sent to %s: %s", pid, command)

    async def broadcast_command(self, command: str, payload: dict | None = None) -> None:
        """Broadcast a command to all clients over MQTT."""
        envelope = build_envelope(sender="host", msg_type=command, payload=payload or {})
        await self._mqtt.publish(self._topics.host_command(), envelope)
        logger.info("Broadcast command: %s", command)
