"""Base API routes available to all projects.

Provides health check, system status, and peer registry endpoints.
These are automatically included when using the base APIServer.
"""

import time
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["system"])

# These get populated by the host runtime at startup.
_start_time: float = 0.0
_registry_fn = None
_extras_fn = None


def init_base_routes(
    registry_fn=None,
    extras_fn=None,
) -> None:
    """Initialise base routes with runtime dependencies.

    Args:
        registry_fn: Callable returning the PeerRegistry summary dict.
        extras_fn: Callable returning any extra status data.
    """
    global _start_time, _registry_fn, _extras_fn
    _start_time = time.time()
    _registry_fn = registry_fn
    _extras_fn = extras_fn


@router.get("/health")
async def health() -> dict[str, str]:
    """Simple health check."""
    return {"status": "ok"}


@router.get("/status")
async def status() -> dict[str, Any]:
    """System status overview."""
    data: dict[str, Any] = {
        "uptime": round(time.time() - _start_time, 1) if _start_time else 0,
    }
    if _registry_fn:
        data["clients"] = _registry_fn()
    if _extras_fn:
        data.update(_extras_fn())
    return data
