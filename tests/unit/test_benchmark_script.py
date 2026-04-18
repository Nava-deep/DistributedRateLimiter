from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_benchmark import (
    BenchmarkSummary,
    benchmark_policy_payloads,
    create_results_dir,
    display_scenario_name,
    normalize_scenario,
    parse_error_report,
    parse_locust_console_summary,
    parse_target_hosts,
    write_summary,
)


@pytest.mark.unit
def test_parse_target_hosts_splits_and_trims_hosts() -> None:
    hosts = parse_target_hosts(" http://localhost:8000/ ,http://localhost:8001 ")

    assert hosts == ["http://localhost:8000", "http://localhost:8001"]


@pytest.mark.unit
def test_parse_target_hosts_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        parse_target_hosts(" , ")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw_scenario", "expected"),
    [
        ("shared-quota", "shared-protected"),
        ("shared-protected", "shared-protected"),
        ("burst-route", "protected-burst"),
        ("platform-services", "platform-services"),
    ],
)
def test_normalize_scenario_handles_aliases(raw_scenario: str, expected: str) -> None:
    assert normalize_scenario(raw_scenario) == expected


@pytest.mark.unit
def test_normalize_scenario_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        normalize_scenario("unknown")


@pytest.mark.unit
def test_display_scenario_name_maps_internal_name_to_public_label() -> None:
    assert display_scenario_name("shared-protected") == "shared-quota"


@pytest.mark.unit
def test_benchmark_policy_payloads_for_platform_services_include_all_routes() -> None:
    payloads = list(benchmark_policy_payloads("platform-services"))

    assert [item["route"] for item in payloads] == [
        "/services/auth/session",
        "/services/payments/authorize",
        "/services/search/query",
    ]


@pytest.mark.unit
def test_benchmark_policy_payloads_for_shared_protected_return_single_policy() -> None:
    payloads = list(benchmark_policy_payloads("shared-protected"))

    assert len(payloads) == 1
    assert payloads[0]["route"] == "/demo/protected"


@pytest.mark.unit
def test_create_results_dir_creates_timestamped_directory(tmp_path: Path) -> None:
    result_dir = create_results_dir(tmp_path, "shared-quota")

    assert result_dir.exists()
    assert result_dir.name.endswith("_shared-quota")


@pytest.mark.unit
def test_parse_error_report_counts_blocked_and_other_errors(tmp_path: Path) -> None:
    log_path = tmp_path / "locust_stderr.log"
    log_path.write_text(
        "\n".join(
            [
                "  3 rate_limit_blocked",
                "  2 unexpected server error 500",
                "  1 # occurrences",
            ]
        ),
        encoding="utf-8",
    )

    blocked_requests, error_requests = parse_error_report(log_path)

    assert blocked_requests == 3
    assert error_requests == 2


@pytest.mark.unit
def test_parse_error_report_returns_zeroes_when_log_is_missing(tmp_path: Path) -> None:
    blocked_requests, error_requests = parse_error_report(tmp_path / "missing.log")

    assert blocked_requests == 0
    assert error_requests == 0


@pytest.mark.unit
def test_parse_locust_console_summary_parses_aggregated_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "locust_stderr.log"
    log_path.write_text(
        "\n".join(
            [
                "Aggregated         86     5(5.81%) |     7     12    30    12 |    31.24    0.00",
                "Aggregated 86 5(5.81%) 7 12 30 12 31.24 0.00 0 0 0 0",
            ]
        ),
        encoding="utf-8",
    )

    total_requests, total_failures, avg_latency_ms, p95_latency_ms, requests_per_second = (
        parse_locust_console_summary(log_path)
    )

    assert total_requests == 86
    assert total_failures == 5
    assert avg_latency_ms == 7.0
    assert p95_latency_ms == 12.0
    assert requests_per_second == 31.24


@pytest.mark.unit
def test_parse_locust_console_summary_raises_when_aggregate_is_missing(tmp_path: Path) -> None:
    log_path = tmp_path / "locust_stderr.log"
    log_path.write_text("no aggregate line here\n", encoding="utf-8")

    with pytest.raises(ValueError):
        parse_locust_console_summary(log_path)


@pytest.mark.unit
def test_write_summary_writes_json_and_markdown(tmp_path: Path) -> None:
    summary = BenchmarkSummary(
        scenario="platform-services",
        correctness_test_count=172,
        target_hosts=["http://localhost:8001", "http://localhost:8002"],
        api_instances=2,
        concurrent_users=80,
        spawn_rate=20.0,
        run_time="45s",
        total_requests=100,
        allowed_requests=90,
        blocked_requests=10,
        error_requests=0,
        avg_latency_ms=8.5,
        p95_latency_ms=15.2,
        requests_per_second=35.1,
        notes="Synthetic benchmark run",
        generated_at_utc="2026-04-18T00:00:00+00:00",
    )

    write_summary(tmp_path, summary)

    json_payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    markdown_payload = (tmp_path / "summary.md").read_text(encoding="utf-8")

    assert json_payload["scenario"] == "platform-services"
    assert json_payload["correctness_test_count"] == 172
    assert "Synthetic benchmark run" in markdown_payload
    assert "Use this report as the source of truth" in markdown_payload
