from __future__ import annotations

from typing import Iterable
import numpy as np


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return float(max(lo, min(hi, x)))


def safe_mean(xs: Iterable[float], default: float = 0.0) -> float:
    vals = list(xs)
    return float(np.mean(vals)) if vals else float(default)


def safe_std(xs: Iterable[float], default: float = 0.0) -> float:
    vals = list(xs)
    return float(np.std(vals)) if vals else float(default)


def piecewise_linear(x: float, points: list[tuple[float, float]]) -> float:
    points = sorted(points)
    if x <= points[0][0]:
        return float(points[0][1])
    if x >= points[-1][0]:
        return float(points[-1][1])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return float(y1)
            t = (x - x0) / (x1 - x0)
            return float(y0 + t * (y1 - y0))
    return float(points[-1][1])


def json_normalize(value):
    """Recursively convert NumPy/scalar/array/tuple values to JSON-safe Python values."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return [json_normalize(v) for v in value.tolist()]
    if isinstance(value, dict):
        return {str(k): json_normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_normalize(v) for v in value]
    raise TypeError(f"Unsupported JSON value type: {type(value).__name__}")
