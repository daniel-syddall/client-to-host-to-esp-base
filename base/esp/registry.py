"""ESP board state registry.

Tracks the live state of every ESP board connected to this Pi.
Analogous to PeerRegistry (host tracks Pis) but scoped to one Pi's
local USB-connected boards.

State machine per board:
    WAITING  ──► READY  ──► RUNNING ──► STALE
                   │                      │
                   └──────────────────────┤
                                          ▼
                                    DISCONNECTED
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, Awaitable

from pydantic import BaseModel

logger = logging.getLogger(__name__)

StateChangeCallback = Callable[[int, "BoardState", "BoardState"], Awaitable[None]]


# ======================== State ======================== #

class BoardState(str, Enum):
    WAITING      = "waiting"       # Serial connected, handshake not yet complete.
    READY        = "ready"         # INIT sent and ACK received, awaiting START.
    RUNNING      = "running"       # START sent — board is actively working.
    STALE        = "stale"         # Heartbeat overdue but still connected.
    DISCONNECTED = "disconnected"  # Serial device lost or unreachable.


class BoardStatus(BaseModel):
    """Live snapshot of one ESP board's status."""
    board_id:     int
    port:         str
    state:        BoardState        = BoardState.WAITING
    last_seen:    float             = 0.0
    last_payload: dict[str, Any]   = {}


# ======================== Registry ======================== #

class ESPRegistry:
    """Tracks the state of ESP boards connected to this Pi.

    Args:
        timeout: Seconds without a heartbeat before a RUNNING board is marked STALE.
        check_interval: How often (seconds) to run the state check loop.
    """

    def __init__(
        self,
        timeout: float = 15.0,
        check_interval: float = 5.0,
    ) -> None:
        self._timeout        = timeout
        self._check_interval = check_interval
        self._boards: dict[int, BoardStatus] = {}
        self._on_change: list[StateChangeCallback] = []

    # ======================== Properties ======================== #

    @property
    def boards(self) -> dict[int, BoardStatus]:
        return dict(self._boards)

    @property
    def running_count(self) -> int:
        return sum(1 for b in self._boards.values() if b.state == BoardState.RUNNING)

    @property
    def total_count(self) -> int:
        return len(self._boards)

    def get(self, board_id: int) -> BoardStatus | None:
        return self._boards.get(board_id)

    def summary(self) -> dict[str, str]:
        """Return {board_id_str: state_str} for all boards."""
        return {str(b.board_id): b.state.value for b in self._boards.values()}

    # ======================== Registration ======================== #

    def register(self, board_id: int, port: str) -> None:
        """Register a newly discovered board."""
        self._boards[board_id] = BoardStatus(board_id=board_id, port=port)
        logger.info("ESP board registered: id=%d port=%s", board_id, port)

    def remove(self, board_id: int) -> None:
        self._boards.pop(board_id, None)

    # ======================== State Transitions ======================== #

    def set_state(self, board_id: int, state: BoardState) -> None:
        """Transition a board to a new state and fire callbacks."""
        board = self._boards.get(board_id)
        if not board:
            return
        old = board.state
        if old == state:
            return
        board.state = state
        logger.info("ESP board %d: %s -> %s", board_id, old.value, state.value)
        self._fire_change(board_id, old, state)

    def heartbeat_received(self, board_id: int, payload: dict[str, Any] | None = None) -> None:
        """Record a heartbeat from a board. Clears STALE if previously stale."""
        board = self._boards.get(board_id)
        if not board:
            return
        board.last_seen    = time.time()
        board.last_payload = payload or {}
        if board.state == BoardState.STALE:
            self.set_state(board_id, BoardState.RUNNING)

    # ======================== Events ======================== #

    def on_state_change(self, callback: StateChangeCallback) -> None:
        """Register a callback fired on any board state transition.

        Signature: async (board_id, old_state, new_state) -> None
        """
        self._on_change.append(callback)

    # ======================== Check Loop ======================== #

    async def run(self) -> None:
        """Run the stale-detection loop as an asyncio task."""
        logger.info("ESPRegistry running (timeout=%.1fs)", self._timeout)
        while True:
            self._check_states()
            await asyncio.sleep(self._check_interval)

    def _check_states(self) -> None:
        now = time.time()
        for board_id, board in self._boards.items():
            if board.state != BoardState.RUNNING:
                continue
            if now - board.last_seen > self._timeout:
                self.set_state(board_id, BoardState.STALE)

    # ======================== Internal ======================== #

    def _fire_change(self, board_id: int, old: BoardState, new: BoardState) -> None:
        for cb in self._on_change:
            try:
                loop = asyncio.get_running_loop()
                asyncio.run_coroutine_threadsafe(cb(board_id, old, new), loop)
            except RuntimeError:
                pass
