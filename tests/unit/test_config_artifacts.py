from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_prometheus_config_scrapes_both_api_instances() -> None:
    config_path = ROOT / "prometheus" / "prometheus.yml"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    targets = payload["scrape_configs"][0]["static_configs"][0]["targets"]

    assert "api1:8000" in targets
    assert "api2:8000" in targets


@pytest.mark.unit
def test_grafana_datasource_points_to_prometheus_service() -> None:
    datasource_path = ROOT / "grafana" / "provisioning" / "datasources" / "prometheus.yml"
    payload = yaml.safe_load(datasource_path.read_text(encoding="utf-8"))

    datasource = payload["datasources"][0]
    assert datasource["uid"] == "prometheus"
    assert datasource["url"] == "http://prometheus:9090"


@pytest.mark.unit
def test_grafana_dashboard_json_contains_expected_panels() -> None:
    dashboard_path = ROOT / "grafana" / "dashboards" / "distributed-rate-limiter.json"
    payload = json.loads(dashboard_path.read_text(encoding="utf-8"))

    panel_titles = {panel["title"] for panel in payload["panels"]}

    assert {
        "Traffic And Decisions",
        "Failure Indicators",
        "Latency",
        "Cache And Retry Signals",
    }.issubset(panel_titles)


@pytest.mark.unit
def test_sample_benchmark_artifacts_are_consistent() -> None:
    sample_dir = ROOT / "benchmark_results" / "sample_multi_instance_benchmark"
    summary = json.loads((sample_dir / "summary.json").read_text(encoding="utf-8"))
    metadata = json.loads((sample_dir / "metadata.json").read_text(encoding="utf-8"))
    markdown = (sample_dir / "summary.md").read_text(encoding="utf-8")

    assert summary["api_instances"] == metadata["api_instances"]
    assert summary["target_hosts"] == metadata["target_hosts"]
    assert summary["correctness_test_count"] > 0
    assert "synthetic benchmark" in markdown.lower()


@pytest.mark.unit
def test_ci_workflow_runs_lint_and_tests() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "ci.yml"
    payload = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = payload["jobs"]["test"]["steps"]
    run_commands = "\n".join(step.get("run", "") for step in steps)

    assert "ruff check ." in run_commands
    assert "pytest -q" in run_commands


@pytest.mark.unit
def test_docker_compose_config_smoke_passes() -> None:
    env_path = ROOT / ".env"
    env_path.write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    try:
        command = ["docker", "compose", "--env-file", ".env.example", "config"]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
    finally:
        env_path.unlink(missing_ok=True)

    assert completed.returncode == 0, completed.stderr
    assert "grafana:" in completed.stdout
    assert "prometheus:" in completed.stdout
    assert "api1:" in completed.stdout
