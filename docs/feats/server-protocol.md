# Server Protocol

This doc describes the current TCP protocol implemented by `server/` in `rp_ads1278`. It covers the capability handshake, fixed-size binary commands, 64-byte message headers, and the current emission rules used by both the MMIO-polling server and the opt-in DMA consumers.

## Goal

Define the current network contract clearly enough that the implemented Python client can connect, send control commands, and decode streamed ADS1278 snapshots without inferring layout details from the C source.

## Scope

- In scope: the capability line, default TCP port, binary command encoding, binary message encoding, little-endian assumptions, local USB CSV logging commands, and current emission rules.
- Out of scope: the FPGA register map itself, GUI behavior, and Linux service setup.

## User-facing behavior

Current transport assumptions are:

- TCP listener port: `5000`
- Capability line: ASCII, newline-terminated (`RP_CAP:ads1278_v3`)
- All binary traffic after the capability line: little-endian
- Channel samples on the wire: signed 32-bit integers produced by server-side sign extension of the FPGA's zero-extended 24-bit channel words

Connection startup is:

1. Client connects to the TCP port.
2. Server sends `RP_CAP:ads1278_v3\n`.
3. Server sends one binary `SAMPLE` message immediately, even if acquisition is currently disabled.

Client-to-server commands are fixed 8-byte messages:

| Word | Field | Meaning |
|------|------|------|
| `0` | `opcode` | Command selector |
| `1` | `value` | Command value |

Current opcodes are:

| Opcode | Name | Rules |
|------|------|------|
| `1` | `SET_ENABLE` | `value` must be `0` or `1` |
| `2` | `TRIGGER_SYNC` | `value` is ignored by the server |
| `3` | `SET_EXTCLK_DIV` | `value` must be `>= 3` |
| `4` | `MARK_CAPTURE` | `value` is ignored by the server |
| `5` | `SET_MOD_DIV` | `value` must be `0` or `>= 2`; `0` holds MOD high |
| `6` | `START_LOCAL_LOG` | Bits `0..7` are the channel mask (`0` means all channels); bit `8` requests demod-rate CH8 logging |
| `7` | `STOP_LOCAL_LOG` | `value` is ignored on request; `ACK.value` reports rows written |
| `8` | `SET_LOCAL_LOG_DURATION` | Whole seconds for the next local log; `0` means manual/untimed |
| `9` | `SET_LOCAL_LOG_FILENAME` | One 3-byte ASCII chunk of the next local log basename |

Unknown opcodes are rejected.

USB CSV logging commands are ordered by the client as:

1. `MARK_CAPTURE` to establish a stream boundary.
2. `SET_LOCAL_LOG_DURATION` with `0` for manual logging or a positive whole-second duration for unattended logging.
3. One or more `SET_LOCAL_LOG_FILENAME` chunks. Bits `31:24` are the chunk index; bits `23:0` are up to three little-endian ASCII bytes. The server clears the pending basename when chunk `0` arrives and terminates the basename at the first NUL byte.
4. `START_LOCAL_LOG` with the selected channel mask and optional demod-rate bit.

`START_LOCAL_LOG` opens a CSV under the server log directory (`/mnt/usb/ads1278/logs` by default, or `--log-dir PATH`). If opening fails because the USB stick is not mounted, the filesystem is full, or the basename is invalid, the server sends `ERROR`. If bit `8` is set, the server also requires the current `CTRL` snapshot to have acquisition plus demod enabled (`CTRL & 0x6 == 0x6`) before it starts; otherwise it sends `ERROR`. Timed local logs continue after the TCP client disconnects until the server deadline expires. Manual local logs are closed on client disconnect to avoid unbounded writes.

When bit `8` is set and CH8 is the only selected channel, the CSV writer gates rows to the demod update cadence. It writes the first row, any later row where CH8 changes, or a row after `max(1, round(mod_div / (extclk_div * 512)))` ADC frames so flat signals still advance in time. It writes at most one row for a given ADC frame. If demod acquisition is not active after the log has started, rows fall back to the full ADC-rate stream.

Server-to-client legacy/control messages use a fixed 64-byte header:

| Word | Field | Meaning |
|------|------|------|
| `0` | `msg_type` | `1 = SAMPLE`, `2 = ACK`, `3 = ERROR`, `4 = BULK_SAMPLES` |
| `1` | `msg_seq` | Monotonic server-side message counter |
| `2` | `opcode` | `0` for `SAMPLE`; echoed command opcode for `ACK`/`ERROR` |
| `3` | `value` | `0` for `SAMPLE`; echoed command value for `ACK`/`ERROR`; frame count for `BULK_SAMPLES` |
| `4` | `status_raw` | Raw FPGA `STATUS` word from the latest coherent snapshot |
| `5` | `ctrl_raw` | Raw FPGA `CTRL` word from the latest coherent snapshot |
| `6` | `extclk_div` | Raw FPGA divider word from the latest coherent snapshot |
| `7` | `mod_div` | Raw FPGA modulation divider from the latest coherent snapshot; `0` means MOD off/high |
| `8` | `ch1` | Signed 32-bit channel sample |
| `9` | `ch2` | Signed 32-bit channel sample |
| `10` | `ch3` | Signed 32-bit channel sample |
| `11` | `ch4` | Signed 32-bit channel sample |
| `12` | `ch5` | Signed 32-bit channel sample |
| `13` | `ch6` | Signed 32-bit channel sample |
| `14` | `ch7` | Signed 32-bit channel sample |
| `15` | `ch8` | Signed 32-bit channel sample |

For `BULK_SAMPLES`, the 64-byte header is immediately followed by `value` compact frame records. Each compact record is 40 bytes:

| Word | Field | Meaning |
|------|------|------|
| `0` | `frame_count` | Raw 32-bit frame counter stored in DDR |
| `1` | `status_raw` | Raw frame status word stored in DDR |
| `2` | `ch1` | Signed 32-bit channel sample |
| `3` | `ch2` | Signed 32-bit channel sample |
| `4` | `ch3` | Signed 32-bit channel sample |
| `5` | `ch4` | Signed 32-bit channel sample |
| `6` | `ch5` | Signed 32-bit channel sample |
| `7` | `ch6` | Signed 32-bit channel sample |
| `8` | `ch7` | Signed 32-bit channel sample |
| `9` | `ch8` | Signed 32-bit channel sample |

The bulk header's `msg_seq` is the first logical sample sequence number in the batch. The updated Python client expands a bulk wire message into normal in-memory `SAMPLE` messages with sequence numbers `msg_seq + frame_index`, so plotting and CSV logging can keep using the existing sample path.

Emission rules are:

- Send one initial `SAMPLE` immediately after the capability line.
- Send `ACK` immediately after every valid command.
- Send `ERROR` immediately after every invalid command.
- For local USB logging, send `ACK START_LOCAL_LOG` only after the CSV has been opened and its header flushed.
- Send `SAMPLE` when `frame_cnt` changes.
- In `--dma` mode, send one existing `SAMPLE` message per valid 128-byte DMA frame from a completed DDR ping-pong buffer, then ACK that buffer in MMIO.
- In `--dma-bulk` mode, send one `BULK_SAMPLES` header plus compact records for valid frames in the completed DDR ping-pong buffer, then ACK that buffer in MMIO.
- When USB CSV logging is active, the server writes the same logical samples to the CSV before socket emission, optionally gated by demod-rate CH8 logging. If a timed log remains active after client disconnect, the server keeps consuming legacy samples or DMA buffers with `client_fd == -1` until the deadline.
- `ACK` and `ERROR` carry the same snapshot fields as `SAMPLE`, so a client can always treat the message as both a response and a state update.

## Architecture

The protocol implementation is intentionally simple:

1. `protocol.h` defines the packed `ads1278_command` and `ads1278_message` structs and compile-time size guards.
2. `cmd_parse.c` buffers short `recv()` chunks until a full 8-byte command is available, then validates opcode/value rules.
3. `server.c` turns validated commands into MMIO writes or local CSV actions, refreshes the latest coherent snapshot, and emits one 64-byte message per response.
4. `memory_map.c` sign-extends MMIO channel words before they are copied into `ads1278_message`, so clients do not have to reinterpret the raw 24-bit payload.
5. `server.c` copies DMA frame payloads into compact bulk records when `--dma-bulk` is enabled.

In legacy mode, protocol messages expose current state, not a guaranteed lossless frame history. In `--dma` mode, the same message layout is reused for completed DDR frames. In `--dma-bulk` mode, completed DDR frames are grouped so the server does not send one TCP message per sample.

## Known risk areas

- `msg_seq` is monotonic only for the current server process lifetime.
- `frame_cnt` is only 16 bits inside `status_raw`, so clients must tolerate wraparound.
- Bulk records carry a 32-bit `frame_count`, but the current UI model still exposes the lower 16 bits through `frame_cnt` for consistency with `status_raw`.
- `ACK` for `TRIGGER_SYNC` confirms that software wrote the command, not that a downstream analog effect has been verified.
- The protocol is little-endian by design; a big-endian port would need explicit byte swapping.

## Manual QA

- Connect with `nc` or a small Python client and confirm the ASCII capability line arrives first.
- Confirm the next binary payload is exactly 64 bytes for the initial `SAMPLE`.
- With `ads1278-server --dma-bulk`, confirm later `BULK_SAMPLES` headers are followed by `value * 40` payload bytes and the updated client expands them into normal samples.
- Send `SET_ENABLE 1` and confirm the next response is `ACK` with echoed opcode/value.
- Send `SET_EXTCLK_DIV 2` and confirm the next response is `ERROR`.
- Send `SET_MOD_DIV 6250000` and confirm the next response is `ACK` with `mod_div = 6250000`.
- Send `MARK_CAPTURE`, `SET_LOCAL_LOG_DURATION 60`, filename chunks, then `START_LOCAL_LOG 0`; confirm a CSV appears under `/mnt/usb/ads1278/logs` and continues after client disconnect until the deadline.
- With `CTRL & 0x6 == 0x6`, send `START_LOCAL_LOG 0x180` and confirm CH8 rows are reduced to the demod cadence; with `CTRL & 0x6 != 0x6`, confirm the server returns `ERROR`.
- Confirm negative channel inputs appear as negative signed 32-bit values in the binary message payload.

## Key files

| Area | File |
|------|------|
| Protocol constants and layout | `server/protocol.h` |
| Command buffering and validation | `server/cmd_parse.c` |
| Main protocol emission loop | `server/server.c` |
| USB CSV writer | `server/csv_logger.c` |
| Protocol layout test | `server/tests/test_protocol_layout.c` |
| Command parser test | `server/tests/test_cmd_parse.c` |

## Related docs

- [DMA Frame Record](dma-frame-record.md)
- [Server](server.md)
- [Server MMIO Contract](server-mmio-contract.md)
- [FPGA Register Map](fpga-register-map.md)
- [ADS1278 Acquisition Pipeline](ads1278-acquisition-pipeline.md)
- [Server implementation handoff](../handoffs/20260406b_server-implementation-and-documentation.md)
