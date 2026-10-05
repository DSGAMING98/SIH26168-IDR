"""Causal signal conditioning primitives suitable for a live phone pipeline."""

from __future__ import annotations

import numpy as np


class CausalLowPassFilter:
    """First-order causal IIR with an exact continuous-time RC discretization."""

    def __init__(self, cutoff_hz: float, dimensions: int) -> None:
        if not np.isfinite(cutoff_hz) or cutoff_hz <= 0:
            raise ValueError("Low-pass cutoff must be finite and positive.")
        if dimensions <= 0:
            raise ValueError("Filter dimensions must be positive.")
        self.cutoff_hz = float(cutoff_hz)
        self.dimensions = int(dimensions)
        self._state: np.ndarray | None = None

    def update(self, value: np.ndarray, dt_s: float) -> np.ndarray:
        sample = np.asarray(value, dtype=float)
        if sample.shape != (self.dimensions,) or not np.all(np.isfinite(sample)):
            raise ValueError("Filter sample has invalid shape or values.")
        if not np.isfinite(dt_s) or dt_s <= 0:
            raise ValueError("Filter dt must be finite and positive.")
        if self._state is None:
            self._state = sample.copy()
        else:
            alpha = 1.0 - np.exp(-2.0 * np.pi * self.cutoff_hz * dt_s)
            self._state = self._state + alpha * (sample - self._state)
        return self._state.copy()


def causal_low_pass(values: np.ndarray, dt_s: np.ndarray, cutoff_hz: float) -> np.ndarray:
    """Convenience batch wrapper that still processes strictly left-to-right."""

    samples = np.asarray(values, dtype=float)
    delta = np.asarray(dt_s, dtype=float)
    if samples.ndim != 2 or delta.shape != (len(samples),):
        raise ValueError("Values must be (n, d) and dt must be (n,).")
    filter_ = CausalLowPassFilter(cutoff_hz, samples.shape[1])
    return np.vstack([filter_.update(sample, dt) for sample, dt in zip(samples, delta, strict=True)])
