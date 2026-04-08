"""Client-side host state tracking.

The client needs to know if the host is reachable. This is a simplified
single-peer tracker: it listens for host heartbeats and transitions
between ONLINE / STALE / OFFLINE.
"""

import asyncio
import logging
import time
from typing import Any, Callable, Awaitable

from base.host.state import PeerState

logger = logging.getLogger(__name__)

StateChangeCallback = Callable[[PeerState, PeerState], Awaitable[None]]


class HostTracker:
    """Tracks whether the host is reachable based on its heartbeats.

    Args:
        timeout: Seconds without a heartbeat before the host is STALE.
        offline_after: Seconds without a heartbeat before the host is OFFLINE.
        check_interval: How often (seconds) to evaluate state.
    """

    def __init__(
        self,
        timeout: float = 15.0,
        offline_after: float = 30.0,
        check_interval: float = 5.0,
    ) -> None:
        self._timeout = timeout
        self._offline_after = offline_after
        self._check_interval = check_interval
        self._state = PeerState.UNKNOWN
        self._last_seen: float = 0.0
        self._last_payload: dict[str, Any] = {}
        self._on_change: list[StateChangeCallback] = []

    # ======================== Properties ======================== #

    @property
    def state(self) -> PeerState:
        return self._state

    @property
    def is_online(self) -> bool:
        return self._state == PeerState.ONLINE

    @property
    def last_seen(self) -> float:
        return self._last_seen

    @property
    def last_payload(self) -> dict[str, Any]:
        return dict(self._last_payload)

    # ======================== Events ======================== #

    def on_state_change(self, callback: StateChangeCallback) -> None:
        """Register a callback for host state changes.

        Callback signature: async (old_state, new_state) -> None
        """
        self._on_change.append(callback)

    # ======================== Heartbeat ======================== #

    def heartbeat_received(self, payload: dict[str, Any] | None = None) -> None:
        """Record that a heartbeat was received from the host."""
        old = self._state
        self._last_seen = time.time()
        self._last_payload = payload or {}
        self._state = PeerState.ONLINE

        if old != PeerState.ONLINE:
            logger.info("Host: %s -> ONLINE", old.value)
            self._fire_change(old, PeerState.ONLINE)

    # ======================== State Check Loop ======================== #

    async def run(self) -> None:
        """Run the state checker in a loop. Call as an asyncio task."""
        logger.info(
            "HostTracker running (timeout=%.1fs, offline=%.1fs)",
            self._timeout, self._offline_after,
        )
        while True:
            self._check_state()
            await asyncio.sleep(self._check_interval)

    def _check_state(self) -> None:
        """Evaluate host state based on time since last heartbeat."""
        if self._state == PeerState.UNKNOWN:
            return

        elapsed = time.time() - self._last_seen
        old = self._state

        if elapsed > self._offline_after and self._state != PeerState.OFFLINE:
            self._state = PeerState.OFFLINE
            logger.warning("Host: %s -> OFFLINE (%.1fs)", old.value, elapsed)
            self._fire_change(old, PeerState.OFFLINE)

        elif elapsed > self._timeout and self._state == PeerState.ONLINE:
            self._state = PeerState.STALE
            logger.warning("Host: ONLINE -> STALE (%.1fs)", elapsed)
            self._fire_change(old, PeerState.STALE)

    # ======================== Internal ======================== #

    def _fire_change(self, old: PeerState, new: PeerState) -> None:
        for cb in self._on_change:
            try:
                loop = asyncio.get_running_loop()
                asyncio.run_coroutine_threadsafe(cb(old, new), loop)
            except RuntimeError:
                pass
