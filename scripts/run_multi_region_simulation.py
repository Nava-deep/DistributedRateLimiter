from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from app.services.multi_region import simulate_multi_region_limit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_DIR = ROOT / "benchmark_results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulate India and US rate-limit replicas under replication lag.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Global limit shared by both regions.",
    )
    parser.add_argument(
        "--replication-lag-ms",
        type=int,
        default=180,
        help="One-way replication lag between India and US regions.",
    )
    parser.add_argument("--india-requests", type=int, default=8, help="Requests sent in India.")
    parser.add_argument("--us-requests", type=int, default=8, help="Requests sent in US.")
    parser.add_argument(
        "--request-spacing-ms",
        type=int,
        default=20,
        help="Spacing between requests in the same region.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_RESULTS_DIR),
        help="Directory where the simulation summary will be written.",
    )
    return parser.parse_args()


def create_results_dir(root: Path) -> Path:
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    result_dir = root / f"{timestamp}_multi_region_consistency"
    result_dir.mkdir(parents=True, exist_ok=False)
    return result_dir


def render_markdown(summary: dict[str, int]) -> str:
    return "\n".join(
        [
            "# Multi-Region Consistency Simulation",
            "",
            "This run simulates two regional replicas, one in India and one in the US,",
            "making local allow/block decisions before asynchronous replication arrives.",
            "",
            "| Field | Value |",
            "| --- | ---: |",
            f"| Configured limit | {summary['configured_limit']} |",
            f"| Replication lag (ms) | {summary['replication_lag_ms']} |",
            f"| India requests sent | {summary['india_requests_sent']} |",
            f"| US requests sent | {summary['us_requests_sent']} |",
            f"| India allowed | {summary['india_allowed']} |",
            f"| US allowed | {summary['us_allowed']} |",
            f"| Total allowed | {summary['total_allowed']} |",
            f"| Oversubscription | {summary['oversubscription']} |",
            f"| Stale allowed decisions | {summary['stale_allowed_decisions']} |",
            "",
            "Oversubscription and stale decisions are the consistency cost of active-active",
            "regional replicas with replication lag. The main service avoids this problem by",
            "sending rate-limit decisions to one shared Redis coordination layer.",
            "",
        ]
    )


def main() -> None:
    args = parse_args()
    summary, decisions = simulate_multi_region_limit(
        configured_limit=args.limit,
        replication_lag_ms=args.replication_lag_ms,
        india_requests=args.india_requests,
        us_requests=args.us_requests,
        request_spacing_ms=args.request_spacing_ms,
    )

    root = Path(args.output_dir)
    result_dir = create_results_dir(root)

    summary_payload = summary.as_dict() | {
        "generated_at_utc": datetime.now(tz=UTC).isoformat(),
        "regions": ["india", "us"],
    }
    decisions_payload = [asdict(decision) for decision in decisions]

    (result_dir / "summary.json").write_text(
        json.dumps(summary_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    (result_dir / "decisions.json").write_text(
        json.dumps(decisions_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    (result_dir / "summary.md").write_text(
        render_markdown(summary_payload),
        encoding="utf-8",
    )

    print(json.dumps({"result_dir": str(result_dir), **summary_payload}, indent=2))


if __name__ == "__main__":
    main()
