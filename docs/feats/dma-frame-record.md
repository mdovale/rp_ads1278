# DMA Frame Record

This doc defines the in-memory record for DMA-backed capture in `rp_ads1278`. Software, RTL, and tests must share the same **payload** layout and the same **DDR stride** (they are not the same size).

## Goal

Define one unambiguous capture record so PL writers and host parsers agree on field order, and so completed DDR buffers can be indexed without burst-alignment math.

## Scope

- In scope: payload fields, DDR stride / padding, burst alignment rationale, C struct layout.
- Out of scope: ping-pong ownership, MMIO DMA registers, TCP bulk transport.

## Payload layout (40 bytes, 10 words)

Logical sample content per captured frame (little-endian 32-bit words):

| Byte offset | Word | Field | Type | Meaning |
|------|------|------|------|------|
| `0x00` | `0` | `frame_count` | `uint32_t` | Frame sequence (`spi_frame_cnt` zero-extended) |
| `0x04` | `1` | `status_raw` | `uint32_t` | Raw status at capture (`new_data`, `overflow`, `frame_cnt` in upper half) |
| `0x08` | `2` | `ch1` | `int32_t` | Channel 1, sign-extended 24-bit sample |
| `0x0C` | `3` | `ch2` | `int32_t` | Channel 2 |
| `0x10` | `4` | `ch3` | `int32_t` | Channel 3 |
| `0x14` | `5` | `ch4` | `int32_t` | Channel 4 |
| `0x18` | `6` | `ch5` | `int32_t` | Channel 5 |
| `0x1C` | `7` | `ch6` | `int32_t` | Channel 6 |
| `0x20` | `8` | `ch7` | `int32_t` | Channel 7 |
| `0x24` | `9` | `ch8` | `int32_t` | Channel 8 |

The staged acquisition FIFO (`ads1278_acq_top`) still stores **320 bits (10 words)** per push. The DMA serializer expands each record to the DDR stride below.

## DDR stride (128 bytes, 32 words)

Each capture is written to DDR as **32 consecutive 32-bit words**:

| Byte offset | Word | Content |
|------|------|------|
| `0x00`–`0x27` | `0`–`9` | Payload (table above) |
| `0x28`–`0x7B` | `10`–`30` | **Padding** — PL drives `0` |
| `0x7C` | `31` | **Stride canary** — fixed `0xAD127831` |

Constants in `server/dma_frame.h`:

- `ADS1278_DMA_FRAME_PAYLOAD_SIZE` = 40  
- `ADS1278_DMA_FRAME_SIZE` = 128 (stride for indexing DDR)  
- `ADS1278_DMA_FRAME_WORDS` = 32  
- `ADS1278_DMA_FRAME_STRIDE_CANARY` = `0xAD127831`  

Host code should use `sizeof(ads1278_dma_frame)` or `ADS1278_DMA_FRAME_SIZE` when advancing through a DMA buffer, not the 40-byte payload size alone.

## Why 128-byte stride (burst alignment)

The HP0 writer (`axis_ram_writer`) commits **128-byte AXI bursts** (16 × 64-bit beats). It starts a burst when the internal FIFO holds more than **15** sixty-four-bit words, which requires **32** thirty-two-bit stream words.

| Size | Value |
|------|--------|
| Payload per frame | 40 bytes (10 stream words) |
| DDR stride | 128 bytes (32 stream words) |
| AXI burst | 128 bytes (32 stream words) |

**One padded record = one burst chunk** → record *i* always starts at byte offset `i × 128`.

Earlier bring-up used a **64-byte** stride (two records per burst). On-target tests with `FIFO_DROPS = 0` still showed `pad=BAD` and `gap ≠ 1`, which indicates the host was still effectively parsing a **40-byte** byte stream (payload-only) while stepping **64 bytes** — padding bytes then contained the next frame’s payload. The **128-byte** stride removes that ambiguity.

### Misaligned parsing symptoms (do not confuse with FIFO drops)

| Symptom | Typical cause |
|---------|----------------|
| `pad=BAD` on every line | Stride mismatch (often 40 B stream + 64/128 B parser) |
| `gap` huge with `FIFO_DROPS = 0` | Stride mismatch (not dropped frames) |
| `gap` huge with large `FIFO_DROPS` | Real drops **and/or** stride mismatch |
| `pad=LEGACY` in `dma-frames` | 64-byte-era bitstream (no `0xAD127831` canary) |

## Software parsing rules

- Treat the DMA buffer as a dense array of `ads1278_dma_frame` with **128-byte** stride.
- A frame is releasable to TCP or CSV only when padding/canary validate, `frame_count` is the zero-extended copy of `status_raw[31:16]`, `new_data` is set, `overflow` is clear, and the server can release it as part of a monotonic 16-bit frame-count sequence.
- With `pad=ok`, `frame_count` should increase by **1** between consecutive released records (16-bit counter may wrap). Forward gaps are logged before release; stale, duplicate, or reordered records are rejected.
- `pad=LEGACY` means rebuild/deploy the current bitstream and `rpdevmem`.
- Skip all-zero `frame[0]` if the writer had not yet completed the first burst.

## Architecture

1. MMIO remains the control / debug plane.  
2. DMA capture writes contiguous 128-byte-strided records into DDR via HP0.  
3. Phase 9 server code should mmap completed ping-pong buffers and parse with this stride.

## Key files

| Area | File |
|------|------|
| Format spec | `docs/feats/dma-frame-record.md` |
| Alignment handoff | `docs/handoffs/20260524_dma-frame-burst-alignment.md` |
| FIFO → stream | `fpga/rtl/ads1278_dma_fifo_axis.v` |
| HP0 burst writer | `fpga/rtl/axis_ram_writer.v` |
| C layout | `server/dma_frame.h` |
| Layout test | `server/tests/test_dma_frame_layout.c` |
| Bring-up | `server/rpdevmem.c` (`dma-frames`) |

## Related docs

- [Server MMIO Contract](server-mmio-contract.md)
- [DMA route migration plan](../handoffs/20260416_dma-route-migration-plan.md)
- [Phase 8 capture handoff](../handoffs/20260424_phase8-capture-dma.md)
