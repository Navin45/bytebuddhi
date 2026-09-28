"""Client-side sequence tracking. Gaps are never skipped."""

from __future__ import annotations


class SequenceGap(Exception):
    def __init__(self, expected: int, received: int) -> None:
        super().__init__(f"Missing event sequence {expected}; received {received}")
        self.expected = expected
        self.received = received


class SequenceTracker:
    """`after_sequence` means strictly greater than the last applied sequence."""

    def __init__(self, last_sequence: int = 0) -> None:
        if last_sequence < 0:
            raise ValueError("last_sequence must be >= 0")
        self.last_sequence = last_sequence

    def observe(self, sequence: int) -> str:
        if sequence <= 0:
            raise ValueError("sequence must be >= 1")
        if sequence <= self.last_sequence:
            return "duplicate"
        expected = self.last_sequence + 1
        if sequence != expected:
            raise SequenceGap(expected, sequence)
        self.last_sequence = sequence
        return "applied"
