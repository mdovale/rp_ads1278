import csv

import pytest

from ads1278_client.csv_logger import SampleCsvLogger
from ads1278_client.models import MessageType
from ads1278_client.protocol import build_message, parse_message


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
