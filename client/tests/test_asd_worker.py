from __future__ import annotations

import numpy as np

from ads1278_client.asd_worker import AsdTraceRequest, compute_asd_traces
from ads1278_client.spectrum import AsdSpectrum


def test_compute_asd_traces_converts_codes_to_volts(monkeypatch) -> None:
    captured = {}

    def fake_compute_asd(samples_v, *, fs_hz, fast):
        captured["samples_v"] = samples_v
        captured["fs_hz"] = fs_hz
        captured["fast"] = fast
        return AsdSpectrum(
            frequencies_hz=np.asarray([1.0, 2.0]),
            asd=np.asarray([3.0, 4.0]),
            sample_count=samples_v.size,
        )

    monkeypatch.setattr("ads1278_client.asd_worker.compute_asd", fake_compute_asd)

    result = compute_asd_traces(
        revision=3,
        traces=[
            AsdTraceRequest(
                channel_index=0,
                label="CH1",
                samples_codes=np.asarray([0, 1 << 22], dtype=np.int32),
            )
        ],
        fs_hz=1000.0,
        reference_volts=2.5,
    )

    assert result.error == ""
    assert result.revision == 3
    assert result.results[0].label == "CH1"
    assert np.allclose(captured["samples_v"], [0.0, 1.25])
    assert captured["fs_hz"] == 1000.0
    assert captured["fast"] is True
