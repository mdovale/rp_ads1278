# DMA Frame Record

This doc defines the first fixed-size in-memory record for DMA-backed capture in `rp_ads1278`. It is the Phase 2 contract that later RTL, DDR buffer handling, and server parsing should share before the DMA datapath itself is implemented.

## Goal

Define one unambiguous DMA frame layout in bytes and 32-bit words so future PL writers and software parsers can agree on the same record format without reopening field-order questions during bring-up.

## Scope

- In scope: one captured frame layout in DDR memory, field order, field sizes, channel representation, and the Phase 2 decisions needed before RTL changes.
- Out of scope: the DMA engine itself, ping-pong ownership rules, MMIO control registers for DMA, interrupt behavior, and any future bulk TCP protocol.

## User-facing behavior

The first DMA record is one fixed 40-byte frame stored as 10 little-endian 32-bit words:

| Byte offset | Word | Field | Type | Meaning |
|------|------|------|------|------|
| `0x00` | `0` | `frame_count` | `uint32_t` | Acquisition frame sequence number for this captured frame |
| `0x04` | `1` | `status_raw` | `uint32_t` | Raw per-frame status word captured alongside the samples |
| `0x08` | `2` | `ch1` | `int32_t` | Channel 1 sample, sign-extended from the ADS1278 24-bit code |
| `0x0C` | `3` | `ch2` | `int32_t` | Channel 2 sample |
| `0x10` | `4` | `ch3` | `int32_t` | Channel 3 sample |
| `0x14` | `5` | `ch4` | `int32_t` | Channel 4 sample |
| `0x18` | `6` | `ch5` | `int32_t` | Channel 5 sample |
| `0x1C` | `7` | `ch6` | `int32_t` | Channel 6 sample |
| `0x20` | `8` | `ch7` | `int32_t` | Channel 7 sample |
| `0x24` | `9` | `ch8` | `int32_t` | Channel 8 sample |

Phase 2 decisions locked by this doc:

- Store channel payloads as signed 32-bit integers in memory for simple server parsing and parity with the current wire protocol.
- Include the full `status_raw` word in every frame for early debug visibility.
- Do not include `extclk_div` in every frame; treat it as control metadata read through MMIO.
- Do not include a timestamp in the first-pass record.

Additional interpretation rules:

- `frame_count` is the producer-owned per-frame sequence field for DMA parsing. If the initial hardware implementation still sources only the current 16-bit MMIO `frame_cnt`, producers should zero-extend it into this 32-bit slot until a wider native counter exists.
- `status_raw` preserves the hardware-facing status bits seen at capture time even if some information overlaps with `frame_count`.
- DMA buffers should be treated as tightly packed arrays of this record with no per-record padding.

Phase 3 should assume:

- PL writes one whole `ads1278_dma_frame` record per captured acquisition frame.
- FIFO payload width and pack/unpack logic should preserve the field order shown above exactly.
- The first DMA buffer implementation can count records in units of `ADS1278_DMA_FRAME_SIZE` bytes rather than introducing any variable-length framing.

## Architecture

This record is intentionally separate from the current MMIO register map and the current TCP `ads1278_v1` message:

1. The MMIO path remains the compatibility control/debug plane.
2. The DMA path writes contiguous `ads1278_dma_frame` records into DDR.
3. Future server DMA code should parse completed buffers using this record definition before deciding how to expose them over the network.

The repo should keep one source-of-truth layout in code as well as this doc so RTL, C parsing, and tests cannot drift independently.

## Key files

| Area | File |
|------|------|
| Phase 2 format spec | `docs/feats/dma-frame-record.md` |
| DMA migration plan | `docs/handoffs/20260416_dma-route-migration-plan.md` |
| Legacy MMIO compatibility contract | `docs/feats/server-mmio-contract.md` |
| C layout constants | `server/dma_frame.h` |
| C layout test | `server/tests/test_dma_frame_layout.c` |

## Related docs

- [Server MMIO Contract](server-mmio-contract.md)
- [Server Protocol](server-protocol.md)
- [Server](server.md)
- [README](../../README.md)
- [DMA route migration plan](../handoffs/20260416_dma-route-migration-plan.md)
