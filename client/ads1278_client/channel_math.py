from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np

from .protocol import CHANNEL_COUNT


@dataclass(frozen=True)
class MathTrace:
    enabled: bool
    terms: tuple[tuple[int, int], ...]

    def label(self) -> str:
        if not self.terms:
            return "Math"
        parts: list[str] = []
        for channel_idx, sign in self.terms:
            token = f"CH{channel_idx + 1}"
            if not parts:
                parts.append(f"-{token}" if sign < 0 else token)
            else:
                parts.append(f"-{token}" if sign < 0 else f"+{token}")
        return "".join(parts)

    def term_count(self) -> int:
        return len(self.terms)


def validate_terms(terms: Sequence[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    if not terms:
        raise ValueError("at least one term is required")
    normalized: list[tuple[int, int]] = []
    for channel_idx, sign in terms:
        idx = int(channel_idx)
        coeff = int(sign)
        if idx < 0 or idx >= CHANNEL_COUNT:
            raise ValueError(f"channel index out of range: {idx}")
        if coeff not in (-1, 1):
            raise ValueError("term sign must be +1 or -1")
        normalized.append((idx, coeff))
    return tuple(normalized)


def compute_trace(
    trace: MathTrace,
    channel_history: Sequence[np.ndarray],
) -> np.ndarray:
    if not trace.terms:
        return np.asarray([], dtype=np.float64)

    lengths = [
        channel_history[channel_idx].size
        for channel_idx, _ in trace.terms
        if channel_history[channel_idx].size > 0
    ]
    if not lengths:
        return np.asarray([], dtype=np.float64)

    length = min(lengths)
    result = np.zeros(length, dtype=np.float64)
    for channel_idx, sign in trace.terms:
        history = channel_history[channel_idx]
        if history.size == 0:
            continue
        result += history[-length:].astype(np.float64) * float(sign)
    return result


def math_traces_to_json(traces: Sequence[MathTrace]) -> str:
    payload = [
        {
            "enabled": trace.enabled,
            "terms": [[channel_idx, sign] for channel_idx, sign in trace.terms],
        }
        for trace in traces
    ]
    return json.dumps(payload)


def math_traces_from_json(raw: str) -> list[MathTrace]:
    if not raw.strip():
        return []
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("math traces must be a JSON list")

    traces: list[MathTrace] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("math trace entry must be an object")
        enabled = bool(item.get("enabled", True))
        terms_raw = item.get("terms", [])
        if not isinstance(terms_raw, list):
            raise ValueError("math trace terms must be a list")
        terms = validate_terms(
            [(int(entry[0]), int(entry[1])) for entry in terms_raw]
        )
        traces.append(MathTrace(enabled=enabled, terms=terms))
    return traces


def load_math_traces_from_settings(
    settings_value: Any,
    *,
    default: Iterable[MathTrace] = (),
) -> list[MathTrace]:
    if settings_value in (None, ""):
        return list(default)
    if isinstance(settings_value, str):
        try:
            return math_traces_from_json(settings_value)
        except (json.JSONDecodeError, ValueError, TypeError, IndexError):
            return list(default)
    return list(default)
