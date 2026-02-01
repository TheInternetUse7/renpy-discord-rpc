from __future__ import annotations

import time
from dataclasses import dataclass

from pypresence import Presence


@dataclass
class PresenceState:
    last_update_monotonic: float = 0.0
    connected: bool = False


class DiscordRPC:
    def __init__(self, client_id: str, min_update_interval_seconds: float = 15.0) -> None:
        self.client_id = str(client_id)
        self.min_update_interval_seconds = float(min_update_interval_seconds)
        self._rpc: Presence | None = None
        self._state = PresenceState()

    def connect(self) -> None:
        if not self.client_id:
            raise ValueError("client_id is empty")
        if self._state.connected and self._rpc is not None:
            return
        self._rpc = Presence(self.client_id)
        self._rpc.connect()
        self._state.connected = True

    def close(self) -> None:
        if self._rpc is None:
            return
        try:
            self._rpc.close()
        finally:
            self._rpc = None
            self._state.connected = False

    def _can_update(self, *, force: bool = False) -> bool:
        if force:
            return True
        now = time.monotonic()
        return (now - self._state.last_update_monotonic) >= self.min_update_interval_seconds

    def clear(self, *, force: bool = False) -> None:
        if self._rpc is None:
            return
        if not self._can_update(force=force):
            return
        self._rpc.clear()
        self._state.last_update_monotonic = time.monotonic()

    def update(
        self,
        *,
        details: str,
        state: str,
        large_image: str | None = None,
        large_text: str | None = None,
        force: bool = False,
    ) -> None:
        if self._rpc is None:
            return
        if not self._can_update(force=force):
            return
        payload: dict[str, object] = {
            "details": details,
            "state": state,
        }
        if large_image:
            payload["large_image"] = large_image
            if large_text:
                payload["large_text"] = large_text
        self._rpc.update(**payload)
        self._state.last_update_monotonic = time.monotonic()
