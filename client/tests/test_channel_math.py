import json

import numpy as np
import pytest

from ads1278_client.channel_math import (
    MathTrace,
    compute_trace,
    load_math_traces_from_settings,
    math_traces_from_json,
    math_traces_to_json,
    validate_terms,
)


def test_math_trace_label_formats_sum_and_difference() -> None:
    assert MathTrace(enabled=True, terms=((0, 1), (1, 1))).label() == "CH1+CH2"
    assert MathTrace(enabled=True, terms=((0, 1), (2, -1))).label() == "CH1-CH3"
    assert MathTrace(enabled=True, terms=((1, -1),)).label() == "-CH2"


def test_compute_trace_sums_and_subtracts_channel_histories() -> None:
    trace = MathTrace(enabled=True, terms=((0, 1), (1, 1), (2, -1)))
    histories = [
        np.asarray([10, 20], dtype=np.int32),
        np.asarray([1, 2], dtype=np.int32),
        np.asarray([4, 8], dtype=np.int32),
        *[np.asarray([], dtype=np.int32) for _ in range(5)],
    ]

    result = compute_trace(trace, histories)

    assert np.allclose(result, [7.0, 14.0])


def test_compute_trace_uses_common_tail_when_lengths_differ() -> None:
    trace = MathTrace(enabled=True, terms=((0, 1), (1, 1)))
    histories = [
        np.asarray([1, 2, 3], dtype=np.int32),
        np.asarray([10, 20], dtype=np.int32),
        *[np.asarray([], dtype=np.int32) for _ in range(6)],
    ]

    result = compute_trace(trace, histories)

    assert np.allclose(result, [12.0, 23.0])


def test_validate_terms_rejects_invalid_channel_or_sign() -> None:
    with pytest.raises(ValueError, match="at least one term"):
        validate_terms([])

    with pytest.raises(ValueError, match="out of range"):
        validate_terms([(8, 1)])

    with pytest.raises(ValueError, match="sign must"):
        validate_terms([(0, 2)])


def test_math_trace_json_round_trip() -> None:
    traces = [
        MathTrace(enabled=True, terms=((0, 1), (1, 1))),
        MathTrace(enabled=False, terms=((2, 1), (3, -1))),
    ]

    restored = math_traces_from_json(math_traces_to_json(traces))

    assert restored == traces


def test_load_math_traces_from_settings_falls_back_on_invalid_json() -> None:
    default = [MathTrace(enabled=True, terms=((0, 1),))]
    assert load_math_traces_from_settings("", default=default) == default
    assert load_math_traces_from_settings("{bad", default=default) == default
    assert load_math_traces_from_settings(
        json.dumps([{"enabled": True, "terms": [[0, 1], [1, -1]]}])
    ) == [MathTrace(enabled=True, terms=((0, 1), (1, -1)))]
