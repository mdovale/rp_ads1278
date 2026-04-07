# rp_ads1278 - Python client implementation handoff

This handoff turns the broad "implement a minimal client" guidance into a concrete plan for building the missing `client/` layer against the now-implemented server protocol.

> Historical note: this handoff predates the in-tree `client/` implementation. For the current client behavior and usage, see `client/README.md` and `docs/feats/client.md`.

## Summary

- The FPGA layer is implemented and documented well enough to support software bring-up.
- The minimal `server/` layer now exists in-tree and defines a fixed v1 TCP protocol that the client should treat as the source of truth.
- `client/` still does not exist.
- The next session should implement a small Python desktop client that connects to the server, decodes the fixed 60-byte message format, plots eight channels live, exposes the three control commands, and logs samples to CSV.
- The most important design constraint is that the current server is a latest-sample streamer. The client must not imply lossless capture.

## Why this handoff exists

`docs/handoffs/20260406_next-development-steps.md` correctly identified the client as the next major layer after the server, but it left several implementation decisions open:

- how the client should parse the capability handshake and fixed-size binary stream
- how the client should model `SAMPLE`, `ACK`, and `ERROR`
- how control commands should be sent and acknowledged in the UI
- what should be plotted and what should be logged
- how much of `.reference/rpll_client/` should be copied versus redesigned

The next session should not reopen the wire protocol unless the server changes in the same session and the protocol docs are updated with it.

## Current repo state

Keep this state in mind before starting client work:

- `server/` now exists and is the only implemented software layer above the FPGA.
- `server/protocol.h` defines the protocol constants and packed layouts.
- `docs/feats/server.md` documents the server runtime model and limitations.
- `docs/feats/server-protocol.md` documents the capability line, command format, and 60-byte message layout.
- `client/` does not yet exist.
- Native host verification for the server was completed with:
  - `make -C server test`
  - `make -C server`
- Repo-level cross-build verification for the server was not completed on this host because:
  - `./server-build-cross.sh` failed due to missing `arm-linux-gnueabihf-gcc`
  - `./server-build-docker.sh` failed because the Docker daemon was not running

Those missing cross-build checks do not block host-side client implementation.

## Current state to preserve

Do not change these contracts while implementing the client unless you also update the server and the protocol docs in the same session.

- TCP port: `5000`
- Capability line: `RP_CAP:ads1278_v1\n`
- Command size: `8` bytes, little-endian
- Message size: `60` bytes, little-endian
- Command layout:
  - word `0`: `opcode`
  - word `1`: `value`
- Message layout:
  - word `0`: `msg_type`
  - word `1`: `msg_seq`
  - word `2`: `opcode`
  - word `3`: `value`
  - word `4`: `status_raw`
  - word `5`: `ctrl_raw`
  - word `6`: `extclk_div`
  - words `7` to `14`: `ch1` to `ch8` as signed 32-bit samples
- Opcode values:
  - `1`: `SET_ENABLE`
  - `2`: `TRIGGER_SYNC`
  - `3`: `SET_EXTCLK_DIV`
- Message types:
  - `1`: `SAMPLE`
  - `2`: `ACK`
  - `3`: `ERROR`

Important behavioral constraints to preserve in the UI:

- The server sends one initial `SAMPLE` immediately after connect, even if acquisition is disabled.
- `ACK` and `ERROR` both carry a full snapshot and should be treated as state updates, not as side-band text.
- `frame_cnt` is only 16 bits inside `status_raw` and will wrap.
- `overflow` is a sticky FPGA overlap flag, not a TCP packet-loss counter.
- `CTRL[0]` auto-clears in hardware, so a `TRIGGER_SYNC` acknowledgement is software-level only.
- The current transport exposes latest-sample semantics, not a guaranteed gap-free sample history.

## Client design decisions

### 1. Scope for v1

Build a minimal bring-up client, not the final polished acquisition suite.

- Language: Python
- Runtime: host desktop
- Network model: one TCP connection to one Red Pitaya server
- Stream parser: one capability line followed by fixed-size binary messages
- UI scope:
  - connect or disconnect
  - show connection state
  - show `frame_cnt`
  - plot CH1 to CH8 live
  - expose enable or disable control
  - expose `SYNC`
  - expose divider control
  - start or stop CSV logging
- Non-goals for v1:
  - offline file import
  - protocol version negotiation beyond checking the capability line
  - multi-device control
  - advanced triggering
  - derived DSP views
  - guaranteed timing-accurate recording

### 2. Reuse the reference client architecture instead of inventing a new one

The user explicitly called out `.reference/rpll_client/` as a reusable authored reference. Treat it as the default source tree to copy from heavily.

Recommended rule:

- Copy the reference client's overall structure, event flow, and GUI scaffolding where it fits.
- Rename symbols and labels to the ADS1278 domain instead of preserving reference-project terminology.
- Simplify aggressively where the current server protocol is smaller than the reference protocol.
- Do not preserve reference-only protocol branches or legacy compatibility code that the current server does not need.

### 3. Use a background networking worker

Do not let blocking socket reads run on the GUI thread.

Recommended model:

1. Main thread owns the UI.
2. One background networking worker owns the socket, read loop, reconnect-safe teardown, and command writes.
3. The worker emits parsed message objects to the UI through a thread-safe queue, signal, or callback mechanism consistent with the reference client.
4. The UI/controller layer owns the latest displayed state and plotting buffers.

### 4. Parse the wire format exactly once in one module

Do not scatter `struct.unpack()` logic across the UI.

Recommended protocol helpers:

- Command packer: `struct.Struct("<II")`
- Message parser: `struct.Struct("<7I8i")`
- Capability-line parser:
  - read until newline
  - require exact match to `RP_CAP:ads1278_v1`
  - fail fast on mismatch

Represent parsed messages with one small typed object that carries:

- `msg_type`
- `msg_seq`
- `opcode`
- `value`
- `status_raw`
- `ctrl_raw`
- `extclk_div`
- `channels`
- derived helpers such as:
  - `frame_cnt = status_raw >> 16`
  - `overflow = bool(status_raw & 0x2)`
  - `new_data = bool(status_raw & 0x1)`
  - `enabled = bool(ctrl_raw & 0x2)`

### 5. Treat `ACK` and `ERROR` as first-class UI events

Do not build the client as if only `SAMPLE` matters.

Recommended behavior:

- `SAMPLE`: update plots and status widgets
- `ACK`: update status widgets immediately and surface a short success indication for the originating command
- `ERROR`: update status widgets and surface a visible error indication including opcode and value

This is especially important for:

- `TRIGGER_SYNC`, where the effect cannot be inferred from `CTRL[0]`
- invalid divider writes, which the user should see immediately

### 6. Log sample data explicitly, not every message indiscriminately

For v1 CSV logging, log `SAMPLE` messages only unless there is a clear need to include control responses.

Recommended CSV columns:

- host timestamp
- `msg_seq`
- `frame_cnt`
- `status_raw`
- `ctrl_raw`
- `extclk_div`
- `ch1`
- `ch2`
- `ch3`
- `ch4`
- `ch5`
- `ch6`
- `ch7`
- `ch8`

If `ACK` or `ERROR` logging is later desired, add it as an explicit mode with a row type field rather than silently mixing control responses into sample logs.

## Proposed `client/` tree

Keep the first version small and easy to test. If `.reference/rpll_client/` already has a better equivalent structure, prefer copying it rather than debating packaging details.

- `client/requirements.txt` or `client/pyproject.toml`
- `client/main.py`
- `client/ads1278_client/__init__.py`
- `client/ads1278_client/protocol.py`
- `client/ads1278_client/transport.py`
- `client/ads1278_client/models.py`
- `client/ads1278_client/controller.py`
- `client/ads1278_client/csv_logger.py`
- `client/ads1278_client/main_window.py`
- `client/tests/test_protocol.py`
- `client/tests/test_csv_logger.py`

If the reference client already has a reusable split for worker, controller, and plotting widgets, mirror that naming pattern instead of forcing the tree above exactly.

## File responsibilities

### `client/ads1278_client/protocol.py`

Own:

- capability-line validation
- command packing
- fixed 60-byte message parsing
- message-type and opcode constants
- derived helpers for `frame_cnt`, `overflow`, `enabled`, and similar status bits

### `client/ads1278_client/transport.py`

Own:

- socket connect and disconnect
- read loop
- newline handshake read
- fixed-size message framing
- reconnect-safe shutdown
- serialized command sending

### `client/ads1278_client/controller.py`

Own:

- latest server state
- plot buffer updates
- command dispatch from UI actions
- command-response status text
- logger start or stop coordination

### `client/ads1278_client/csv_logger.py`

Own:

- CSV file creation
- header writing
- row writing for `SAMPLE` messages
- flush and close behavior

### `client/ads1278_client/main_window.py`

Own:

- connection controls
- status display
- frame counter display
- divider entry
- enable and disable control
- `SYNC` button
- eight live traces
- logging controls

## Implementation order

### 1. Scaffold the client tree

- Create `client/`.
- Add the packaging entry point first.
- Copy the reference client's bootstrapping and application skeleton where possible.

### 2. Implement protocol parsing before UI details

- Add capability-line validation.
- Add command packing for the three server opcodes.
- Add the 60-byte binary message parser.
- Add unit tests for:
  - split capability-line reads
  - split binary-message reads
  - negative channel decoding
  - frame-count extraction
  - invalid capability rejection

### 3. Implement the transport worker

- Connect to host and port.
- Read the capability line first.
- Then read exact 60-byte binary records in a loop.
- Publish parsed messages upward without UI-specific logic inside the transport module.

### 4. Build the smallest useful UI

- Add host or port entry and connect button.
- Add connection-state indicator.
- Add one visible `frame_cnt` display.
- Add eight live plots.
- Add enable, disable, `SYNC`, and divider controls.
- Add a small status area for `ACK` and `ERROR`.

### 5. Add CSV logging

- Log only `SAMPLE` messages by default.
- Include enough metadata to correlate rows with UI state and server sequence.
- Keep the logger decoupled from the plotting code.

### 6. Validate locally before involving hardware

- Use a tiny fake server or fixture stream first.
- Only move to the real Red Pitaya after the parser, UI, and logger work against deterministic test data.

## Suggested fake-server test fixture

Before connecting to hardware, make a tiny Python fixture that:

- accepts one TCP client
- sends `RP_CAP:ads1278_v1\n`
- sends one initial `SAMPLE`
- sends an `ACK`
- sends an `ERROR`
- sends a few `SAMPLE` messages with changing `frame_cnt`
- includes at least one negative channel value

This lets the next session validate:

- line-based handshake parsing
- fixed-size binary framing
- `ACK`/`ERROR` handling
- signed channel decoding
- CSV logging behavior
- plotting updates without requiring a board

## Documentation that should be written in the same session

Do not leave the client behavior only in the Python code.

### Add `docs/feats/client.md`

This should cover:

- the role of the client in the three-layer architecture
- how to run it locally
- current UI/runtime model
- connection lifecycle
- current limitations

### Do not create a second protocol spec

The wire protocol already belongs in `docs/feats/server-protocol.md`.

Client docs should:

- link to `server-protocol.md`
- describe how the client consumes that protocol
- avoid duplicating the binary layout as a second source of truth

### Update `README.md` only if the entry point or scope materially changes

The current README already says the end-state client is a Python GUI, so do not churn it unless implementation reveals a real mismatch.

## Manual QA checklist

- The client can connect to `ads1278-server` on port `5000`.
- The client rejects an invalid capability line cleanly.
- The initial `SAMPLE` populates the UI even before acquisition is enabled.
- `SET_ENABLE 1` results in an `ACK` and then visible `frame_cnt` movement when the server is streaming.
- `SET_ENABLE 0` results in an `ACK` and `frame_cnt` stops advancing.
- `TRIGGER_SYNC` produces an `ACK` and a visible status notification in the UI.
- `SET_EXTCLK_DIV 625` produces an `ACK` and the displayed divider updates.
- `SET_EXTCLK_DIV 2` produces an `ERROR` that the user can see clearly.
- Negative channel values render correctly and log as negative integers.
- CSV logging writes rows for streamed samples and closes cleanly on stop or disconnect.
- Disconnects do not hang the UI thread.

## Known risks to keep explicit in the docs

- The current server is a latest-sample streamer, so the client must not imply lossless capture.
- High sample rates can skip intermediate frames even when the network is healthy.
- `overflow` is only a sticky overlap indicator, not a missed-sample count.
- `frame_cnt` wrap is normal and must not be treated as a fatal error.
- `ACK` for `TRIGGER_SYNC` confirms a command write, not a verified analog-world effect.
- Divider changes affect the whole FPGA timing path, not only one displayed rate number.

## References

- `README.md`
- `docs/handoffs/20260406_next-development-steps.md`
- `docs/handoffs/20260406b_server-implementation-and-documentation.md`
- `docs/feats/server.md`
- `docs/feats/server-protocol.md`
- `docs/feats/server-mmio-contract.md`
- `docs/feats/fpga.md`
- `docs/feats/fpga-register-map.md`
- `docs/feats/ads1278-acquisition-pipeline.md`
- `server/protocol.h`
- `.reference/rpll_client/`

## Success criteria for the next session

- A real `client/` tree exists.
- The client can parse `RP_CAP:ads1278_v1\n` and the fixed 60-byte message format correctly.
- The client can send `SET_ENABLE`, `TRIGGER_SYNC`, and `SET_EXTCLK_DIV` commands.
- The client plots all eight channels live and shows frame counter plus connection state.
- The client logs streamed samples to CSV.
- The client docs describe the runtime model and explicitly state the current latest-sample limitations.
