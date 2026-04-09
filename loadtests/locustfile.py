from __future__ import annotations

import json
import os
import random
import threading
from collections import Counter
from pathlib import Path

from locust import HttpUser, between, events, task

TARGET_HOSTS = tuple(
    host.strip()
    for host in os.getenv("RATE_LIMIT_TARGET_HOSTS", "").split(",")
    if host.strip()
)
SCENARIO = os.getenv("RATE_LIMIT_SCENARIO", "mixed").strip().lower()
STATUS_OUTPUT_PATH = os.getenv("RATE_LIMIT_STATUS_OUTPUT")

_status_counts: Counter[str] = Counter()
_status_lock = threading.Lock()


def _record_status(status_code: int | str) -> None:
    with _status_lock:
        _status_counts[str(status_code)] += 1


def _selected_base_url(default_host: str) -> str:
    if TARGET_HOSTS:
        return random.choice(TARGET_HOSTS)
    return default_host.rstrip("/")


def _write_status_counts() -> None:
    if not STATUS_OUTPUT_PATH:
        return

    output_path = Path(STATUS_OUTPUT_PATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "scenario": SCENARIO,
                "status_counts": dict(sorted(_status_counts.items())),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


@events.quitting.add_listener
def on_quitting(environment, **kwargs) -> None:
    _write_status_counts()


class RateLimiterUser(HttpUser):
    wait_time = between(0.01, 0.10)

    def on_start(self) -> None:
        self.user_id = random.choice(["alice", "bob", "vip-user", "charlie"])
        self.tenant_id = random.choice(["tenant-a", "tenant-b"])
        self.forwarded_for = f"203.0.113.{random.randint(1, 200)}"

    def _headers(self) -> dict[str, str]:
        return {
            "X-Tenant-Id": self.tenant_id,
            "X-Forwarded-For": self.forwarded_for,
        }

    def _request(self, path: str, *, name: str) -> None:
        url = f"{_selected_base_url(self.host)}{path}"
        try:
            with self.client.get(
                url,
                headers=self._headers(),
                name=name,
                catch_response=True,
            ) as response:
                _record_status(response.status_code)
                if response.status_code == 429:
                    response.failure("rate_limit_blocked")
                elif response.status_code >= 500:
                    response.failure(f"unexpected server error {response.status_code}")
                else:
                    response.success()
        except Exception:
            _record_status("EXCEPTION")
            raise

    @task(2)
    def public_endpoint(self) -> None:
        if SCENARIO not in {"mixed", "public-heavy"}:
            return
        self._request("/demo/public", name="/demo/public")

    @task(4)
    def protected_endpoint(self) -> None:
        if SCENARIO not in {"mixed", "protected-burst", "shared-protected"}:
            return
        self._request("/demo/protected", name="/demo/protected")

    @task(4)
    def user_endpoint(self) -> None:
        if SCENARIO not in {"mixed", "user-hotspot"}:
            return
        self._request(f"/demo/user/{self.user_id}", name="/demo/user/{user_id}")

    @task(3)
    def ip_hotspot_endpoint(self) -> None:
        if SCENARIO != "ip-hotspot":
            return
        self.forwarded_for = "203.0.113.10"
        self._request("/demo/protected", name="/demo/protected[ip-hotspot]")

    @task(3)
    def protected_burst_endpoint(self) -> None:
        if SCENARIO not in {"protected-burst", "shared-protected"}:
            return
        self._request("/demo/protected", name="/demo/protected[burst]")
