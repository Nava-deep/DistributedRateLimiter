from __future__ import annotations

import random

from locust import HttpUser, between, task


class RateLimiterUser(HttpUser):
    wait_time = between(0.01, 0.25)

    def on_start(self) -> None:
        self.user_id = random.choice(["alice", "bob", "vip-user", "charlie"])
        self.client.headers.update(
            {
                "X-Tenant-Id": random.choice(["tenant-a", "tenant-b"]),
                "X-Forwarded-For": f"203.0.113.{random.randint(1, 200)}",
            }
        )

    @task(2)
    def public_endpoint(self) -> None:
        self.client.get("/demo/public", name="/demo/public")

    @task(4)
    def protected_endpoint(self) -> None:
        self.client.get("/demo/protected", name="/demo/protected")

    @task(4)
    def user_endpoint(self) -> None:
        self.client.get(f"/demo/user/{self.user_id}", name="/demo/user/{user_id}")

