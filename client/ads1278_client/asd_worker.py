from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .spectrum import AsdSpectrum, compute_asd
from .units import raw_codes_to_volts


@dataclass(frozen=True)
class AsdTraceRequest:
    channel_index: int
    label: str
    samples_codes: np.ndarray


@dataclass(frozen=True)
class AsdTraceResult:
    channel_index: int
    label: str
    spectrum: AsdSpectrum


@dataclass(frozen=True)
class AsdComputation:
    revision: int
    results: tuple[AsdTraceResult, ...]
    sample_count: int
    duration_s: float
    compute_ms: float
    error: str = ""


def compute_asd_traces(
    *,
    revision: int,
    traces: Sequence[AsdTraceRequest],
    fs_hz: float,
    reference_volts: float,
) -> AsdComputation:
    started = time.perf_counter()
    results: list[AsdTraceResult] = []
    sample_count = min((trace.samples_codes.size for trace in traces), default=0)
    try:
        for trace in traces:
            samples_v = raw_codes_to_volts(trace.samples_codes, reference_volts)
            spectrum = compute_asd(
                samples_v,
                fs_hz=fs_hz,
                fast=trace.samples_codes.size < 8192,
            )
            results.append(
                AsdTraceResult(
                    channel_index=trace.channel_index,
                    label=trace.label,
                    spectrum=spectrum,
                )
            )
    except Exception as exc:
        return AsdComputation(
            revision=revision,
            results=(),
            sample_count=int(sample_count),
            duration_s=float(sample_count / fs_hz) if fs_hz > 0 else 0.0,
            compute_ms=(time.perf_counter() - started) * 1000.0,
            error=str(exc),
        )

    return AsdComputation(
        revision=revision,
        results=tuple(results),
        sample_count=int(sample_count),
        duration_s=float(sample_count / fs_hz) if fs_hz > 0 else 0.0,
        compute_ms=(time.perf_counter() - started) * 1000.0,
    )
