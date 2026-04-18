from __future__ import annotations

import pytest

from app.services.multi_region import simulate_multi_region_limit


@pytest.mark.unit
def test_multi_region_simulation_has_no_oversubscription_without_replication_lag() -> None:
    summary, _ = simulate_multi_region_limit(
        configured_limit=10,
        replication_lag_ms=0,
        india_requests=8,
        us_requests=8,
        request_spacing_ms=20,
    )

    assert summary.oversubscription == 0
    assert summary.stale_allowed_decisions == 0


@pytest.mark.unit
def test_multi_region_simulation_shows_stale_decisions_with_replication_lag() -> None:
    summary, decisions = simulate_multi_region_limit(
        configured_limit=6,
        replication_lag_ms=200,
        india_requests=6,
        us_requests=6,
        request_spacing_ms=10,
    )

    assert summary.oversubscription > 0
    assert summary.stale_allowed_decisions > 0
    assert any(
        decision.accepted and decision.actual_global_before_decision >= summary.configured_limit
        for decision in decisions
    )


@pytest.mark.unit
def test_multi_region_simulation_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError):
        simulate_multi_region_limit(configured_limit=0)


@pytest.mark.unit
def test_multi_region_simulation_rejects_negative_replication_lag() -> None:
    with pytest.raises(ValueError):
        simulate_multi_region_limit(replication_lag_ms=-1)


@pytest.mark.unit
def test_multi_region_simulation_totals_match_per_region_counts() -> None:
    summary, _ = simulate_multi_region_limit(
        configured_limit=12,
        replication_lag_ms=50,
        india_requests=5,
        us_requests=4,
        request_spacing_ms=30,
    )

    assert summary.total_allowed == summary.india_allowed + summary.us_allowed
    assert summary.india_requests_sent == summary.india_allowed + summary.india_blocked
    assert summary.us_requests_sent == summary.us_allowed + summary.us_blocked


@pytest.mark.unit
def test_multi_region_simulation_tracks_replication_queue_depth() -> None:
    summary, _ = simulate_multi_region_limit(
        configured_limit=6,
        replication_lag_ms=120,
        india_requests=4,
        us_requests=4,
        request_spacing_ms=5,
    )

    assert summary.max_replication_queue_depth >= 8
