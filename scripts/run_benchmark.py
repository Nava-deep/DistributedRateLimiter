from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_DIR = ROOT / "benchmark_results"
SCENARIO_ALIASES = {
    "mixed": "mixed",
    "shared-quota": "shared-protected",
    "shared-protected": "shared-protected",
    "burst-route": "protected-burst",
    "protected-burst": "protected-burst",
    "user-hotspot": "user-hotspot",
    "ip-hotspot": "ip-hotspot",
    "platform-services": "platform-services",
}
SCENARIO_LABELS = {
    "mixed": "mixed",
    "shared-protected": "shared-quota",
    "protected-burst": "burst-route",
    "user-hotspot": "user-hotspot",
    "ip-hotspot": "ip-hotspot",
    "platform-services": "platform-services",
}


@dataclass(slots=True)
class BenchmarkSummary:
    scenario: str
    correctness_test_count: int
    target_hosts: list[str]
    api_instances: int
    concurrent_users: int
    spawn_rate: float
    run_time: str
    total_requests: int
    allowed_requests: int
    blocked_requests: int
    error_requests: int
    avg_latency_ms: float | None
    p95_latency_ms: float | None
    requests_per_second: float | None
    notes: str | None
    generated_at_utc: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a reproducible Locust benchmark against the distributed rate limiter.",
    )
    parser.add_argument(
        "--target-hosts",
        default="http://localhost:8000",
        help="Comma-separated list of API or load-balancer base URLs.",
    )
    parser.add_argument(
        "--scenario",
        default="shared-quota",
        help="Benchmark scenario to prepare and execute.",
    )
    parser.add_argument("--users", type=int, default=40, help="Concurrent Locust users.")
    parser.add_argument("--spawn-rate", type=float, default=10.0, help="Users spawned per second.")
    parser.add_argument("--run-time", default="30s", help="Locust run time, for example 30s or 2m.")
    parser.add_argument(
        "--api-instances",
        type=int,
        default=1,
        help="Number of API instances behind the target host(s).",
    )
    parser.add_argument(
        "--admin-token",
        default=os.getenv("ADMIN_TOKEN", "super-secret-admin-token"),
        help="Admin token used to prepare benchmark policies.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_RESULTS_DIR),
        help="Directory where timestamped benchmark results will be written.",
    )
    parser.add_argument(
        "--notes",
        default=None,
        help="Optional environment notes stored with the benchmark summary.",
    )
    parser.add_argument(
        "--skip-prepare",
        action="store_true",
        help="Skip creating benchmark policies before running Locust.",
    )
    return parser.parse_args()


def parse_target_hosts(raw_hosts: str) -> list[str]:
    hosts = [host.strip().rstrip("/") for host in raw_hosts.split(",") if host.strip()]
    if not hosts:
        raise ValueError("At least one target host is required.")
    return hosts


def normalize_scenario(raw_scenario: str) -> str:
    try:
        return SCENARIO_ALIASES[raw_scenario.strip().lower()]
    except KeyError as exc:
        valid_scenarios = ", ".join(
            [
                "mixed",
                "shared-quota",
                "burst-route",
                "user-hotspot",
                "ip-hotspot",
                "platform-services",
            ]
        )
        raise ValueError(
            f"Unsupported scenario '{raw_scenario}'. Choose one of: {valid_scenarios}"
        ) from exc


def display_scenario_name(internal_scenario: str) -> str:
    return SCENARIO_LABELS[internal_scenario]


def benchmark_policy_payloads(scenario: str) -> Iterable[dict[str, Any]]:
    if scenario in {"protected-burst", "shared-protected"}:
        return [
            {
                "name": "benchmark-shared-protected",
                "description": "Benchmark policy for protected route burst traffic.",
                "algorithm": "token_bucket",
                "rate": 120,
                "window_seconds": 60,
                "burst_capacity": 120,
                "route": "/demo/protected",
                "failure_mode": "fail_closed",
            }
        ]
    if scenario == "user-hotspot":
        return [
            {
                "name": "benchmark-user-hotspot",
                "description": "Benchmark policy for user-scoped route traffic.",
                "algorithm": "token_bucket",
                "rate": 90,
                "window_seconds": 60,
                "burst_capacity": 90,
                "route": "/demo/user/{user_id}",
                "user_id": "vip-user",
                "failure_mode": "fail_closed",
            }
        ]
    if scenario == "ip-hotspot":
        return [
            {
                "name": "benchmark-ip-hotspot",
                "description": "Benchmark policy for a single forwarded IP.",
                "algorithm": "fixed_window",
                "rate": 60,
                "window_seconds": 60,
                "route": "/demo/protected",
                "ip_address": "203.0.113.10",
                "failure_mode": "fail_closed",
            }
        ]
    if scenario == "platform-services":
        return [
            {
                "name": "benchmark-auth-service",
                "description": "Benchmark policy for the auth platform service.",
                "algorithm": "token_bucket",
                "rate": 80,
                "window_seconds": 60,
                "burst_capacity": 80,
                "route": "/services/auth/session",
                "failure_mode": "fail_closed",
            },
            {
                "name": "benchmark-payments-service",
                "description": "Benchmark policy for the payments platform service.",
                "algorithm": "sliding_window_log",
                "rate": 45,
                "window_seconds": 60,
                "route": "/services/payments/authorize",
                "failure_mode": "fail_closed",
            },
            {
                "name": "benchmark-search-service",
                "description": "Benchmark policy for the search platform service.",
                "algorithm": "fixed_window",
                "rate": 120,
                "window_seconds": 60,
                "route": "/services/search/query",
                "failure_mode": "fail_closed",
            },
        ]
    return [
        {
            "name": "benchmark-public-mixed",
            "description": "Mixed benchmark route policy for protected endpoint.",
            "algorithm": "token_bucket",
            "rate": 120,
            "window_seconds": 60,
            "burst_capacity": 120,
            "route": "/demo/protected",
            "failure_mode": "fail_closed",
        },
        {
            "name": "benchmark-user-mixed",
            "description": "Mixed benchmark route policy for user endpoint.",
            "algorithm": "sliding_window_log",
            "rate": 90,
            "window_seconds": 60,
            "route": "/demo/user/{user_id}",
            "user_id": "vip-user",
            "failure_mode": "fail_closed",
        },
    ]


def prepare_benchmark_policies(base_url: str, admin_token: str, scenario: str) -> None:
    headers = {"X-Admin-Token": admin_token}
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        response = client.get("/admin/policies", headers=headers)
        response.raise_for_status()
        existing = {item["name"]: item["id"] for item in response.json()["items"]}

        for payload in benchmark_policy_payloads(scenario):
            existing_id = existing.get(payload["name"])
            if existing_id is None:
                created = client.post("/admin/policies", headers=headers, json=payload)
                created.raise_for_status()
                continue

            updated = client.put(f"/admin/policies/{existing_id}", headers=headers, json=payload)
            updated.raise_for_status()


def create_results_dir(root: Path, scenario: str) -> Path:
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    result_dir = root / f"{timestamp}_{scenario}"
    result_dir.mkdir(parents=True, exist_ok=False)
    return result_dir


def collect_test_count() -> int:
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    output = "\n".join([completed.stdout, completed.stderr])
    match = re.search(r"(\d+)\s+tests?\s+collected", output)
    if match is not None:
        return int(match.group(1))

    pattern = re.compile(r"^\s*(?:async\s+def|def)\s+(test_[a-zA-Z0-9_]+)\s*\(")
    count = 0
    for path in (ROOT / "tests").rglob("test_*.py"):
        source = path.read_text(encoding="utf-8")
        count += len(pattern.findall(source))
    return count


def run_locust(
    *,
    result_dir: Path,
    target_hosts: list[str],
    scenario: str,
    users: int,
    spawn_rate: float,
    run_time: str,
) -> None:
    csv_prefix = result_dir / "locust"
    html_report = result_dir / "locust_report.html"
    status_output = result_dir / "status_counts.json"
    command = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(ROOT / "loadtests" / "locustfile.py"),
        "--headless",
        "--host",
        target_hosts[0],
        "--users",
        str(users),
        "--spawn-rate",
        str(spawn_rate),
        "--run-time",
        run_time,
        "--csv",
        str(csv_prefix),
        "--html",
        str(html_report),
        "--only-summary",
    ]

    env = os.environ.copy()
    env["RATE_LIMIT_TARGET_HOSTS"] = ",".join(target_hosts)
    env["RATE_LIMIT_SCENARIO"] = scenario
    env["RATE_LIMIT_STATUS_OUTPUT"] = str(status_output)

    (result_dir / "command.txt").write_text(" ".join(command) + "\n", encoding="utf-8")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    (result_dir / "locust_stdout.log").write_text(completed.stdout, encoding="utf-8")
    (result_dir / "locust_stderr.log").write_text(completed.stderr, encoding="utf-8")

    if completed.returncode not in {0, 1}:
        raise RuntimeError(
            "Locust benchmark failed. See locust_stdout.log and "
            "locust_stderr.log in the result directory."
        )


def parse_error_report(log_path: Path) -> tuple[int, int]:
    if not log_path.exists():
        return 0, 0

    blocked_requests = 0
    error_requests = 0
    for line in log_path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*(\d+)\s+(.+?)\s*$", line)
        if match is None:
            continue
        occurrences = int(match.group(1))
        error_message = match.group(2)
        if "rate_limit_blocked" in error_message:
            blocked_requests += occurrences
        elif "Error report" not in error_message and "# occurrences" not in error_message:
            error_requests += occurrences
    return blocked_requests, error_requests


def parse_locust_console_summary(
    log_path: Path,
) -> tuple[int, int, float | None, float | None, float | None]:
    total_requests: int | None = None
    total_failures: int | None = None
    avg_latency_ms: float | None = None
    requests_per_second: float | None = None
    p95_latency_ms: float | None = None

    for line in log_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("Aggregated") and "|" in line:
            segments = [segment.strip() for segment in line.split("|")]
            request_segment = segments[0].split()
            latency_segment = segments[1].split()
            throughput_segment = segments[2].split()

            total_requests = int(request_segment[1])
            total_failures = int(request_segment[2].split("(")[0])
            avg_latency_ms = round(float(latency_segment[0]), 3)
            requests_per_second = round(float(throughput_segment[0]), 3)

        if stripped.startswith("Aggregated") and "|" not in line:
            tokens = stripped.split()
            if len(tokens) >= 13:
                p95_latency_ms = round(float(tokens[6]), 3)

    if total_requests is None or total_failures is None:
        raise ValueError(f"Could not parse final aggregate stats from {log_path}")

    return total_requests, total_failures, avg_latency_ms, p95_latency_ms, requests_per_second


def summarize_result(
    *,
    scenario: str,
    correctness_test_count: int,
    target_hosts: list[str],
    api_instances: int,
    users: int,
    spawn_rate: float,
    run_time: str,
    notes: str | None,
    result_dir: Path,
) -> BenchmarkSummary:
    (
        total_requests,
        total_failures,
        avg_latency_ms,
        p95_latency_ms,
        requests_per_second,
    ) = parse_locust_console_summary(result_dir / "locust_stderr.log")
    blocked_requests, error_requests = parse_error_report(result_dir / "locust_stderr.log")

    if blocked_requests == 0 and error_requests == 0 and total_failures > 0:
        blocked_requests = total_failures

    error_requests = max(0, total_failures - blocked_requests)
    allowed_requests = max(0, total_requests - total_failures)

    summary = BenchmarkSummary(
        scenario=scenario,
        correctness_test_count=correctness_test_count,
        target_hosts=target_hosts,
        api_instances=api_instances,
        concurrent_users=users,
        spawn_rate=spawn_rate,
        run_time=run_time,
        total_requests=total_requests,
        allowed_requests=allowed_requests,
        blocked_requests=blocked_requests,
        error_requests=error_requests,
        avg_latency_ms=avg_latency_ms,
        p95_latency_ms=p95_latency_ms,
        requests_per_second=requests_per_second,
        notes=notes,
        generated_at_utc=datetime.now(tz=UTC).isoformat(),
    )
    return summary


def write_summary(result_dir: Path, summary: BenchmarkSummary) -> None:
    summary_json = result_dir / "summary.json"
    summary_md = result_dir / "summary.md"
    payload = asdict(summary)

    summary_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    summary_md.write_text(
        "\n".join(
            [
                "# Benchmark Summary",
                "",
                f"- Scenario: `{summary.scenario}`",
                f"- Correctness tests available: `{summary.correctness_test_count}`",
                f"- Target hosts: `{', '.join(summary.target_hosts)}`",
                f"- API instances: `{summary.api_instances}`",
                f"- Concurrent users: `{summary.concurrent_users}`",
                f"- Spawn rate: `{summary.spawn_rate}` users/s",
                f"- Run time: `{summary.run_time}`",
                f"- Total requests: `{summary.total_requests}`",
                f"- Allowed requests: `{summary.allowed_requests}`",
                f"- Blocked requests: `{summary.blocked_requests}`",
                f"- Error requests: `{summary.error_requests}`",
                f"- Average latency: `{summary.avg_latency_ms}` ms",
                f"- P95 latency: `{summary.p95_latency_ms}` ms",
                f"- Requests per second: `{summary.requests_per_second}`",
                f"- Generated at: `{summary.generated_at_utc}`",
                f"- Notes: `{summary.notes or 'n/a'}`",
                "",
                "Use this report as the source of truth for resume numbers. "
                "Avoid copying values from ad-hoc terminal runs.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    target_hosts = parse_target_hosts(args.target_hosts)
    internal_scenario = normalize_scenario(args.scenario)
    scenario_label = display_scenario_name(internal_scenario)
    correctness_test_count = collect_test_count()
    result_dir = create_results_dir(Path(args.output_dir), scenario_label)

    (result_dir / "metadata.json").write_text(
        json.dumps(
            {
                "scenario": scenario_label,
                "correctness_test_count": correctness_test_count,
                "target_hosts": target_hosts,
                "api_instances": args.api_instances,
                "concurrent_users": args.users,
                "spawn_rate": args.spawn_rate,
                "run_time": args.run_time,
                "notes": args.notes,
                "prepared_policies": not args.skip_prepare,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    if not args.skip_prepare:
        prepare_benchmark_policies(target_hosts[0], args.admin_token, internal_scenario)

    run_locust(
        result_dir=result_dir,
        target_hosts=target_hosts,
        scenario=internal_scenario,
        users=args.users,
        spawn_rate=args.spawn_rate,
        run_time=args.run_time,
    )
    summary = summarize_result(
        scenario=scenario_label,
        correctness_test_count=correctness_test_count,
        target_hosts=target_hosts,
        api_instances=args.api_instances,
        users=args.users,
        spawn_rate=args.spawn_rate,
        run_time=args.run_time,
        notes=args.notes,
        result_dir=result_dir,
    )
    write_summary(result_dir, summary)

    print(f"Benchmark results written to {result_dir}")
    print(json.dumps(asdict(summary), indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Benchmark run failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
