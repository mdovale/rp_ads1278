# Client

This doc covers the current `client/` layer in `rp_ads1278`: a Python desktop GUI that connects to the Red Pitaya server, consumes the `ads1278_v3` TCP protocol, plots eight live channels, exposes acquisition and modulation controls, and optionally logs streamed samples to CSV.

## Goal

Provide a small host-side bring-up client that makes the current server stream observable and controllable while accepting both legacy single-sample messages and DMA bulk batches, with CSV logging either on the host computer or on a USB stick mounted by the Red Pitaya server.

## Scope

- In scope: local desktop execution, one TCP connection to one server, capability-line validation, binary message parsing, bulk sample expansion, live plotting, optional live ASD plotting, enable/disable, `SYNC`, divider, modulation frequency controls, and manual or timed CSV logging for `SAMPLE` messages on either this computer or a Red Pitaya-mounted USB stick.
- Out of scope: multi-device control, offline import, derived DSP views beyond ASD, timing-accurate recording, and guaranteed gap-free history capture.

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
- The client accepts `RP_CAP:ads1278_v3` and still accepts `RP_CAP:ads1278_v2` for older servers before it accepts binary traffic.
- After the handshake, the client decodes the little-endian server messages defined in [Server Protocol](server-protocol.md), including `BULK_SAMPLES` batches.
- The top bar shows connection state, `frame_cnt`, `msg_seq`, enable state, overflow state, the currently reported EXTCLK divider, and modulation state/frequency.
- The main view plots `CH1` through `CH8` as eight live traces.
- The **View** selector switches between time-domain plotting and an optional
  SpecKit-backed ASD view. ASD plots `V/sqrt(Hz)` versus Hz from a longer client
  history buffer and recomputes in a background worker so the GUI remains
  responsive.
- `Enable`, `Disable`, `SYNC`, `Set divider`, `Set MOD`, and **Demod CH1** send the documented binary commands to the server. The **MOD enable** checkbox immediately sends `MOD_DIV = 0` when unchecked, which holds the MOD output high; **Demod CH1** toggles `CTRL[2]` so CH1 shows the FPGA demod output while CH8 remains raw.
- `ACK` and `ERROR` update the displayed state immediately and also surface a visible status line that includes the echoed opcode and value.
- The **Save CSV to** selector chooses between `This computer` and `USB on Red Pitaya`.
- **CSV filename** sets the basename before capture starts. For local logging, **CSV folder** chooses where the file is written. For USB logging, the server writes that basename under `/mnt/usb/ads1278/logs`.
- **Demod rate (~MOD Hz)** is available only when CH1 is the sole selected channel. It keeps the existing CSV schema but gates rows to the demod update cadence.
- Local computer CSV logging writes rows only for in-memory `SAMPLE` messages and includes host timestamp plus server metadata and selected channels. Bulk batches are expanded to `SAMPLE` objects before logging.
- With demod-rate host logging enabled, the logger writes the first CH1 row, CH1 changes, or a row after `max(1, round(mod_div / (extclk_div * 512)))` ADC frames. If demod acquisition is not active in the message snapshot, host logging falls back to full-rate rows.
- USB CSV logging sends `SET_LOCAL_LOG_DURATION`, `SET_LOCAL_LOG_FILENAME`, and `START_LOCAL_LOG` after the `MARK_CAPTURE` ACK. When demod-rate logging is selected, `START_LOCAL_LOG` sets bit `8`; the controller requires the latest snapshot to have acquisition plus demod enabled (`CTRL & 0x6 == 0x6`) before sending. The server writes rows to the USB stick and returns the row count when `STOP_LOCAL_LOG` is ACKed.
- CSV logging can run manually until `Stop CSV` or for a positive duration entered as hours, minutes, and seconds. Host-side timed capture is stopped by the client timer; USB timed capture is stopped by the server timer.
- Host-side logging stops cleanly on manual stop, timed capture expiry, or disconnect. USB timed logging continues after disconnect until the server-side deadline expires; USB manual logging closes on disconnect.

## Architecture

The current client intentionally mirrors the same small-file structure used in the rest of the repo:

1. `client/main.py` is the source entry point and launches the Qt application.
2. `ads1278_client/main_window.py` owns the PySide6 window, connection and command widgets, logging actions, and eight `pyqtgraph` plots.
3. `ads1278_client/controller.py` owns the latest displayed state, channel history buffers, ASD history buffers, command dispatch, local logger lifecycle, and USB logging command flow.
4. `ads1278_client/transport.py` owns the background socket thread, capability-line read, fixed-size message framing, and serialized command writes.
5. `ads1278_client/protocol.py` owns the exact command/message structs, incremental handshake parsing, and binary decoding helpers.
6. `ads1278_client/csv_logger.py` owns CSV file creation, header writing, row writing, flushes, and close behavior.
7. `client/tools/fake_server.py` provides a host-side fixture server for manual bring-up without a board.

The connection lifecycle is:

1. The user clicks `Connect`.
2. The controller starts a background transport worker.
3. The worker connects to the configured host and port, reads until newline, validates the capability line, and forwards any binary remainder into the message parser.
4. The worker parses 64-byte single-message headers, waits for any `BULK_SAMPLES` payload bytes, and pushes expanded `Ads1278Message` objects back to the controller.
5. The controller updates the latest snapshot for all message types, appends time-plot and ASD history data only for `SAMPLE`, and logs only `SAMPLE` rows when host-side CSV logging is active. If USB logging was selected, the controller sends the duration, filename chunks, and start command after the capture marker ACK and waits for the server ACK before reporting logging active.
6. The Qt GUI polls a thread-safe controller snapshot on a timer and updates labels and plots on the main thread.
7. On disconnect or transport failure, the worker stops, the controller closes any active host-side CSV logger, and the GUI returns to the disconnected state. Timed USB CSV logging continues on the server after disconnect.

## Known risk areas

- The current server is a latest-sample streamer, so the client must not be interpreted as a lossless recorder.
- At higher acquisition rates the plotted stream can still be decimated by the GUI history length and render cadence. Bulk mode improves transport efficiency but does not fix FPGA `overflow`, GP0 hangs, or any explicit DMA overwrite/drop counters.
- `frame_cnt` is only 16 bits inside `status_raw`, so wraparound is normal.
- `overflow` is a sticky FPGA overlap indicator, not a TCP packet-loss count.
- `ACK` for `TRIGGER_SYNC` confirms the command write path, not a verified analog-world effect.
- Divider changes affect the FPGA timing path globally because that is the current hardware contract.
- The live ASD view is computed from the client-side stream buffer. It is useful
  for quick noise inspection, but it is not a substitute for logged, offline
  analysis when gap-free records or very low-frequency confidence are required.
- USB CSV logging requires the Red Pitaya server to be running independently of SSH, preferably via systemd, and requires the stick to be mounted at `/mnt/usb` before capture starts.

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
- Set MOD frequency `10 Hz` and confirm the displayed modulation frequency updates to `10.000 Hz`.
- Clear **MOD enable** and confirm the status line shows `ACK SET_MOD_DIV value=0` and `mod: off`.
- Start manual CSV logging, re-enable streaming, and confirm the file contains only `SAMPLE` rows with negative values preserved.
- Select CH1 only, enable **Demod rate (~MOD Hz)**, and confirm local CSV row count tracks the MOD cadence when acquisition plus demod are active.
- Set a positive CSV duration, start logging, and confirm logging stops automatically after the requested capture window.
- Select `Save CSV to: USB on Red Pitaya`, start and stop manual CSV logging against `client/tools/fake_server.py`, and confirm the status reports a server row count. Repeat with CH1-only demod-rate logging after enabling acquisition and demod in the fake server.
- On hardware, mount a USB stick at `/mnt/usb`, run the server with `--log-dir /mnt/usb/ads1278/logs`, select `Save CSV to: USB on Red Pitaya`, set a short duration, start logging, disconnect the GUI, and confirm the CSV keeps growing until the server deadline.

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
