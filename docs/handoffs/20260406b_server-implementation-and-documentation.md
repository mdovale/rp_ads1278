# rp_ads1278 - Server implementation and documentation handoff

This handoff turns the broad "next development steps" guidance into a concrete plan for building and documenting the missing `server/` layer.

## Summary

- The FPGA/MMIO contract is implemented and documented well enough to support a first server.
- The repo-root server build/deploy scaffolding already exists, but `server/` does not.
- `./server-build-cross.sh` currently fails immediately with `Error: Makefile not found in /Users/mdovale/Work-local/rp_ads1278/server`.
- The minimal server should be a small C binary that maps `0x40000000` via `/dev/mem`, polls for new frames using `frame_cnt`, streams a fixed binary message format over TCP, and accepts a very small control command set.
- The most important design constraint is that `STATUS[0]` / `irq` are pulse-style. The server should treat `frame_cnt` as the authoritative "new sample" indicator and `new_data` as advisory only.

## Why this handoff exists

`docs/handoffs/20260406_next-development-steps.md` correctly says the next high-value work is the server, but it deliberately leaves several implementation decisions open:

- how the server should detect new data safely
- what frame format should be sent to the client
- what command format should be accepted
- how the new source tree should fit the existing root build and deploy scripts
- which docs should be written alongside the code

The next session should not reopen those questions unless the FPGA contract changes.

## Current state to preserve

Keep the current hardware/software contract unchanged unless there is a deliberate RTL update and matching doc update in the same session.

- MMIO base: `0x40000000`
- MMIO aperture: `0x1000`
- Access width: 32-bit reads and writes
- Register map:
  - `0x00` to `0x1C`: `CH1` to `CH8`
  - `0x20`: `STATUS`
  - `0x24`: `CTRL`
  - `0x28`: `EXTCLK_DIV`
- `CTRL[1]`: acquisition enable
- `CTRL[0]`: one-shot `SYNC` trigger that auto-clears in hardware
- `STATUS[0]`: pulse-style `new_data`
- `STATUS[1]`: sticky `overflow`
- `STATUS[31:16]`: `frame_cnt`
- Channel words: zero-extended 24-bit samples
- `EXTCLK_DIV` reset value: `625`

Important RTL-backed caveats:

- `new_data` is not sticky, so polling software can miss it.
- `irq` mirrors `new_data`, so it is also pulse-like and not useful for this first `/dev/mem` server.
- `EXTCLK_DIV` is shared by EXTCLK generation, SPI timing, and SYNC pulse width.
- RTL clamps divider values smaller than `2`, but the ADS1278 clocking docs imply software should stay at `3` or greater to remain within the documented practical clock range.
- `SYNC` is not gated by enable in the current RTL.

## Server design decisions

### 1. Scope for v1

Build a minimal bring-up server, not the final high-throughput architecture.

- Language: C
- Runtime: Linux user space on Red Pitaya PS
- MMIO path: `/dev/mem` with `O_RDWR | O_SYNC`
- Network model: one TCP client at a time
- Concurrency model: single-threaded polling loop
- Control path: fixed-size binary commands
- Stream path: fixed-size binary messages
- Non-goals for v1:
  - DMA
  - DDR ring buffers
  - kernel driver or UIO
  - multi-client fanout
  - guaranteed lossless capture at high sample rates

### 2. Treat this as a latest-sample streamer

Because the FPGA only exposes one set of channel registers plus a 16-bit frame counter, the first server should be documented as a latest-sample streamer, not a lossless recorder.

- If the FPGA produces frames faster than user-space polling can observe them, intermediate samples will be skipped.
- `overflow` means overlap occurred inside the FPGA capture pipeline, not necessarily that the TCP server dropped a packet.
- This is acceptable for the first server because the immediate goal is observability and client bring-up, not final throughput.

### 3. Use `frame_cnt`, not `new_data`, to decide when to emit

Recommended rule:

- Poll `STATUS`.
- Extract `frame_cnt = status >> 16`.
- Emit a new sample message only when `frame_cnt` changes, or immediately after a successful control command.
- Ignore `STATUS[0]` for control flow except maybe for debug logging.

### 4. Read a coherent snapshot

The channel registers update together, but software still reads them through separate MMIO transactions. Avoid mixing fields across two FPGA frames.

Recommended snapshot helper:

1. Read `STATUS_A`.
2. Read `CH1` to `CH8`.
3. Read `CTRL`.
4. Read `EXTCLK_DIV`.
5. Read `STATUS_B`.
6. If `frame_cnt(STATUS_A) != frame_cnt(STATUS_B)`, retry a small number of times.
7. If retries still fail, keep the newest stable snapshot and increment a local debug counter.

Use `STATUS_B` as the status word attached to the emitted snapshot.

### 5. Sign-extend before sending

Do not make the future client reinterpret zero-extended raw channel words if the server can fix that once.

Recommended conversion:

- mask to `0x00ffffff`
- if bit `23` is set, OR with `0xff000000`
- store on the wire as signed 32-bit little-endian integers

This keeps the client simpler while preserving the raw `STATUS`, `CTRL`, and `EXTCLK_DIV` words separately.

## Recommended wire protocol for v1

Use a simple, explicit protocol instead of copying the `rpll` frame layout.

### Connection handshake

On connect, the server should first send one ASCII capability line:

```text
RP_CAP:ads1278_v1
```

After that line, all traffic is binary.

### Client-to-server commands

Each command is exactly 8 bytes, little-endian:

- word 0: opcode
- word 1: value

Recommended opcodes:

- `1`: `SET_ENABLE`
  - `value = 0` disable
  - `value = 1` enable
- `2`: `TRIGGER_SYNC`
  - `value` ignored, client should send `1`
- `3`: `SET_EXTCLK_DIV`
  - `value >= 3`

Reject:

- unknown opcodes
- `SET_ENABLE` values other than `0` or `1`
- `SET_EXTCLK_DIV < 3`

### Server-to-client messages

Every binary message after the capability line should be exactly 60 bytes, little-endian, in this order:

- word 0: `msg_type`
- word 1: `msg_seq`
- word 2: `opcode`
- word 3: `value`
- word 4: `status_raw`
- word 5: `ctrl_raw`
- word 6: `extclk_div`
- words 7 to 14: `ch1` to `ch8` as signed 32-bit samples

`msg_type` values:

- `1`: `SAMPLE`
- `2`: `ACK`
- `3`: `ERROR`

Field meaning:

- `msg_seq` is a server-side monotonic message counter.
- `opcode` and `value` are `0` for normal `SAMPLE` messages.
- For `ACK` and `ERROR`, `opcode` and `value` echo the command that caused the response.
- `status_raw`, `ctrl_raw`, `extclk_div`, and channel words always carry the server's latest coherent snapshot, even for `ACK` and `ERROR`.

Why this shape:

- It gives the client an explicit acknowledgement path for `SYNC`, which cannot be inferred from `CTRL[0]` because that bit auto-clears.
- It keeps the parser simple because every binary message has the same size.
- It avoids interleaving text acknowledgements with binary sample traffic.

### Emission rules

- Send one `SAMPLE` immediately after connect using the latest snapshot, even if acquisition is disabled.
- Send one `ACK` immediately after each valid command.
- Send one `ERROR` immediately after each invalid command.
- Send `SAMPLE` messages whenever `frame_cnt` changes.

## Proposed `server/` tree

Keep the first version small and aligned with the root build scripts.

- `server/Makefile`
- `server/server.c`
- `server/server.h`
- `server/memory_map.c`
- `server/memory_map.h`
- `server/protocol.h`
- `server/cmd_parse.c`
- `server/cmd_parse.h`
- `server/tests/test_cmd_parse.c`
- `server/tests/test_protocol_layout.c`

Optional but useful:

- `server/rpdevmem.c`

Notes:

- The Makefile target should produce a binary named `server` because `server-build-cross.sh` and `server-build-docker.sh` expect that output.
- `server-deploy.sh` already installs that binary remotely as `ads1278-server`, so there is no need to rename the local build target.

## File responsibilities

### `server/protocol.h`

Own:

- port number
- opcode constants
- message-type constants
- packed message layout
- message-size constants

Add compile-time size checks so the message layout cannot drift silently.

### `server/memory_map.h` and `server/memory_map.c`

Own:

- MMIO base and aperture
- register offsets
- `/dev/mem` open, `mmap`, and cleanup helpers
- 32-bit read and write wrappers
- 24-bit sign-extension helper
- coherent snapshot helper

Do not copy the multi-region `rpll` memory-map table. This project only needs one small register block.

### `server/cmd_parse.h` and `server/cmd_parse.c`

Own:

- buffering partial reads from the socket
- assembling fixed 8-byte commands
- validating opcodes and values

Unlike `rpll`, there is no need to support the old 4-byte legacy command encoding.

### `server/server.c`

Own:

- socket setup and accept loop
- signal handling for clean exit
- client receive loop
- MMIO writes for enable, SYNC, and divider changes
- sample emission loop keyed off `frame_cnt`
- immediate `ACK` or `ERROR` emission after commands

## Implementation order

### 1. Scaffold the source tree

- Create `server/` and `server/tests/`.
- Add the Makefile first so the root build scripts stop failing on a missing directory.
- Keep warning flags fairly strict, but do not pull in external dependencies.

### 2. Implement the MMIO layer

- Add `/dev/mem` mapping for `0x40000000` and `0x1000`.
- Add register offset constants.
- Add read/write helpers using `volatile uint32_t *`.
- Add a snapshot helper that returns:
  - `status_raw`
  - `ctrl_raw`
  - `extclk_div`
  - signed `ch1` to `ch8`

### 3. Implement protocol and command parsing

- Define the 60-byte server message format in `protocol.h`.
- Define the 8-byte command format in `protocol.h`.
- Add unit tests for:
  - partial command reads
  - invalid opcode rejection
  - invalid divider rejection
  - packed message size

### 4. Implement the TCP loop

- Bind one TCP listener.
- Accept one client at a time.
- Send `RP_CAP:ads1278_v1\n` on connect.
- Send one initial `SAMPLE`.
- Poll both the socket and FPGA state.
- Emit `SAMPLE` only when `frame_cnt` changes.
- Emit `ACK` or `ERROR` after commands.

### 5. Build on host, then cross-build

- Verify `make -C server`
- Verify `./server-build-cross.sh`
- Verify `./server-build-docker.sh`

The root scripts already enforce the correct local binary location, so let them act as the final shape check.

### 6. Board smoke test

- Deploy with `./server-deploy.sh --ip <host>`.
- Run the binary manually on the Red Pitaya first, not as a service.
- Connect with a tiny ad hoc client or Python snippet before writing the GUI client.

## Documentation that should be written in the same session

Do not leave the server protocol only in code comments.

### Add `docs/feats/server.md`

This should be the server-layer feature doc and should cover:

- role of the server in the three-layer architecture
- build entry points
- deploy path
- runtime model
- current limitations of the MMIO-only approach

### Add `docs/feats/server-protocol.md`

This should document:

- capability line
- command opcodes and validation rules
- 60-byte message layout
- little-endian assumption
- signed channel representation
- meaning of `SAMPLE`, `ACK`, and `ERROR`

### Update `docs/feats/server-mmio-contract.md` only if needed

Update it if implementation reveals a doc mismatch with the RTL, for example:

- offset mismatch
- reset value mismatch
- behavior mismatch for enable, SYNC, or divider writes

Do not broaden that doc into a network-protocol spec. Keep MMIO and TCP docs separate.

## Manual QA checklist

- `./server-build-cross.sh` succeeds.
- `./server-build-docker.sh` succeeds.
- `./server-deploy.sh --ip <host>` copies the binary successfully.
- On a board with the FPGA loaded, the server can map `0x40000000` without faulting.
- Initial connect returns `RP_CAP:ads1278_v1`.
- Initial binary message is exactly 60 bytes after the capability line.
- `SET_ENABLE 1` produces an `ACK` and subsequent `SAMPLE` messages with changing `frame_cnt`.
- `SET_ENABLE 0` produces an `ACK`, then `frame_cnt` returns to `0` and stops advancing.
- `SET_EXTCLK_DIV 625` produces an `ACK` with `extclk_div = 625`.
- `TRIGGER_SYNC` produces an `ACK` and the expected acquisition disturbance on real hardware.
- Channel ordering appears stable as CH1 to CH8.
- Signed negative inputs are decoded correctly by the server sign-extension helper.

## Known risks to keep explicit in the docs

- This server is not a final throughput solution because the FPGA exposes only a latest-value register bank.
- High sample rates will cause skipped frames in user-space polling even if TCP is healthy.
- `overflow` only means at least one overlap happened; it is not a missed-frame counter.
- `frame_cnt` is only 16 bits and will wrap.
- `SYNC` acknowledgement is software-level only; `CTRL[0]` will normally read back as cleared.
- Divider writes affect EXTCLK, SPI timing, and SYNC width together.

## References

- `README.md`
- `docs/handoffs/20260406_next-development-steps.md`
- `docs/feats/fpga.md`
- `docs/feats/fpga-register-map.md`
- `docs/feats/ads1278-acquisition-pipeline.md`
- `docs/feats/server-mmio-contract.md`
- `docs/notes/AXI_GP0_REGISTER_MAP_HOWTO.md`
- `fpga/rtl/ads1278_axi_slave.sv`
- `fpga/rtl/ads1278_acq_top.v`
- `fpga/rtl/ads1278_extclk_gen.v`
- `fpga/rtl/ads1278_spi_tdm.v`
- `fpga/rtl/ads1278_sync_pulse.v`
- `server-build-cross.sh`
- `server-build-docker.sh`
- `server-deploy.sh`
- `.reference/rpll_server/README.md`
- `.reference/rpll_server/esw/Makefile`
- `.reference/rpll_server/esw/server.c`
- `.reference/rpll_server/esw/memory_map.c`
- `.reference/rpll_server/esw/cmd_parse.c`

## Success criteria for the next session

- A real `server/` tree exists and builds through the root scripts.
- The network protocol is documented in `docs/feats/`, not only implied by source.
- The server can enable acquisition, trigger SYNC, set `EXTCLK_DIV`, and stream signed CH1 to CH8 snapshots from the MMIO block.
- The docs explicitly say this is a minimal MMIO polling server with latest-sample semantics, not a lossless final transport.
