"""Small platform-neutral causal buffer used by replay-side tests and tools."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TimedValue:
    timestamp_ns: int
    value: Any


class CausalLatestBuffer:
    """Keep latest values while rejecting duplicates and out-of-order input."""

    def __init__(self, capacity_per_stream: int = 256) -> None:
        if capacity_per_stream < 2:
            raise ValueError("capacity_per_stream must be at least two")
        self._capacity = capacity_per_stream
        self._values: dict[str, deque[TimedValue]] = defaultdict(deque)

    def add(self, stream: str, timestamp_ns: int, value: Any) -> None:
        queue = self._values[stream]
        if queue and timestamp_ns <= queue[-1].timestamp_ns:
            raise ValueError(f"Out-of-order sample for {stream}")
        queue.append(TimedValue(int(timestamp_ns), value))
        while len(queue) > self._capacity:
            queue.popleft()

    def latest_at_or_before(self, stream: str, timestamp_ns: int) -> TimedValue | None:
        return next(
            (item for item in reversed(self._values.get(stream, ())) if item.timestamp_ns <= timestamp_ns),
            None,
        )
