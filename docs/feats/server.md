# Server

This doc covers the current `server/` layer in `rp_ads1278`: a minimal Red Pitaya user-space process that maps the FPGA MMIO block, accepts one TCP client, and streams the latest coherent ADS1278 snapshot over a fixed binary protocol.

## Goal

Provide a small, documented bring-up server that can control acquisition, expose current FPGA state over TCP, and unblock client development without changing the current FPGA/MMIO contract.

## Scope

- In scope: local `server/` sources, build and deploy entry points, the single-client runtime model, command handling, and the current MMIO-polling limitations.
- Out of scope: DMA, lossless recording, multi-client fanout, Linux service management, and any host-side GUI behavior beyond the documented wire protocol.

## User-facing behavior

Current build and deploy entry points are:

| Action | Entry point |
|------|------|
| Native host build | `make -C server` |
| Native unit tests | `make -C server test` |
| Cross-build for Red Pitaya | `./server-build-cross.sh` |
| Dockerized cross-build | `./server-build-docker.sh` |
| Deploy to board | `./server-deploy.sh --ip <host>` |

Current runtime behavior is:

- The binary is `server/server` locally and is deployed as `ads1278-server`.
- The process maps `0x42000000` for `0x1000` bytes through `/dev/mem`.
- The listener accepts one TCP client at a time on port `5000`.
- On connect, the server sends `RP_CAP:ads1278_v1\n`, then one initial `SAMPLE` message built from the latest coherent snapshot.
- While a client is connected, the server schedules MMIO checks from the current `EXTCLK_DIV` so the wake cadence targets about `2 * f_data`, capped by the configured `--poll-ms` maximum wait, and emits a new `SAMPLE` only when `frame_cnt` changes.
- Valid commands are applied immediately and answered with an `ACK`.
- Invalid commands are answered with an `ERROR`.
- `ACK` and `ERROR` messages still include the latest coherent snapshot so the client does not need a second read path.

Current limitations are explicit:

- This is a latest-sample streamer, not a lossless transport.
- High acquisition rates can skip intermediate frames because software only observes the newest register-bank contents.
- `overflow` is a sticky overlap flag from the FPGA pipeline, not a count of missed TCP messages.
- `frame_cnt` is 16-bit and will wrap.
- `SYNC` acknowledgement is software-level only because `CTRL[0]` auto-clears in hardware.

## Architecture

The current server is intentionally split into a few small files:

1. `server.c` owns process startup, signal handling, the one-client accept loop, socket I/O, MMIO writes for commands, and `SAMPLE`/`ACK`/`ERROR` emission.
2. `memory_map.c` owns `/dev/mem` mapping, register offsets, 32-bit access helpers, 24-bit sign extension, and coherent snapshot reads keyed on `frame_cnt`.
3. `cmd_parse.c` owns partial socket buffering and fixed 8-byte command assembly plus opcode/value validation.
4. `protocol.h` owns the fixed 8-byte command shape, the fixed 60-byte message shape, and protocol constants such as the capability line, port, and opcodes.
5. `tests/` holds focused unit checks for command parsing and message layout so the protocol cannot drift silently.

The snapshot flow matches the current RTL contract:

1. Read `STATUS` before the channel bank.
2. Read `CH1` through `CH8`, `CTRL`, and `EXTCLK_DIV`.
3. Read `STATUS` again.
4. Treat the snapshot as coherent only when the two `frame_cnt` values match.
5. If retries fail, keep the last stable snapshot and increment a local debug counter.

## Known risk areas

- The server still polls in user space, so it is not a final throughput architecture even though the wake cadence now follows `EXTCLK_DIV`.
- `new_data` is pulse-style and is not used as the primary emission trigger.
- Divider writes affect EXTCLK generation, SPI timing, and SYNC pulse width together because that is the current FPGA contract.
- The server assumes a little-endian host, which matches the current Red Pitaya target and the documented protocol.

## Manual QA

- `make -C server test`
- `make -C server`
- `./server-build-cross.sh`
- `./server-build-docker.sh`
- `./server-deploy.sh --ip <host>`
- Run `ads1278-server` on the board and confirm the first bytes on connect are the capability line followed by a 60-byte binary message.
- Send `SET_ENABLE`, `TRIGGER_SYNC`, and `SET_EXTCLK_DIV` commands and confirm `ACK` messages echo the opcode/value pair and updated snapshot fields.

## Key files

| Area | File |
|------|------|
| Main runtime loop | `server/server.c` |
| Server-level options and entry points | `server/server.h` |
| MMIO and coherent snapshot logic | `server/memory_map.c` |
| MMIO types and register constants | `server/memory_map.h` |
| Command buffering and validation | `server/cmd_parse.c` |
| Wire protocol constants and packed structs | `server/protocol.h` |
| MMIO debug helper | `server/rpdevmem.c` |
| Parser tests | `server/tests/test_cmd_parse.c` |
| Protocol layout tests | `server/tests/test_protocol_layout.c` |
| Cross-build script | `server-build-cross.sh` |
| Docker build script | `server-build-docker.sh` |
| Deploy script | `server-deploy.sh` |

## Related docs

- [Server Protocol](server-protocol.md)
- [Server MMIO Contract](server-mmio-contract.md)
- [FPGA Register Map](fpga-register-map.md)
- [ADS1278 Acquisition Pipeline](ads1278-acquisition-pipeline.md)
- [README](../../README.md)
- [Server implementation handoff](../handoffs/20260406b_server-implementation-and-documentation.md)
