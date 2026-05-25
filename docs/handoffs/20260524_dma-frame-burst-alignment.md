# DMA frame DDR stride — problem, fixes, and bring-up status

**Date:** 2026-05-24  
**Blocks:** Phase 8 validation (capture FIFO → DDR), Phase 9 server DDR consumer  
**Status:** Fix implemented in repo; on-target parse test **not yet passing** — see [Open issues](#open-issues-on-target)

---

## Summary

Phase 8 proved that **live ADC data reaches DDR** (capture mode, `FIFO_DROPS` often 0, plausible `ch1` values). The blocker for calling Phase 8 “done” is **software cannot yet trust `dma-frames` output**: `pad=BAD`, `gap ≠ 1`, and canary `0xAD127831` not seen at word 31.

That is **not** the same as “capture is broken.” It is a **DDR layout vs parser stride** problem (and possibly **Zynq cache coherency** and **bring-up tooling**). The payload format (40 bytes, 10 words) is correct; the **DDR stride** must match how the PL stream writer packs bytes.

---

## Background

### Intended data path (Phase 8)

```
ADC → ads1278_acq_top (320-bit FIFO record)
    → ads1278_dma_fifo_axis (32-bit AXI stream)
    → ads1278_dma_phase4 / axis_ram_writer (128-byte HP0 bursts)
    → DDR at DMA_BASE_ADDR
    → host reads via rpdevmem dma-frames
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

## The problem

### Symptom (on-target)

After capture mode (`DMA_CTRL = 0x3`) and stopping DMA (`write 0x38 0x0`):

| Observation | Example |
|-------------|---------|
| `dma-frames` shows real-ish `ch1` | ~480–870 |
| `pad=BAD` on every line | All frames |
| `gap` not 1 | 25, 134, 192, … |
| `ddr-read 31` | `0x00020001`, **not** `0xad127831` |
| Pattern-mode `ddr-dump` | `0x078e0004`, `0x078e0005`, … (not `0,1,2,3`) |

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

This was confirmed by a key diagnostic:

> **`FIFO_DROPS = 0` but `gap ≠ 1`** → not dropped frames; **alignment / parser / stale DDR** issue.

### What is *not* the problem

| Misread | Reality |
|---------|---------|
| “ADC dropping frames” (when `FIFO_DROPS = 0`) | Parser stride wrong |
| “Phase 8 capture dead” | `dma_running`, real `ch1`, `dma_write_index` grows |
| “`0x078e0004` pattern test failed” | Pattern path works; `ddr-dump` shows 32-bit view of 64-bit-packed stream |
| Old pattern residue only | Stale DDR + misalignment can mimic pattern-like words |

### Secondary factors (also break bring-up)

1. **FIFO drops** — at `EXTCLK_DIV = 0x271`, `FIFO_DROPS` was **4271** in one run. Large `gap` between DDR records is **expected** even with correct stride (skipped `frame_cnt` values).
2. **Zynq cache coherency** — HP0 PL writes are not L1-coherent with Cortex-A9. CPU may read **cached stale DDR** unless invalidated before readback.
3. **`rpdevmem` DDR mmap** — `mmap(..., base_addr)` requires **4 KiB-aligned** `DMA_BASE_ADDR`. Unaligned base (e.g. `0x1e000800`) → `open ddr: Invalid argument`. `DMA_BUF_SIZE == 0` → same error.
4. **Deployed binary** — `server-deploy.sh` installs `/usr/local/bin/ads1278-rpdevmem`. Shell alias `devmem` may point at an **older** binary without 128-byte layout / cache sync / canary check.
5. **Stale DDR** — reading without a fresh capture, or reading before the writer filled the first 128 bytes, shows zeros or old pattern data at the buffer head.

---

## What we implemented (repo)

### 1. Initial mistake: assuming 40-byte stride in DDR

Early Phase 8 used 10 stream words per frame. Software indexed `frame[i]` every 10 words. That matched the **payload** doc but not the **burst writer** layout → misparse.

### 2. First fix attempt: 64-byte DDR stride (16 stream words)

**RTL:** `ads1278_dma_fifo_axis.v` emitted 16 words: 10 payload + 6 zero pad.  
**Rationale:** Two records = 128 bytes = one burst.

**On-target:** Still `pad=BAD`, `gap ≠ 1` with `FIFO_DROPS = 0` → 64-byte parser stride still did not match actual DDR byte layout (likely still effectively 40-byte stream in memory and/or cache stale reads).

### 3. Current fix: 128-byte DDR stride (32 stream words) + canary

**RTL** (`fpga/rtl/ads1278_dma_fifo_axis.v`):

| Stream words | Content |
|--------------|---------|
| 0–9 | 320-bit FIFO payload |
| 10–30 | Zero padding |
| 31 | Fixed canary **`0xAD127831`** |

**Rationale:** 32 stream words = 128 bytes = one `axis_ram_writer` minimum burst chunk → record *i* at byte offset **`i × 128`** for the life of the buffer.

**Software** (`server/dma_frame.h`):

- `ADS1278_DMA_FRAME_PAYLOAD_SIZE` = 40  
- `ADS1278_DMA_FRAME_SIZE` = **128**  
- `ADS1278_DMA_FRAME_STRIDE_CANARY` = `0xAD127831`  

**Bring-up** (`server/rpdevmem.c`):

- `dma-frames` prints `pad=ok` / `pad=BAD` / `pad=LEGACY`
- `dma-scan-canary` scans buffer for canary hits
- `__builtin___clear_cache()` on mmap’d DDR before read (Zynq coherency)

**Docs:** `docs/feats/dma-frame-record.md` updated (payload vs stride).

**Tests:** `server/tests/test_dma_frame_layout.c` asserts 128-byte struct layout.

### Files touched

| Area | Path |
|------|------|
| Serializer | `fpga/rtl/ads1278_dma_fifo_axis.v` |
| DMA mux | `fpga/rtl/ads1278_dma_phase4.v` (unchanged path; uses `u_capture`) |
| HP0 writer | `fpga/rtl/axis_ram_writer.v` (unchanged; 128-byte bursts) |
| C layout | `server/dma_frame.h` |
| Layout test | `server/tests/test_dma_frame_layout.c` |
| Bring-up | `server/rpdevmem.c` |
| Spec | `docs/feats/dma-frame-record.md` |
| Phase 8 handoff | `docs/handoffs/20260424_phase8-capture-dma.md` |
| Migration plan | `docs/handoffs/20260416_dma-route-migration-plan.md` (note) |

---

## On-target results so far

### What passed (hardware path)

| Check | Seen on `rp-f0f033` |
|-------|---------------------|
| Capture mode `dma_mode=1` | Yes |
| `dma_cfg_error=0`, `dma_error_count=0` | Yes |
| `dma_overwrites=0` (short tests) | Often |
| `FIFO_DROPS=0` | In at least one run |
| `ch1` looks like ADC data | Yes (~480–870) |
| `dma_write_index` grows | Yes (e.g. 102–130) |

→ **Phase 8 PL path is alive.**

### What failed (parse / bring-up)

| Check | Seen |
|-------|------|
| `pad=ok` | Never — always `pad=BAD` |
| `ddr-read 31` = `0xad127831` | No — e.g. `0x00020001` |
| `gap=1` with `FIFO_DROPS=0` | No — gaps 25–336 |
| `dma-scan-canary` | Not verified in logs (needs redeployed `rpdevmem`) |
| `open ddr: Invalid argument` | Seen when base/size invalid or unaligned |

### Interpretation table (`dma-frames` / `ddr-read`)

| Result | Likely meaning |
|--------|----------------|
| `pad=ok`, canary at words 31, 63, … | Stride fix + bitstream + tool OK |
| `pad=LEGACY` | New `rpdevmem`, **old** bitstream (64-byte era) |
| `pad=BAD`, no canary in scan | Stale cache, wrong binary, or stream still 40-byte |
| `gap ≫ 1`, `FIFO_DROPS = 0` | Stride/parser issue |
| `gap ≫ 1`, `FIFO_DROPS` large | Real drops + possible stride issue |
| `open ddr: Invalid argument` | Read `0x3c`/`0x40`; fix base alignment and non-zero size |

---

## Open issues on-target

1. **Confirm canary in DDR** after fresh capture with redeployed bitstream **and** `ads1278-rpdevmem` (cache sync build).
2. **Page-aligned DDR mmap** — `rpdevmem` passes `DMA_BASE_ADDR` directly to `mmap` offset; must be multiple of 4096 (`0x1e000000` OK; `0x1e000800` fails).
3. **`devmem` alias** — verify `which devmem` and `strings … | grep ad127831`.
4. **Do not read DDR without capture** — always run full arm → capture → stop → readback.
5. **Phase 8 “formal pass”** blocked until `pad=ok` + `gap=1` (with low `FIFO_DROPS`) on at least one clean run.

---

## Verification procedure

### Prerequisites

- Rebuild and deploy **FPGA bitstream** (includes `ads1278_dma_fifo_axis.v` 32-beat serializer).
- Rebuild and deploy **`ads1278-rpdevmem`** (128-byte `dma_frame.h`, cache sync, canary scan).

```sh
which devmem
strings "$(which devmem)" | grep -i ad127831
```

### Register setup + capture

```sh
devmem write 0x24 0x2          # acquisition enable
devmem write 0x28 0x271        # EXTCLK (slow down if FIFO_DROPS high)

devmem write 0x38 0x0
devmem write 0x58 0xf
devmem write 0x3c 0x1e000000   # DMA_BASE — must be 4 KiB aligned
devmem write 0x40 0x00010000   # DMA_BUF_SIZE — must be non-zero

devmem write 0x38 0x3          # DMA enable + capture mode
sleep 1
devmem read 0x30               # FIFO_DROPS — aim for 0

devmem write 0x38 0x0          # stop before DDR readback
```

### DDR readback

```sh
devmem read 0x3c               # sanity: 0x1e000000
devmem read 0x40               # sanity: 0x00010000
devmem dma-scan-canary         # hits at word 31, 63, … ?
devmem ddr-read 31             # expect 0xad127831
devmem dma-frames 16
```

### Pass criteria (Phase 8 parse test)

| # | Criterion |
|---|-----------|
| 1 | `dma-scan-canary`: first hit at word **31**, spacing **32** words |
| 2 | `ddr-read 31` = **`0xad127831`** |
| 3 | `dma-frames`: **`pad=ok`** on valid frames (skip all-zero `frame[0]`) |
| 4 | **`gap=1`** between consecutive valid records when `FIFO_DROPS` is low |
| 5 | Pattern regression: `DMA_CTRL=0x1` → `ddr-dump` shows incrementing stream (not necessarily `0,1,2,3` per 32-bit index) |

### Pattern mode regression (optional)

```sh
devmem write 0x24 0x0
devmem write 0x38 0x1
sleep 1
devmem write 0x38 0x0
devmem ddr-dump 8
```

Expect monotonic low-byte increment (e.g. `…04, …05, …06`), not `0x078e00xx` capture residue.

---

## Phase 9 implications

- Server must index ping-pong buffers with **`ADS1278_DMA_FRAME_SIZE` (128)**, not 40 or 64.
- Invalidate CPU cache (or map uncached) before reading PL-written DDR.
- Implement **`DMA_BUF_ACK`** loop; separate from stride fix.
- `ddr-dump` / default mmap at `DMA_BASE_ADDR` only covers buffer 0; buffer 1 needs page-aligned mmap at `base + DMA_BUF_SIZE`.

---

## Suggested next steps

1. Redeploy **both** bitstream and `ads1278-rpdevmem`; run [Verification procedure](#verification-procedure) and capture `dma-scan-canary` + `ddr-read 31` output.
2. If canary **never** appears in scan: confirm Vivado build includes `ads1278_dma_fifo_axis.v` and capture mode uses `u_capture` (not pattern-only path).
3. If canary appears every 32 words but `dma-frames` still `pad=BAD`: fix tool/binary mismatch.
4. If `open ddr: Invalid argument` persists: check `read 0x3c` / `read 0x40`; fix page-aligned base in `ads1278_ddr_open` (rpll-style page rounding) — Agent task.
5. Once `pad=ok` + `gap=1` with low drops: mark Phase 8 parse test **pass**; start Phase 9 ping-pong consumer.

---

## Related docs

- [DMA frame record (payload + stride spec)](../feats/dma-frame-record.md)
- [Phase 8 capture handoff](20260424_phase8-capture-dma.md)
- [DMA migration plan](20260416_dma-route-migration-plan.md)
