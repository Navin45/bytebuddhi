"""Run-execution counters on the existing meter port."""

from __future__ import annotations

from app.application.ports.output.observability.meter import Meter


class RunMetrics:
    def __init__(self, meter: Meter | None = None) -> None:
        self._counters = {}
        if meter is None:
            return
        names = (
            "run_claims",
            "run_claim_conflicts",
            "lease_renewals",
            "lease_expirations",
            "stale_runs",
            "recovered_runs",
            "worker_crashes",
            "admission_rejections",
            "admission_acquires",
            "admission_releases",
            "redis_unavailable",
            "postgres_errors",
            "active_runs",
            "queued_runs",
        )
        for name in names:
            self._counters[name] = meter.create_counter(
                f"bytebuddhi.{name}",
                description=name.replace("_", " "),
            )

    def add(self, name: str, amount: int = 1) -> None:
        counter = self._counters.get(name)
        if counter is not None:
            counter.add(amount)
