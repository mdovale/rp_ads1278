import csv

import pytest

from ads1278_client.csv_logger import SampleCsvLogger
from ads1278_client.models import MessageType
from ads1278_client.protocol import build_message, parse_message


def _sample_message(
    *,
    msg_seq: int,
    frame_cnt: int,
    ctrl_raw: int = 0x00000006,
    extclk_div: int = 1,
    mod_div: int = 5120,
    ch1: int = 1,
    ch8: int = -8,
):
    return parse_message(
        build_message(
            MessageType.SAMPLE,
            msg_seq,
            0,
            0,
            ((frame_cnt & 0xFFFF) << 16) | 0x1,
            ctrl_raw,
            extclk_div,
            mod_div,
            [ch1, -2, 3, -4, 5, -6, 7, ch8],
        )
    )


def test_csv_logger_writes_header_and_sample_row(tmp_path) -> None:
    message = parse_message(
        build_message(
            MessageType.SAMPLE,
            77,
            0,
            0,
            0x00110001,
            0x00000002,
            625,
            6_250_000,
            [1, -2, 3, -4, 5, -6, 7, -8],
        )
    )
    path = tmp_path / "samples.csv"

    logger = SampleCsvLogger(path)
    logger.write_sample(message)
    logger.close()

    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == SampleCsvLogger.HEADER
    assert rows[1][1:7] == ["77", "17", "1114113", "2", "625", "6250000"]
    assert rows[1][7:] == ["1", "-2", "3", "-4", "5", "-6", "7", "-8"]


def test_csv_logger_writes_selected_channels_only(tmp_path) -> None:
    message = parse_message(
        build_message(
            MessageType.SAMPLE,
            77,
            0,
            0,
            0x00110001,
            0x00000002,
            625,
            6_250_000,
            [1, -2, 3, -4, 5, -6, 7, -8],
        )
    )
    path = tmp_path / "subset.csv"

    logger = SampleCsvLogger(path, channel_indices=(0, 2, 7))
    logger.write_sample(message)
    logger.close()

    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == SampleCsvLogger.METADATA_HEADER + ["ch1", "ch3", "ch8"]
    assert rows[1][7:] == ["1", "3", "-8"]


def test_csv_logger_rejects_empty_channel_selection(tmp_path) -> None:
    with pytest.raises(ValueError, match="at least one channel"):
        SampleCsvLogger(tmp_path / "empty.csv", channel_indices=())


def test_csv_logger_rejects_demod_rate_without_ch1_only(tmp_path) -> None:
    with pytest.raises(ValueError, match="CH1 only"):
        SampleCsvLogger(
            tmp_path / "bad_demod.csv",
            channel_indices=(0, 7),
            demod_rate=True,
        )


def test_csv_logger_demod_rate_skips_duplicate_ch1_frames(tmp_path) -> None:
    path = tmp_path / "demod.csv"

    logger = SampleCsvLogger(path, channel_indices=(0,), demod_rate=True)
    for frame_cnt in range(1, 12):
        logger.write_sample(_sample_message(msg_seq=frame_cnt, frame_cnt=frame_cnt, ch1=1234))
    logger.write_sample(_sample_message(msg_seq=12, frame_cnt=11, ch1=1235))
    logger.close()

    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert [row[1] for row in rows[1:]] == ["1", "11"]


def test_csv_logger_demod_rate_writes_changed_ch1(tmp_path) -> None:
    path = tmp_path / "demod_changed.csv"

    logger = SampleCsvLogger(path, channel_indices=(0,), demod_rate=True)
    logger.write_sample(_sample_message(msg_seq=1, frame_cnt=1, ch1=1234))
    logger.write_sample(_sample_message(msg_seq=2, frame_cnt=2, ch1=1235))
    logger.close()

    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert [row[1] for row in rows[1:]] == ["1", "2"]


def test_csv_logger_demod_rate_falls_back_to_full_rate_without_demod_ctrl(tmp_path) -> None:
    path = tmp_path / "demod_full_rate.csv"

    logger = SampleCsvLogger(path, channel_indices=(0,), demod_rate=True)
    for frame_cnt in range(1, 4):
        logger.write_sample(
            _sample_message(
                msg_seq=frame_cnt,
                frame_cnt=frame_cnt,
                ctrl_raw=0x00000002,
                ch1=1234,
            )
        )
    logger.close()

    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))

    assert [row[1] for row in rows[1:]] == ["1", "2", "3"]


def test_csv_logger_rejects_non_sample_messages(tmp_path) -> None:
    message = parse_message(
        build_message(
            MessageType.ACK,
            10,
            1,
            1,
            0,
            0,
            625,
            6_250_000,
            [0, 0, 0, 0, 0, 0, 0, 0],
        )
    )
    logger = SampleCsvLogger(tmp_path / "ack.csv")
    with pytest.raises(ValueError):
        logger.write_sample(message)
    logger.close()
