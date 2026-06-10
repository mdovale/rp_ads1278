from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


MIN_ASD_SAMPLE_COUNT = 256


class SpectrumUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class AsdSpectrum:
    frequencies_hz: np.ndarray
    asd: np.ndarray
    sample_count: int


def speckit_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__)).resolve()
    for candidate in (current, *current.parents):
        for relative in (
            Path("reference") / "speckit-1.0.2",
            Path(".reference") / "speckit-1.0.2",
        ):
            root = candidate / relative
            if (root / "speckit").is_dir():
                return root
    raise SpectrumUnavailableError("Could not find reference/speckit-1.0.2")


def ensure_speckit_path() -> Path:
    root = speckit_root()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    return root


def _load_compute_spectrum() -> Any:
    try:
        ensure_speckit_path()
        from speckit import compute_spectrum
    except Exception as exc:  # pragma: no cover - exact import failure depends on env
        raise SpectrumUnavailableError(
            "SpecKit is unavailable. Install spectrum dependencies with "
            '`python -m pip install -e "./client[spectrum]"`.'
        ) from exc
    return compute_spectrum


def compute_asd(
    samples_v: np.ndarray,
    *,
    fs_hz: float,
    fast: bool = False,
) -> AsdSpectrum:
    samples = np.asarray(samples_v, dtype=np.float64)
    samples = samples[np.isfinite(samples)]
    if samples.size < MIN_ASD_SAMPLE_COUNT:
        raise ValueError(f"need at least {MIN_ASD_SAMPLE_COUNT} samples for ASD")
    if fs_hz <= 0.0:
        raise ValueError("sample rate must be positive")

    compute_spectrum = _load_compute_spectrum()
    kwargs = {
        "Jdes": 200 if fast else 900,
        "Kdes": 40 if fast else 100,
        "order": 0,
        "win": "Kaiser",
        "psll": 200,
        "verbose": False,
    }
    result = compute_spectrum(samples, fs=fs_hz, **kwargs)
    frequencies = np.asarray(result.f, dtype=np.float64)
    asd = np.asarray(result.asd, dtype=np.float64)
    finite = np.isfinite(frequencies) & np.isfinite(asd) & (frequencies > 0.0) & (asd > 0.0)
    return AsdSpectrum(
        frequencies_hz=frequencies[finite],
        asd=asd[finite],
        sample_count=int(samples.size),
    )
