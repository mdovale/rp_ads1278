# Server Protocol

This doc describes the current TCP protocol implemented by `server/` in `rp_ads1278`. It covers the capability handshake, fixed-size binary commands, fixed-size binary responses, and the current emission rules used by the MMIO-polling server.

## Goal

Define the current network contract clearly enough that the implemented Python client can connect, send control commands, and decode streamed ADS1278 snapshots without inferring layout details from the C source.

## Scope

- In scope: the capability line, default TCP port, binary command encoding, binary message encoding, little-endian assumptions, and current emission rules.
- Out of scope: the FPGA register map itself, GUI behavior, Linux service setup, and any future protocol revision beyond `ads1278_v1`.

## User-facing behavior

Current transport assumptions are:

- TCP listener port: `5000`
- Capability line: ASCII, newline-terminated
- All binary traffic after the capability line: little-endian
- Channel samples on the wire: signed 32-bit integers produced by server-side sign extension of the FPGA's zero-extended 24-bit channel words

Connection startup is:

1. Client connects to the TCP port.
2. Server sends `RP_CAP:ads1278_v1\n`.
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

Unknown opcodes are rejected.

Server-to-client binary messages are fixed 60-byte payloads:

| Word | Field | Meaning |
|------|------|------|
| `0` | `msg_type` | `1 = SAMPLE`, `2 = ACK`, `3 = ERROR` |
| `1` | `msg_seq` | Monotonic server-side message counter |
| `2` | `opcode` | `0` for `SAMPLE`; echoed command opcode for `ACK`/`ERROR` |
| `3` | `value` | `0` for `SAMPLE`; echoed command value for `ACK`/`ERROR` |
| `4` | `status_raw` | Raw FPGA `STATUS` word from the latest coherent snapshot |
| `5` | `ctrl_raw` | Raw FPGA `CTRL` word from the latest coherent snapshot |
| `6` | `extclk_div` | Raw FPGA divider word from the latest coherent snapshot |
| `7` | `ch1` | Signed 32-bit channel sample |
| `8` | `ch2` | Signed 32-bit channel sample |
| `9` | `ch3` | Signed 32-bit channel sample |
| `10` | `ch4` | Signed 32-bit channel sample |
| `11` | `ch5` | Signed 32-bit channel sample |
| `12` | `ch6` | Signed 32-bit channel sample |
| `13` | `ch7` | Signed 32-bit channel sample |
| `14` | `ch8` | Signed 32-bit channel sample |

Emission rules are:

- Send one initial `SAMPLE` immediately after the capability line.
- Send `ACK` immediately after every valid command.
- Send `ERROR` immediately after every invalid command.
- Send `SAMPLE` when `frame_cnt` changes.
- `ACK` and `ERROR` carry the same snapshot fields as `SAMPLE`, so a client can always treat the message as both a response and a state update.

## Architecture

The protocol implementation is intentionally simple:

1. `protocol.h` defines the packed `ads1278_command` and `ads1278_message` structs and compile-time size guards.
2. `cmd_parse.c` buffers short `recv()` chunks until a full 8-byte command is available, then validates opcode/value rules.
3. `server.c` turns validated commands into MMIO writes, refreshes the latest coherent snapshot, and emits one 60-byte message per response.
4. `memory_map.c` sign-extends channel words before they are copied into `ads1278_message`, so clients do not have to reinterpret the raw 24-bit payload.

Because the current server is a latest-sample streamer, protocol messages expose current state, not a guaranteed lossless frame history.

## Known risk areas

- `msg_seq` is monotonic only for the current server process lifetime.
- `frame_cnt` is only 16 bits inside `status_raw`, so clients must tolerate wraparound.
- `ACK` for `TRIGGER_SYNC` confirms that software wrote the command, not that a downstream analog effect has been verified.
- The protocol is little-endian by design; a big-endian port would need explicit byte swapping.

## Manual QA

- Connect with `nc` or a small Python client and confirm the ASCII capability line arrives first.
- Confirm the next binary payload is exactly 60 bytes.
- Send `SET_ENABLE 1` and confirm the next response is `ACK` with echoed opcode/value.
- Send `SET_EXTCLK_DIV 2` and confirm the next response is `ERROR`.
- Confirm negative channel inputs appear as negative signed 32-bit values in the binary message payload.

## Key files

| Area | File |
|------|------|
| Protocol constants and layout | `server/protocol.h` |
| Command buffering and validation | `server/cmd_parse.c` |
| Main protocol emission loop | `server/server.c` |
| Protocol layout test | `server/tests/test_protocol_layout.c` |
| Command parser test | `server/tests/test_cmd_parse.c` |

## Related docs

- [DMA Frame Record](dma-frame-record.md)
- [Server](server.md)
- [Server MMIO Contract](server-mmio-contract.md)
- [FPGA Register Map](fpga-register-map.md)
- [ADS1278 Acquisition Pipeline](ads1278-acquisition-pipeline.md)
- [Server implementation handoff](../handoffs/20260406b_server-implementation-and-documentation.md)
