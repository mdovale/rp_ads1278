# Client

This doc covers the current `client/` layer in `rp_ads1278`: a Python desktop GUI that connects to the Red Pitaya server, consumes the fixed `ads1278_v1` TCP protocol, plots eight live channels, exposes the three supported control commands, and optionally logs streamed samples to CSV.

## Goal

Provide a small host-side bring-up client that makes the current server stream observable and controllable without changing the wire protocol or implying lossless capture semantics that the server does not provide.

## Scope

- In scope: local desktop execution, one TCP connection to one server, capability-line validation, fixed-size binary message parsing, live plotting, enable/disable and `SYNC` and divider controls, and CSV logging for `SAMPLE` messages.
- Out of scope: protocol negotiation beyond the fixed capability check, multi-device control, offline import, derived DSP views, timing-accurate recording, and guaranteed gap-free history capture.

## User-facing behavior

Current run and test entry points are:

| Action | Entry point |
|------|------|
| Install client package | `.venv/bin/python -m pip install -e ./client` |
| Install with test deps | `.venv/bin/python -m pip install -e "./client[dev]"` |
| Run GUI from source | `.venv/bin/python client/main.py` |
| Run GUI from installed script | `.venv/bin/ads1278-client` |
| Run local fake server | `PYTHONPATH=client .venv/bin/python client/tools/fake_server.py --demo-sequence` |
| Run unit tests | `PYTHONPATH=client .venv/bin/python -m pytest client/tests -v` |

Current runtime behavior is:

- The GUI defaults to `127.0.0.1:5000` and lets the user change host and port before connecting.
- The client requires the exact capability line `RP_CAP:ads1278_v1` before it accepts binary traffic.
- After the handshake, the client decodes the fixed 60-byte little-endian server messages defined in [Server Protocol](server-protocol.md).
- The top bar shows connection state, `frame_cnt`, `msg_seq`, enable state, overflow state, and the currently reported divider.
- The main view plots `CH1` through `CH8` as eight live traces.
- `Enable`, `Disable`, `SYNC`, and `Set divider` send the documented binary commands to the server.
- `ACK` and `ERROR` update the displayed state immediately and also surface a visible status line that includes the echoed opcode and value.
- CSV logging writes rows only for `SAMPLE` messages and includes host timestamp plus server metadata and all eight channels.
- Logging stops cleanly on manual stop or disconnect.

## Architecture

The current client intentionally mirrors the same small-file structure used in the rest of the repo:

1. `client/main.py` is the source entry point and launches the Qt application.
2. `ads1278_client/main_window.py` owns the PySide6 window, connection and command widgets, logging actions, and eight `pyqtgraph` plots.
3. `ads1278_client/controller.py` owns the latest displayed state, channel history buffers, command dispatch, and logger lifecycle.
4. `ads1278_client/transport.py` owns the background socket thread, capability-line read, fixed-size message framing, and serialized command writes.
5. `ads1278_client/protocol.py` owns the exact command/message structs, incremental handshake parsing, and binary decoding helpers.
6. `ads1278_client/csv_logger.py` owns CSV file creation, header writing, row writing, flushes, and close behavior.
7. `client/tools/fake_server.py` provides a host-side fixture server for manual bring-up without a board.

The connection lifecycle is:

1. The user clicks `Connect`.
2. The controller starts a background transport worker.
3. The worker connects to the configured host and port, reads until newline, validates `RP_CAP:ads1278_v1`, and forwards any binary remainder into the message parser.
4. The worker parses fixed 60-byte messages and pushes `Ads1278Message` objects back to the controller.
5. The controller updates the latest snapshot for all message types, appends plot data only for `SAMPLE`, and logs only `SAMPLE` rows when CSV logging is active.
6. The Qt GUI polls a thread-safe controller snapshot on a timer and updates labels and plots on the main thread.
7. On disconnect or transport failure, the worker stops, the controller closes any active CSV logger, and the GUI returns to the disconnected state.

## Known risk areas

- The current server is a latest-sample streamer, so the client must not be interpreted as a lossless recorder.
- At higher acquisition rates the plotted and logged stream can skip intermediate frames even on a healthy network because the server only emits the latest coherent snapshot.
- `frame_cnt` is only 16 bits inside `status_raw`, so wraparound is normal.
- `overflow` is a sticky FPGA overlap indicator, not a TCP packet-loss count.
- `ACK` for `TRIGGER_SYNC` confirms the command write path, not a verified analog-world effect.
- Divider changes affect the FPGA timing path globally because that is the current hardware contract.

## Manual QA

- Run `PYTHONPATH=client .venv/bin/python client/tools/fake_server.py --demo-sequence`.
- Run `.venv/bin/python client/main.py` and connect to `127.0.0.1:5000`.
- Confirm the initial `SAMPLE` populates the labels and plots before acquisition is enabled.
- Confirm the demo `ACK` and `ERROR` are visible in the status line.
- Click `Enable` and confirm `frame_cnt` starts advancing.
- Click `Disable` and confirm `frame_cnt` stops advancing.
- Click `SYNC` and confirm an `ACK` is shown.
- Set divider `625` and confirm the displayed divider updates.
- Set divider `2` and confirm an `ERROR` is shown.
- Start CSV logging, re-enable streaming, and confirm the file contains only `SAMPLE` rows with negative values preserved.

## Key files

| Area | File |
|------|------|
| Packaging and dependencies | `client/pyproject.toml` |
| Source entry point | `client/main.py` |
| Package exports | `client/ads1278_client/__init__.py` |
| Message model | `client/ads1278_client/models.py` |
| Wire protocol helpers | `client/ads1278_client/protocol.py` |
| Background transport | `client/ads1278_client/transport.py` |
| State and command controller | `client/ads1278_client/controller.py` |
| CSV logging | `client/ads1278_client/csv_logger.py` |
| Qt GUI and plots | `client/ads1278_client/main_window.py` |
| Fake bring-up server | `client/tools/fake_server.py` |
| Protocol tests | `client/tests/test_protocol.py` |
| CSV logger tests | `client/tests/test_csv_logger.py` |
| Transport test | `client/tests/test_transport.py` |

## Related docs

- [README](../../README.md)
- [Server](server.md)
- [Server Protocol](server-protocol.md)
- [Server MMIO Contract](server-mmio-contract.md)
- [Client implementation handoff](../handoffs/20260407_python-client-implementation.md)
