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
_store    = None
_registry = None
_mqtt     = None
_topics   = None
_console: dict[str, list] = {}   # pid → list of recent ESP data events (in-memory)


def init_project_routes(store, registry, mqtt, topics, console: dict | None = None) -> None:
    """Inject runtime dependencies into the route handlers.

    Args:
        store:    HostStore instance.
        registry: PeerRegistry instance.
        mqtt:     MQTTClient instance.
        topics:   TopicManager instance.
        console:  Shared in-memory ESP console buffer {pid: [event, ...]}.
    """
    global _store, _registry, _mqtt, _topics, _console
    _store    = store
    _registry = registry
    _mqtt     = mqtt
    _topics   = topics
    if console is not None:
        _console = console


# ======================== Stats ======================== #

@router.get("/stats")
async def get_stats() -> dict[str, Any]:
    """Get database statistics."""
    stats = await _store.stats()
    stats["clients"]          = _registry.summary() if _registry else {}
    stats["clients_online"]   = _registry.online_count if _registry else 0
    stats["clients_expected"] = _registry.expected_count if _registry else 0
    return stats


# ======================== Data Queries ======================== #

# PROJECT-SPECIFIC: Add your data query endpoints here, e.g.:
#
# @router.get("/readings")
# async def get_readings() -> list[dict[str, Any]]:
#     """Get all sensor readings."""
#     return await _store.get_all_readings()


# ======================== ESP Status ======================== #

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


# ======================== ESP Console ======================== #

@router.get("/esp/console")
async def get_esp_console(
    pid:   str | None = None,
    limit: int        = 50,
) -> dict[str, list]:
    """Return recent ESP data events from the in-memory console buffer.

    Args:
        pid:   If provided, return only events for that client.
               If omitted, return events for all clients.
        limit: Maximum number of events to return per client.

    Returns:
        Dict keyed by client PID, each value a list of event dicts
        (most recent last).
    """
    if pid:
        entries = _console.get(pid, [])
        return {pid: entries[-limit:]}
    return {p: events[-limit:] for p, events in _console.items()}


# ======================== ESP Flash ======================== #

class FlashRequest(BaseModel):
    """Request body for triggering firmware flash on a client's boards."""
    pid:   str
    ports: list[str] = []   # Empty = flash all boards on that client.


@router.post("/esp/flash")
async def flash_esp(req: FlashRequest) -> dict[str, str]:
    """Send a FLASH_REQUEST command to a specific client."""
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


# ======================== ESP Reboot ======================== #

class ESPRebootRequest(BaseModel):
    """Request body for triggering a reconnect/re-handshake on board(s)."""
    pid:       str
    board_ids: list[int] = []   # Empty = reboot all boards on that client.


@router.post("/esp/reboot")
async def reboot_esp_boards(req: ESPRebootRequest) -> dict[str, str]:
    """Send an ESP_REBOOT command to a client, triggering a re-handshake.

    The client closes the serial connection for each targeted board, which
    causes the board's read_loop to reconnect and run a fresh INIT→ACK→START
    handshake. The firmware handles the re-INIT while running, pausing and
    resuming its data_task without a hardware reset.

    Args:
        pid:       Client (Pi) to target.
        board_ids: Board IDs to reboot. Empty means all boards on that client.
    """
    if not _mqtt or not _topics:
        raise HTTPException(status_code=503, detail="MQTT not available")
    from base.comms import build_envelope
    envelope = build_envelope(
        sender="host",
        msg_type="esp_reboot",
        payload={"board_ids": req.board_ids},
    )
    topic = _topics.host_command_to(req.pid)
    await _mqtt.publish(topic, envelope)
    logger.info(
        "ESP reboot sent to %s (boards=%s)",
        req.pid, req.board_ids or "all",
    )
    return {"status": "sent", "pid": req.pid, "boards": str(req.board_ids or "all")}


# ======================== ESP Generic Command ======================== #

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
    logger.info(
        "ESP command '%s' sent to %s (boards=%s)",
        req.cmd, req.pid, req.board_ids or "all",
    )
    return {"status": "sent", "pid": req.pid, "cmd": req.cmd, "topic": topic}


# ======================== Client Commands ======================== #

class CommandRequest(BaseModel):
    """Request body for sending a command to a client."""
    pid:     str
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
