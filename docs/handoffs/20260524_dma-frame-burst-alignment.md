# DMA frame DDR stride — problem, fixes, and bring-up status

**Date:** 2026-05-24 (updated 2026-05-27)  
**Blocks:** Phase 8 validation (capture FIFO → DDR), Phase 9 server DDR consumer  
**Status:** **Phase 8 parse + drop tests passed on-target** (`rp-f0ef77`, May 2026). Initial Phase 9 server DDR consumer is implemented; on-target server validation is next.

---

## Summary

Early Phase 8 runs showed **live ADC data in DDR** but **`dma-frames` misparse** (`pad=BAD`, `gap ≠ 1`) because host tools stepped the **40-byte payload** while the HP0 writer commits **128-byte bursts**.

The **128-byte stride + canary** fix in RTL and `devmem` (`ads1278-rpdevmem`) is validated on hardware:

- **`pad=ok`**, **`gap=1`**, sequential `frame_count` when **`FIFO_DROPS` does not increase**
- Canary scan finds **`0xAD127831` every 32 words**; first record often starts at **word 30** (`frame_start_phase=30`, canary at word **29**)
- **5-minute soak** at `EXTCLK_DIV=0x271`: **`FIFO_DROPS` stays 0**; **`DMA_OVERWRITE_COUNT` rises** without software `DMA_BUF_ACK` (expected ping-pong behavior, not ADC FIFO loss)

---

## On-target validation (2026-05, `rp-f0ef77`)

### Short parse test (2 s capture)

| Check | Result |
|-------|--------|
| `FIFO_DROPS` delta | **0** |
| `dma-frames` (64 lines) | **64× `pad=ok`**, **0× `pad=BAD`** |
| `frame_count` | **1 → 64**, all **`gap=1`** after first line |
| `dma-scan-canary` | **403 hits**; first at **word[29]**; **`frame_start_phase=30`** |
| `ddr-read 31` | `0x12540001` — **status word** of frame at word 30, not canary (see below) |
| `DMA_OVERWRITE_COUNT` | 0 (short run) |

### Long soak (300 s target, `dma-drop-test-long.sh` on board)

`CAPTURE_SEC=300`, `EXTCLK_DIV=0x271`, `DMA_BUF_SIZE=0x10000`. Progress lines every 30 s (script samples while `DMA_CTRL=0x3`):

| Elapsed | FIFO_DROPS | DMA_OVERWRITE_COUNT | DMA_WRAP_COUNT | DMA_WRITE_INDEX |
|---------|------------|---------------------|----------------|-----------------|
| 30 s | 0 | 0x0a (10) | 0x0b (11) | 0xfe (254) |
| 60 s | 0 | 0x15 (21) | 0x16 (22) | 0x1f4 (500) |
| 90 s | 0 | 0x21 (33) | 0x22 (34) | 0xea (234) |

Raw log excerpt (90 s checkpoint):

```text
--- Capturing (DMA_CTRL=0x3) for 300s ---
[  30s] FIFO_DROPS=0x00000000  OVERWRITES=0x0000000a  WRAP_COUNT=0x0000000b  WRITE_INDEX=0x000000fe
[  60s] FIFO_DROPS=0x00000000  OVERWRITES=0x00000015  WRAP_COUNT=0x00000016  WRITE_INDEX=0x000001f4
[  90s] FIFO_DROPS=0x00000000  OVERWRITES=0x00000021  WRAP_COUNT=0x00000022  WRITE_INDEX=0x000000ea
```

Interpretation:

- **`FIFO_DROPS = 0`** throughout the sampled window → staged acquisition FIFO did not lose frames to DDR back-pressure at this rate.
- **`DMA_OVERWRITE_COUNT` and `DMA_WRAP_COUNT` increase** → ping-pong halves wrap faster than software releases them (**no `DMA_BUF_ACK`** during bring-up). That is **not** the same as `FIFO_DROPS`; Phase 9 must ACK completed buffers on long captures.
- **`DMA_WRITE_INDEX` wraps** within a 64 KiB buffer (512 frames × 128 B); index alone is not a drop indicator.

### Earlier failed run (context)

| Check | Result |
|-------|--------|
| 1 s capture, same divider | `FIFO_DROPS = 0xa53` (2643) |
| Same session, later 2 s clean script | `FIFO_DROPS` delta **0**, parse **pass** |

Use board-local **`dma-drop-test.sh`** / **`dma-drop-test-long.sh`** (see [Verification procedure](#verification-procedure)). Read **`FIFO_DROPS` before disabling `CTRL`** (counter clears when acquisition is disabled).

---

## Background

### Intended data path (Phase 8)

```
ADC → ads1278_acq_top (320-bit FIFO record)
    → ads1278_dma_fifo_axis (32-bit AXI stream)
    → ads1278_dma_phase4 / axis_ram_writer (128-byte HP0 bursts)
    → DDR at DMA_BASE_ADDR
    → host reads via devmem dma-frames
```

### Logical frame (unchanged)

Defined in `docs/feats/dma-frame-record.md` — **40-byte payload**, 10 × 32-bit words:

| Word | Field |
|------|--------|
| 0 | `frame_count` |
| 1 | `status_raw` |
| 2–9 | `ch1` … `ch8` (sign-extended 24-bit samples) |

The acquisition FIFO still stores **320 bits** per push. Only the **DMA serializer** expands each record to the DDR stride.

### How the PL writer packs DDR

`axis_ram_writer.v` buffers 32-bit stream words in an asymmetric FIFO (write 32 / read 64) and issues **fixed 128-byte AXI bursts** (16 × 64-bit beats) when more than 15 sixty-four-bit words are available.

So the DDR image is a **continuous byte stream** of 32-bit words, committed in **128-byte chunks** — not “one struct per write” unless the stream stride is chosen to match.

---

## The problem (historical)

### Symptom (pre-fix, on-target)

After capture mode (`DMA_CTRL = 0x3`) and stopping DMA (`write 0x38 0x0`):

| Observation | Example |
|-------------|---------|
| `dma-frames` shows real-ish `ch1` | ~480–870 |
| `pad=BAD` on every line | All frames |
| `gap` not 1 | 25, 134, 192, … |
| `ddr-read 31` | `0x00020001`, **not** `0xad127831` |
| Pattern-mode `ddr-dump` | `0x078e0004`, `0x078e0005`, … |

### Root cause: payload size ≠ burst / parser stride

| Quantity | Size |
|----------|------|
| Payload per capture | **40 bytes** (10 stream words) |
| HP0 burst | **128 bytes** (32 stream words) |

If the serializer emits **only 10 words per frame** (40 bytes) back-to-back in the byte stream:

- `gcd(128, 40) = 8` → record boundaries **drift** relative to 128-byte burst boundaries.
- Host tools that index `frame[i]` at byte offset `i × 40` or `i × 64` read **wrong word offsets**.
- Bytes interpreted as “padding” contain **next frame’s payload** → `pad=BAD`.
- `frame_count` / `status` / `ch1` look plausible but are **misaligned** → chaotic `gap`.

Key diagnostic (still useful):

> **`FIFO_DROPS = 0` but `gap ≠ 1`** → not dropped frames; **alignment / parser / stale DDR** issue.

### Secondary factors

1. **FIFO drops** — large `FIFO_DROPS` with fast capture → real loss before DDR; `gap` in DDR may exceed 1 even with correct stride.
2. **Zynq cache coherency** — `__builtin___clear_cache()` on mmap’d DDR in `rpdevmem.c`.
3. **DDR mmap** — `DMA_BASE_ADDR` must be **4 KiB-aligned**; `DMA_BUF_SIZE` non-zero.
4. **`devmem` alias** — must point at deployed `ads1278-rpdevmem` (`strings … | grep ad127831`).
5. **Stale DDR** — arm → capture → **stop DMA** → then readback.

---

## What we implemented (repo)

### 128-byte DDR stride (32 stream words) + canary

**RTL** (`fpga/rtl/ads1278_dma_fifo_axis.v`):

| Stream words | Content |
|--------------|---------|
| 0–9 | 320-bit FIFO payload |
| 10–30 | Zero padding |
| 31 | Fixed canary **`0xAD127831`** |

**Software** (`server/dma_frame.h`, `server/rpdevmem.c`):

- `ADS1278_DMA_FRAME_SIZE` = **128**
- `dma-frames` / `dma-scan-canary`; cache sync before DDR read
- `dma-frames` uses **`frame_start_phase`** from canary scan (not always word 0)

**Board scripts (on-target only, not yet in repo):** `dma-drop-test.sh`, `dma-drop-test-long.sh`

### Files touched

| Area | Path |
|------|------|
| Serializer | `fpga/rtl/ads1278_dma_fifo_axis.v` |
| C layout | `server/dma_frame.h` |
| Bring-up | `server/rpdevmem.c` |
| Spec | `docs/feats/dma-frame-record.md` |

---

## Verification procedure

### Prerequisites

```sh
ln -sf /usr/local/bin/ads1278-rpdevmem /usr/local/bin/devmem
which devmem
strings "$(which devmem)" | grep -i ad127831
```

Deploy current **bitstream** and **`ads1278-rpdevmem`** from this repo.

### Quick automated tests

```sh
# Copy scripts to board, then:
chmod +x dma-drop-test.sh dma-drop-test-long.sh
./dma-drop-test.sh                    # ~2 s, parse + FIFO_DROPS
CAPTURE_SEC=300 ./dma-drop-test-long.sh   # 5 min soak
```

### Manual capture + readback

```sh
devmem write 0x24 0x2
devmem write 0x28 0x271

devmem write 0x38 0x0
devmem write 0x58 0xf
devmem write 0x3c 0x1e000000
devmem write 0x40 0x00010000

devmem write 0x38 0x3
sleep 2
devmem read 0x30               # FIFO_DROPS — want 0

devmem write 0x38 0x0
devmem dma-scan-canary
devmem ddr-read 29             # canary when frame_start_phase=30
devmem dma-frames 16
```

### Pass criteria (Phase 8)

| # | Criterion |
|---|-----------|
| 1 | `dma-scan-canary`: hits every **32** words; note **`frame_start_phase`** (often **30**) |
| 2 | `ddr-read` at **first canary word** = **`0xad127831`** (not always word 31) |
| 3 | `dma-frames`: **`pad=ok`** on captured frames |
| 4 | **`gap=1`** between consecutive records when **`FIFO_DROPS` delta = 0** |
| 5 | Long soak: **`FIFO_DROPS` flat**; expect **`DMA_OVERWRITE_COUNT` > 0** without `DMA_BUF_ACK` |

### Interpretation table

| Result | Likely meaning |
|--------|----------------|
| `pad=ok`, `gap=1`, `FIFO_DROPS=0` | Stride + deploy OK |
| `pad=LEGACY` | New `devmem`, old bitstream (64-byte era) |
| `pad=BAD`, canary missing | Wrong binary, stale DDR, or pre-128-byte bitstream |
| `gap ≫ 1`, `FIFO_DROPS = 0` | Parser phase / stale buffer |
| `gap ≫ 1`, `FIFO_DROPS` large | Real FIFO drops |
| `OVERWRITES` rise, `FIFO_DROPS = 0` | Ping-pong not ACK'd (Phase 9) |

---

## Phase 9 implications

- Server indexes buffers with **`ADS1278_DMA_FRAME_SIZE` (128)** and the same **canary phase** logic as `dma-frames`.
- Cache invalidate (or uncached map) before reading PL-written DDR.
- Implement **`DMA_BUF_ACK`** loop for long captures; distinguish from **`FIFO_DROPS`**.
- mmap buffer 1 at `DMA_BASE_ADDR + DMA_BUF_SIZE` (page-aligned).

---

## Suggested next steps

1. Run `ads1278-server --dma` on target with a client connected and confirm full buffers are ACKed.
2. Re-run a long soak **with** server ACK and confirm `DMA_OVERWRITE_COUNT` stays flat while `FIFO_DROPS` remains 0.
3. Optional: page-round DDR mmap in `rpdevmem` for unaligned `DMA_BASE_ADDR`.
4. Optional repo hygiene: commit `dma-drop-test.sh` / `dma-drop-test-long.sh` under `tools/board/` so handoffs and CI can reference them.

---

## Related docs

- [DMA frame record (payload + stride spec)](../feats/dma-frame-record.md)
- [Phase 8 capture handoff](20260424_phase8-capture-dma.md)
- [DMA migration plan](20260416_dma-route-migration-plan.md)
