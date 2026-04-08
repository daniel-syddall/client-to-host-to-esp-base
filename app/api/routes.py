"""Project-specific API routes.

Provides endpoints for querying project data, sending commands
to clients, and viewing live system state. These get mounted
alongside the base routes.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/project", tags=["project"])

# Runtime dependencies — injected at startup.
_store = None
_registry = None
_mqtt = None
_topics = None


def init_project_routes(store, registry, mqtt, topics) -> None:
    """Inject runtime dependencies into the route handlers.

    Args:
        store: HostStore instance.
        registry: PeerRegistry instance.
        mqtt: MQTTClient instance.
        topics: TopicManager instance.
    """
    global _store, _registry, _mqtt, _topics
    _store = store
    _registry = registry
    _mqtt = mqtt
    _topics = topics


# ======================== Stats ======================== #

@router.get("/stats")
async def get_stats() -> dict[str, Any]:
    """Get database statistics."""
    stats = await _store.stats()
    stats["clients"] = _registry.summary() if _registry else {}
    stats["clients_online"] = _registry.online_count if _registry else 0
    stats["clients_expected"] = _registry.expected_count if _registry else 0
    return stats


# ======================== Data Queries ======================== #

# PROJECT-SPECIFIC: Add your data query endpoints here, e.g.:
#
# @router.get("/readings")
# async def get_readings() -> list[dict[str, Any]]:
#     """Get all sensor readings."""
#     return await _store.get_all_readings()


# ======================== ESP Endpoints ======================== #

@router.get("/esp/status")
async def get_esp_status() -> dict[str, Any]:
    """Get live ESP board status for all clients.

    Returns a dict keyed by client PID, each containing the last
    known ESP board summary received from that client.
    """
    if not _registry:
        raise HTTPException(status_code=503, detail="Registry not available")
    result: dict[str, Any] = {}
    for pid, peer in _registry.peers.items():
        result[pid] = {
            "esp_boards":  peer.last_payload.get("esp_boards", []),
            "esp_running": peer.last_payload.get("esp_running", 0),
            "esp_total":   peer.last_payload.get("esp_total", 0),
        }
    return result


class FlashRequest(BaseModel):
    """Request body for triggering firmware flash on a client's boards."""
    pid:   str
    ports: list[str] = []   # Empty = flash all boards on that client.


@router.post("/esp/flash")
async def flash_esp(req: FlashRequest) -> dict[str, str]:
    """Send a FLASH_REQUEST command to a specific client.

    The client will flash the specified ports (or all boards if ports is empty),
    then publish a FLASH_RESULT message back to the host.
    """
    if not _mqtt or not _topics:
        raise HTTPException(status_code=503, detail="MQTT not available")
    from base.comms import build_envelope
    envelope = build_envelope(
        sender="host",
        msg_type="flash_request",
        payload={"ports": req.ports},
    )
    topic = _topics.host_command_to(req.pid)
    await _mqtt.publish(topic, envelope)
    logger.info("Flash request sent to %s (ports=%s)", req.pid, req.ports or "all")
    return {"status": "sent", "pid": req.pid, "topic": topic}


class ESPCommandRequest(BaseModel):
    """Request body for relaying a command to ESP boards on a client."""
    pid:       str
    cmd:       str
    board_ids: list[int] = []   # Empty = all boards on that client.
    args:      dict[str, Any] = {}


@router.post("/esp/command")
async def send_esp_command(req: ESPCommandRequest) -> dict[str, str]:
    """Send an ESP_COMMAND to a specific client.

    The client will relay the command over serial to the targeted board(s).
    """
    if not _mqtt or not _topics:
        raise HTTPException(status_code=503, detail="MQTT not available")
    from base.comms import build_envelope
    envelope = build_envelope(
        sender="host",
        msg_type="esp_command",
        payload={
            "cmd":       req.cmd,
            "board_ids": req.board_ids,
            "args":      req.args,
        },
    )
    topic = _topics.host_command_to(req.pid)
    await _mqtt.publish(topic, envelope)
    logger.info("ESP command '%s' sent to %s (boards=%s)", req.cmd, req.pid, req.board_ids or "all")
    return {"status": "sent", "pid": req.pid, "cmd": req.cmd, "topic": topic}


# ======================== Client Commands ======================== #

class CommandRequest(BaseModel):
    """Request body for sending a command to a client."""
    pid: str
    command: str
    payload: dict[str, Any] = {}


class BroadcastRequest(BaseModel):
    """Request body for broadcasting a command to all clients."""
    command: str
    payload: dict[str, Any] = {}


@router.post("/command")
async def send_command(req: CommandRequest) -> dict[str, str]:
    """Send a command to a specific client."""
    if not _mqtt or not _topics:
        raise HTTPException(status_code=503, detail="MQTT not available")

    from base.comms import build_envelope
    envelope = build_envelope(
        sender="host",
        msg_type=req.command,
        payload=req.payload,
    )
    topic = _topics.host_command_to(req.pid)
    await _mqtt.publish(topic, envelope)
    logger.info("Command sent to %s: %s", req.pid, req.command)
    return {"status": "sent", "topic": topic}


@router.post("/command/broadcast")
async def broadcast_command(req: BroadcastRequest) -> dict[str, str]:
    """Broadcast a command to all clients."""
    if not _mqtt or not _topics:
        raise HTTPException(status_code=503, detail="MQTT not available")

    from base.comms import build_envelope
    envelope = build_envelope(
        sender="host",
        msg_type=req.command,
        payload=req.payload,
    )
    topic = _topics.host_command()
    await _mqtt.publish(topic, envelope)
    logger.info("Broadcast command: %s", req.command)
    return {"status": "broadcast", "topic": topic}
