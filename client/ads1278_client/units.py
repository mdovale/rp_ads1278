from __future__ import annotations

import numpy as np

ADS1278_CODE_SCALE = 1 << 23
DEFAULT_ADC_REFERENCE_VOLTS = 2.5
RP_ADC_CLOCK_HZ = 125_000_000.0
ADS1278_CLOCKS_PER_SAMPLE = 512.0
FRAME_COUNTER_MODULUS = 1 << 16


def raw_codes_to_volts(
    samples: np.ndarray,
    reference_volts: float = DEFAULT_ADC_REFERENCE_VOLTS,
) -> np.ndarray:
    return np.asarray(samples, dtype=np.float64) * (reference_volts / ADS1278_CODE_SCALE)


def sample_period_seconds(extclk_div: int) -> float:
    if extclk_div <= 0:
        raise ValueError("EXTCLK divider must be positive")
    extclk_hz = RP_ADC_CLOCK_HZ / (2.0 * extclk_div)
    return ADS1278_CLOCKS_PER_SAMPLE / extclk_hz


def sample_rate_hz(extclk_div: int) -> float:
    return 1.0 / sample_period_seconds(extclk_div)


def frames_per_demod(extclk_div: int, mod_div: int) -> int:
    if extclk_div <= 0 or mod_div < 2:
        return 1
    denominator = int(extclk_div) * int(ADS1278_CLOCKS_PER_SAMPLE)
    return max(1, (int(mod_div) + (denominator // 2)) // denominator)


def frame_counts_to_relative_seconds(
    frame_counts: np.ndarray,
    extclk_div: int,
) -> np.ndarray:
    counts = np.asarray(frame_counts, dtype=np.int64)
    if counts.size == 0:
        return np.asarray([], dtype=np.float64)

    unwrapped = counts.copy()
    offset = 0
    previous = int(counts[0])
    unwrapped[0] = previous
    half_range = FRAME_COUNTER_MODULUS // 2

    for index in range(1, counts.size):
        raw_count = int(counts[index])
        candidate = raw_count + offset
        if candidate < previous - half_range:
            offset += FRAME_COUNTER_MODULUS
            candidate = raw_count + offset
        elif candidate > previous + half_range:
            offset -= FRAME_COUNTER_MODULUS
            candidate = raw_count + offset
        unwrapped[index] = candidate
        previous = candidate

    return (unwrapped - unwrapped[-1]) * sample_period_seconds(extclk_div)


def sample_indices_to_relative_seconds(sample_count: int, extclk_div: int) -> np.ndarray:
    if sample_count <= 0:
        return np.asarray([], dtype=np.float64)
    indices = np.arange(sample_count, dtype=np.float64)
    return (indices - indices[-1]) * sample_period_seconds(extclk_div)
