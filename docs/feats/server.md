# Server

This doc covers the current `server/` layer in `rp_ads1278`: a Red Pitaya user-space process that maps the FPGA MMIO block, accepts one TCP client, streams ADS1278 samples over a binary protocol, and can write client-armed CSV logs to a USB stick mounted on the Red Pitaya. It supports legacy latest-sample MMIO streaming, an opt-in DMA-backed buffer consumer, and a bulk DMA transport mode.

## Goal

Provide a small, documented bring-up server that can control acquisition, expose current FPGA state over TCP, consume completed DMA ping-pong buffers without forcing every DMA frame through the single-sample wire message, and run timed USB-backed CSV captures after the GUI client disconnects.

## Scope

- In scope: local `server/` sources, build and deploy entry points, the single-client runtime model, command handling, legacy MMIO streaming, DMA ping-pong buffer consumption, bulk DMA sample messages, and USB CSV logging under `/mnt/usb/ads1278/logs`.
- Out of scope: multi-client fanout and automatic USB mounting.

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

- The binary is `server/server` locally and is deployed as `/root/ads1278-server`.
- The process maps `0x42000000` for `0x1000` bytes through `/dev/mem`.
- The listener accepts one TCP client at a time on port `5000`.
- On connect, the server sends `RP_CAP:ads1278_v3\n`, then one initial `SAMPLE` message built from the latest coherent snapshot.
- While a client is connected, the server schedules MMIO checks from the current `EXTCLK_DIV` so the wake cadence targets about `2 * f_data`, capped by the configured `--poll-ms` maximum wait, and emits a new `SAMPLE` only when `frame_cnt` changes.
- With `--dma`, the server arms DMA capture mode, watches `DMA_BUF_STATUS`, maps both ping-pong DDR buffers, emits one existing 64-byte `SAMPLE` per valid 128-byte DMA frame, and writes `DMA_BUF_ACK` after each consumed buffer.
- With `--dma-bulk`, the server also enables DMA mode, but emits one `BULK_SAMPLES` header plus compact 40-byte frame records for each completed buffer before writing `DMA_BUF_ACK`.
- `START_LOCAL_LOG` opens a CSV under `/mnt/usb/ads1278/logs` by default; `--log-dir PATH` overrides the directory.
- `START_LOCAL_LOG` bit `8` requests demod-rate logging for CH8-only captures. The server rejects that start with `ERROR` unless the current control snapshot has acquisition plus demod enabled (`CTRL & 0x6 == 0x6`).
- `SET_LOCAL_LOG_DURATION` sets the duration, in seconds, for the next local USB CSV log. `0` means manual logging.
- `SET_LOCAL_LOG_FILENAME` sets the next USB CSV basename in 3-byte protocol chunks. If no basename is sent, the server uses `ads1278_YYYYMMDD_HHMMSS.csv`.
- Timed USB CSV logging continues after the GUI client disconnects until the server deadline expires. Manual USB CSV logging closes on disconnect to avoid unbounded writes.
- Valid commands are applied immediately and answered with an `ACK`.
- Invalid commands are answered with an `ERROR`.
- `ACK` and `ERROR` messages still include the latest coherent snapshot so the client does not need a second read path.

Current limitations are explicit:

- Legacy mode is a latest-sample streamer, not a lossless transport.
- High acquisition rates can skip intermediate frames in legacy mode because software only observes the newest register-bank contents.
- `--dma-bulk` reduces TCP message count, but it is still a user-space poller and still depends on GP0/MMIO stability for `DMA_BUF_STATUS` and `DMA_BUF_ACK`.
- USB CSV logging requires the stick to be mounted manually at `/mnt/usb` before `START_LOCAL_LOG`.
- CSV formatting is synchronous in the server hot path; prefer `--dma-bulk --poll-ms 0` for sustained captures.
- `overflow` is a sticky overlap flag from the FPGA pipeline, not a count of missed TCP messages.
- `frame_cnt` is 16-bit and will wrap.
- `SYNC` acknowledgement is software-level only because `CTRL[0]` auto-clears in hardware.

## Architecture

The current server is intentionally split into a few small files:

1. `server.c` owns process startup, signal handling, the one-client accept loop, socket I/O, MMIO writes for commands, optional DMA buffer ownership, USB CSV logging lifecycle, and `SAMPLE`/`ACK`/`ERROR` emission.
2. `memory_map.c` owns `/dev/mem` mapping, register offsets, 32-bit access helpers, 24-bit sign extension, and coherent snapshot reads keyed on `frame_cnt`.
3. `cmd_parse.c` owns partial socket buffering and fixed 8-byte command assembly plus opcode/value validation.
4. `protocol.h` owns the fixed 8-byte command shape, the 64-byte message header shape, the 40-byte bulk frame shape, and protocol constants such as the capability line, port, and opcodes.
5. `csv_logger.c` owns USB CSV filename validation, directory checks, header writing, row writing, flushes, and close behavior.
6. `tests/` holds focused unit checks for command parsing, CSV logging, and message layout so the protocol cannot drift silently.

The snapshot flow matches the current RTL contract:

1. Read `STATUS` before the channel bank.
2. Read `CH1` through `CH8`, `CTRL`, `EXTCLK_DIV`, and `MOD_DIV`.
3. Read `STATUS` again.
4. Treat the snapshot as coherent only when the two `frame_cnt` values match.
5. If retries fail, keep the last stable snapshot and increment a local debug counter.

The DMA flow is opt-in with `ads1278-server --dma` or `ads1278-server --dma-bulk`:

1. Open buffer 0 at `DMA_BASE_ADDR` and buffer 1 at `DMA_BASE_ADDR + DMA_BUF_SIZE`.
2. On client connect, program `DMA_BASE_ADDR` / `DMA_BUF_SIZE`, clear stale IRQ/full bits, and write `DMA_CTRL = 0x3` for capture mode.
3. Poll `DMA_BUF_STATUS` for full ping-pong buffers.
4. Before parsing a full buffer, sync the DDR mapping for CPU reads and use the canary phase (`0xAD127831`) to find the first complete 128-byte record.
5. Emit either one legacy `SAMPLE` message per valid DMA frame (`--dma`) or one `BULK_SAMPLES` batch per completed buffer (`--dma-bulk`), then write the matching `DMA_BUF_ACK` bit.
6. Stop DMA when the client disconnects, unless a timed USB CSV log is active.

The USB CSV workflow is:

1. Mount the flash stick at `/mnt/usb`.
2. Run `/root/ads1278-server --dma-bulk --poll-ms 0 --log-dir /mnt/usb/ads1278/logs`, preferably through systemd.
3. The client sends `MARK_CAPTURE`, `SET_LOCAL_LOG_DURATION`, optional `SET_LOCAL_LOG_FILENAME` chunks, and `START_LOCAL_LOG`.
4. The server writes rows for legacy samples, DMA samples, or expanded DMA bulk frames. With demod-rate CH8 logging requested, it writes only the first row, CH8 changes, or the elapsed demod frame interval.
5. If the log is timed and the client disconnects, the server keeps servicing acquisition without a client until the deadline.
6. On deadline, `STOP_LOCAL_LOG`, server shutdown, or manual disconnect for untimed logs, the CSV is flushed and closed.

## Known risk areas

- The server still polls in user space, so it is not a final throughput architecture even though the wake cadence now follows `EXTCLK_DIV`.
- `new_data` is pulse-style and is not used as the primary emission trigger.
- Divider writes affect EXTCLK generation, SPI timing, and SYNC pulse width together because that is the current FPGA contract.
- The server assumes a little-endian host, which matches the current Red Pitaya target and the documented protocol.
- DMA mode requires page-aligned `--dma-base` and page-sized `--dma-size`; defaults are `0x1e000000` and `0x00010000`.
- Timed USB CSV capture survives GUI and SSH disconnect only while `ads1278-server` itself stays alive. Use systemd or `nohup`; do not rely on a foreground SSH process.
- If `/mnt/usb` is not a mount point, `START_LOCAL_LOG` fails with `ERROR` and the server logs the OS error to stderr/journal.

## Manual QA

- `make -C server test`
- `make -C server`
- `./server-build-cross.sh`
- `./server-build-docker.sh`
- `./server-deploy.sh --ip <host>`
- Run `ads1278-server` on the board and confirm the first bytes on connect are the capability line followed by a 64-byte binary message.
- Run `ads1278-server --dma` on the board, connect one client, and confirm `DMA_OVERWRITE_COUNT` stays flat while buffers are ACKed.
- Run `ads1278-server --dma-bulk --poll-ms 0` on the board, connect the updated client, and confirm completed buffers arrive as bulk-expanded samples while `DMA_OVERWRITE_COUNT` stays flat.
- Send `SET_ENABLE`, `TRIGGER_SYNC`, `SET_EXTCLK_DIV`, and `SET_MOD_DIV` commands and confirm `ACK` messages echo the opcode/value pair and updated snapshot fields.
- Mount a USB stick at `/mnt/usb`, run `/root/ads1278-server --dma-bulk --poll-ms 0 --log-dir /mnt/usb/ads1278/logs`, start a 60 s USB CSV capture from the client, disconnect the GUI, and confirm the file keeps growing until the deadline.
- With CH8-only logging and `CTRL & 0x6 == 0x6`, enable demod-rate CSV and confirm row count is near the MOD rate; with acquisition-only control, confirm `START_LOCAL_LOG` returns `ERROR`.
- Confirm `sync && umount /mnt/usb` succeeds before unplugging the stick.

## Key files

| Area | File |
|------|------|
| Main runtime loop | `server/server.c` |
| Server-level options and entry points | `server/server.h` |
| MMIO and coherent snapshot logic | `server/memory_map.c` |
| MMIO types and register constants | `server/memory_map.h` |
| Command buffering and validation | `server/cmd_parse.c` |
| Wire protocol constants and packed structs | `server/protocol.h` |
| USB CSV logging | `server/csv_logger.c` |
| MMIO debug helper | `server/rpdevmem.c` |
| Parser tests | `server/tests/test_cmd_parse.c` |
| USB CSV logger test | `server/tests/test_csv_logger.c` |
| Protocol layout tests | `server/tests/test_protocol_layout.c` |
| Cross-build script | `server-build-cross.sh` |
| Docker build script | `server-build-docker.sh` |
| Deploy script | `server-deploy.sh` |

## Related docs

- [DMA Frame Record](dma-frame-record.md)
- [Server Protocol](server-protocol.md)
- [Server MMIO Contract](server-mmio-contract.md)
- [FPGA Register Map](fpga-register-map.md)
- [ADS1278 Acquisition Pipeline](ads1278-acquisition-pipeline.md)
- [README](../../README.md)
- [Server implementation handoff](../handoffs/20260406b_server-implementation-and-documentation.md)
