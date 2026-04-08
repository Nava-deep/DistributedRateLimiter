from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic

from app.schemas.policy import PolicyRead


@dataclass(slots=True)
class LocalPolicySnapshot:
    policies: list[PolicyRead]
    loaded_at_monotonic: float


class PolicySnapshotStore:
    def __init__(self) -> None:
        self._snapshot: LocalPolicySnapshot | None = None
        self._lock = asyncio.Lock()

    async def set(self, policies: list[PolicyRead]) -> None:
        async with self._lock:
            self._snapshot = LocalPolicySnapshot(
                policies=list(policies),
                loaded_at_monotonic=monotonic(),
            )

    async def get_fresh(self, ttl_seconds: int) -> list[PolicyRead] | None:
        async with self._lock:
            if self._snapshot is None:
                return None

            age = monotonic() - self._snapshot.loaded_at_monotonic
            if age > ttl_seconds:
                return None

            return list(self._snapshot.policies)

    async def clear(self) -> None:
        async with self._lock:
            self._snapshot = None

