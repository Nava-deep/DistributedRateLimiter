from __future__ import annotations

import heapq
from dataclasses import asdict, dataclass
from typing import Literal

RegionName = Literal["india", "us"]
EventKind = Literal["request", "replication"]


@dataclass(slots=True)
class RegionalDecision:
    region: RegionName
    kind: EventKind
    time_ms: int
    accepted: bool
    known_global_before_decision: int
    actual_global_before_decision: int
    observed_remote_count: int


@dataclass(slots=True)
class RegionSnapshot:
    name: RegionName
    local_accepted: int = 0
    remote_observed: int = 0
    allowed_requests: int = 0
    blocked_requests: int = 0


@dataclass(slots=True)
class MultiRegionSummary:
    configured_limit: int
    replication_lag_ms: int
    request_spacing_ms: int
    india_requests_sent: int
    us_requests_sent: int
    india_allowed: int
    india_blocked: int
    us_allowed: int
    us_blocked: int
    total_allowed: int
    oversubscription: int
    stale_allowed_decisions: int
    max_replication_queue_depth: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(order=True, slots=True)
class _Event:
    time_ms: int
    priority: int
    kind: EventKind
    region: RegionName


def simulate_multi_region_limit(
    *,
    configured_limit: int = 10,
    replication_lag_ms: int = 180,
    india_requests: int = 8,
    us_requests: int = 8,
    request_spacing_ms: int = 20,
) -> tuple[MultiRegionSummary, list[RegionalDecision]]:
    if configured_limit <= 0:
        raise ValueError("configured_limit must be positive")
    if replication_lag_ms < 0:
        raise ValueError("replication_lag_ms cannot be negative")

    india = RegionSnapshot(name="india")
    us = RegionSnapshot(name="us")
    regions: dict[RegionName, RegionSnapshot] = {"india": india, "us": us}

    queue: list[_Event] = []
    for index in range(india_requests):
        heapq.heappush(queue, _Event(index * request_spacing_ms, 1, "request", "india"))
    for index in range(us_requests):
        heapq.heappush(queue, _Event(index * request_spacing_ms, 1, "request", "us"))

    decisions: list[RegionalDecision] = []
    stale_allowed = 0
    max_queue_depth = len(queue)

    while queue:
        max_queue_depth = max(max_queue_depth, len(queue))
        event = heapq.heappop(queue)

        if event.kind == "replication":
            source = regions[event.region]
            target = us if event.region == "india" else india
            target.remote_observed = max(target.remote_observed, source.local_accepted)
            continue

        region = regions[event.region]
        actual_global = india.local_accepted + us.local_accepted
        known_global = region.local_accepted + region.remote_observed
        accepted = known_global < configured_limit

        if accepted:
            if actual_global >= configured_limit:
                stale_allowed += 1
            region.local_accepted += 1
            region.allowed_requests += 1
            heapq.heappush(
                queue,
                _Event(
                    event.time_ms + replication_lag_ms,
                    0,
                    "replication",
                    event.region,
                ),
            )
        else:
            region.blocked_requests += 1

        decisions.append(
            RegionalDecision(
                region=event.region,
                kind=event.kind,
                time_ms=event.time_ms,
                accepted=accepted,
                known_global_before_decision=known_global,
                actual_global_before_decision=actual_global,
                observed_remote_count=region.remote_observed,
            )
        )

    total_allowed = india.allowed_requests + us.allowed_requests
    summary = MultiRegionSummary(
        configured_limit=configured_limit,
        replication_lag_ms=replication_lag_ms,
        request_spacing_ms=request_spacing_ms,
        india_requests_sent=india_requests,
        us_requests_sent=us_requests,
        india_allowed=india.allowed_requests,
        india_blocked=india.blocked_requests,
        us_allowed=us.allowed_requests,
        us_blocked=us.blocked_requests,
        total_allowed=total_allowed,
        oversubscription=max(0, total_allowed - configured_limit),
        stale_allowed_decisions=stale_allowed,
        max_replication_queue_depth=max_queue_depth,
    )
    return summary, decisions
