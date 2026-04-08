"""Host-side peer state tracking.

The host needs to know which clients are alive, which have gone silent,
and which have never connected. This module provides that tracking
based on heartbeat messages received over MQTT.
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, Awaitable

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Callback type for state change events.
StateChangeCallback = Callable[[str, "PeerState", "PeerState"], Awaitable[None]]


class PeerState(str, Enum):
    """Possible states of a remote peer."""
    UNKNOWN     = "unknown"       # Never seen a heartbeat.
    ONLINE      = "online"        # Heartbeats arriving on time.
    STALE       = "stale"         # Heartbeat overdue but within grace.
    OFFLINE     = "offline"       # Heartbeat expired — peer is down.


class PeerStatus(BaseModel):
    """Snapshot of a peer's current status."""
    pid: str
    state: PeerState = PeerState.UNKNOWN
    last_seen: float = 0.0
    last_payload: dict[str, Any] = {}
    miss_count: int = 0


class PeerRegistry:
    """Tracks the state of multiple remote peers (clients) via heartbeats.

    Args:
        expected_pids: List of peer IDs the host expects to see.
        timeout: Seconds without a heartbeat before a peer is marked STALE.
        offline_after: Seconds without a heartbeat before a peer is marked OFFLINE.
        check_interval: How often (seconds) to run the state check loop.
    """

    def __init__(
        self,
        expected_pids: list[str],
        timeout: float = 15.0,
        offline_after: float = 30.0,
        check_interval: float = 5.0,
    ) -> None:
        self._timeout = timeout
        self._offline_after = offline_after
        self._check_interval = check_interval
        self._on_change: list[StateChangeCallback] = []

        # Initialise a status entry for every expected peer.
        self._peers: dict[str, PeerStatus] = {
            pid: PeerStatus(pid=pid) for pid in expected_pids
        }

    # ======================== Properties ======================== #

    @property
    def peers(self) -> dict[str, PeerStatus]:
        return dict(self._peers)

    @property
    def online_count(self) -> int:
        return sum(1 for p in self._peers.values() if p.state == PeerState.ONLINE)

    @property
    def expected_count(self) -> int:
        return len(self._peers)

    def get(self, pid: str) -> PeerStatus | None:
        return self._peers.get(pid)

    def add_peer(self, pid: str) -> None:
        """Register a new expected peer (no-op if already present)."""
        if pid not in self._peers:
            self._peers[pid] = PeerStatus(pid=pid)

    def remove_peer(self, pid: str) -> None:
        """Remove a peer from the registry."""
        self._peers.pop(pid, None)

    def summary(self) -> dict[str, str]:
        """Return a {pid: state} summary dict."""
        return {pid: p.state.value for pid, p in self._peers.items()}

    # ======================== Events ======================== #

    def on_state_change(self, callback: StateChangeCallback) -> None:
        """Register a callback for when any peer changes state.

        Callback signature: async (pid, old_state, new_state) -> None
        """
        self._on_change.append(callback)

    # ======================== Heartbeat Ingestion ======================== #

    def heartbeat_received(self, pid: str, payload: dict[str, Any] | None = None) -> None:
        """Record that a heartbeat was received from a peer.

        If the peer is not in the expected list, it is added dynamically.
        """
        now = time.time()

        if pid not in self._peers:
            logger.info("Discovered new peer: %s", pid)
            self._peers[pid] = PeerStatus(pid=pid)

        peer = self._peers[pid]
        old_state = peer.state

        peer.last_seen = now
        peer.last_payload = payload or {}
        peer.miss_count = 0
        peer.state = PeerState.ONLINE

        if old_state != PeerState.ONLINE:
            logger.info("Peer %s: %s -> ONLINE", pid, old_state.value)
            self._fire_change(pid, old_state, PeerState.ONLINE)

    # ======================== State Check Loop ======================== #

    async def run(self) -> None:
        """Run the state checker in a loop. Call as an asyncio task."""
        logger.info(
            "PeerRegistry running (timeout=%.1fs, offline=%.1fs, check=%.1fs)",
            self._timeout, self._offline_after, self._check_interval,
        )
        while True:
            self._check_states()
            await asyncio.sleep(self._check_interval)

    def _check_states(self) -> None:
        """Evaluate all peers and transition states based on last_seen."""
        now = time.time()

        for pid, peer in self._peers.items():
            if peer.state == PeerState.UNKNOWN:
                continue

            elapsed = now - peer.last_seen
            old_state = peer.state

            if elapsed > self._offline_after and peer.state != PeerState.OFFLINE:
                peer.state = PeerState.OFFLINE
                peer.miss_count += 1
                logger.warning("Peer %s: %s -> OFFLINE (%.1fs since last heartbeat)", pid, old_state.value, elapsed)
                self._fire_change(pid, old_state, PeerState.OFFLINE)

            elif elapsed > self._timeout and peer.state == PeerState.ONLINE:
                peer.state = PeerState.STALE
                peer.miss_count += 1
                logger.warning("Peer %s: ONLINE -> STALE (%.1fs since last heartbeat)", pid, elapsed)
                self._fire_change(pid, old_state, PeerState.STALE)

    # ======================== Internal ======================== #

    def _fire_change(self, pid: str, old: PeerState, new: PeerState) -> None:
        """Dispatch state change callbacks."""
        for cb in self._on_change:
            try:
                loop = asyncio.get_running_loop()
                asyncio.run_coroutine_threadsafe(cb(pid, old, new), loop)
            except RuntimeError:
                pass
