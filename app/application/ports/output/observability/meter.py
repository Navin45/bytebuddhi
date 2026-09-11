"""Application ports for metrics recording."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Counter(Protocol):
    """Monotonically increasing cumulative metric counter."""

    def add(self, amount: int | float, attributes: dict[str, Any] | None = None) -> None:
        """Add non-negative value to the counter."""
        ...


@runtime_checkable
class UpDownCounter(Protocol):
    """Metric counter that can increase or decrease (e.g. active child agents)."""

    def add(self, amount: int | float, attributes: dict[str, Any] | None = None) -> None:
        """Add value (positive or negative) to the counter."""
        ...


@runtime_checkable
class Histogram(Protocol):
    """Metric recording value distributions (e.g. duration, token usage)."""

    def record(self, amount: int | float, attributes: dict[str, Any] | None = None) -> None:
        """Record an observed value."""
        ...


@runtime_checkable
class Meter(Protocol):
    """Application port for creating metric instruments."""

    def create_counter(self, name: str, unit: str = "", description: str = "") -> Counter:
        """Create a new cumulative Counter instrument."""
        ...

    def create_up_down_counter(self, name: str, unit: str = "", description: str = "") -> UpDownCounter:
        """Create a new UpDownCounter instrument."""
        ...

    def create_histogram(self, name: str, unit: str = "", description: str = "") -> Histogram:
        """Create a new Histogram instrument."""
        ...
