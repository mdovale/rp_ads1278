# DMA route fix plan — frame loss and CH1 spikes

**Date:** 2026-06-25  
**Status:** Open — **Step 1 done** (on-target div 5); active work: **Step 3 (FIFO / PL throughput)** + Step 2 (CH1 spikes). **Step 3a blocked:** depth-512 bitstream fails Vivado synth until `ads1278_frame_fifo.v` is refactored for BRAM inference.  
**Context:** Offline A/B CSV analysis in `data-loss-test/` and `docs/handoffs/20260625_capture-logging-and-dma-open-issues.md`

---

## What we know

- **Legacy mode** cannot deliver high-rate capture. The ADC runs at full speed, but the server only sends the latest sample when it polls. Effective ceiling is about **7–8 ksps**. This is a software limit, not an ADC limit.
- **DMA-bulk** can deliver **~100% rate at ~6–8 ksps** (div 15–20). It is the path to **~24 ksps** (div 5).
- **Two DMA bugs remain:**
  1. **Frame loss** — missing frames at div 10 and div 5. **On-target root cause at div 5: PL `FIFO_DROPS` (server consumer ruled out).**
  2. **CH1 spikes** — rare bad samples (~0.3% of rows) from DDR parse / buffer-boundary misalignment. CH8 stays normal. Good DMA rows match legacy.

Do not use legacy for high-rate work. Fix DMA.

---

## Step 1 — Reproduce on the board — **done**

**Board:** `rp-f0ef77`  
**Setup:** `ads1278-server --dma-bulk --poll-ms 0`, client connected + acquisition enabled, `EXTCLK_DIV = 5` (`devmem write 0x28 5`).

| Counter | Before capture | During capture | After capture |
|---------|----------------|----------------|---------------|
| `FIFO_DROPS` (0x30) | 0 | (not sampled live) | **0x29918 (170,264)** |
| `DMA_OVERWRITE_COUNT` (0x68) | 0 | 0 | **0** |
| `DMA_BUF_STATUS` (0x60) | 0 | 0 (buf never stuck full) | 0 |

**During capture (healthy DMA path, bad FIFO path):**

- `dma_enable: 1`, `dma_running: 1`, `dma_mode: 1` (capture)
- `dma_wrap_count` and `dma_write_index` increasing
- `dma_overwrites: 0` throughout
- `frame_start_phase=0`, `pad=ok`, canary every 32 words
- CH1 in `dma-frames` sample looked like real signal (no multi-million spikes in that snapshot)

**Triage (Step 1 table):**

| Finding | Classification |
|---------|----------------|
| `FIFO_DROPS` ↑ by 170k | **PL staged FIFO → DDR writer cannot sustain div 5** |
| `DMA_OVERWRITE_COUNT` flat | **Server ping-pong ACK is fast enough — not a consumer problem** |
| `pad=ok`, canary OK | Stride / bitstream layout OK; loss is not parse-only |

No divider sweep was needed: offline CSV already showed the rate cliff; on-target counters **confirm FIFO drops at div 5** with server ruled out.

**Note:** Read `FIFO_DROPS` **while capture is still running** on future soaks (`FIFO_DROPS` clears when acquisition disables). Log client CSV for the same run when checking Step 2 spikes.

---

## Step 2 — Fix CH1 spikes (parse / alignment)

Spikes are **not real signal**. They cluster at ping-pong buffer edges (`frame_cnt` jumps backward, `(+6, −4)` pattern).

**2026-06-25 server hardening update:** Per-buffer phase scoring, metadata validation, and a monotonic release queue were added, but the first on-board test froze the client because valid frames were mass-rejected as `reordered`:

```text
Server stats: dma_buffers=337 parsed=89424 released=514 streamed=514 bulk_messages=2 bad=87025 bad_canary=163 bad_metadata=0 gaps=33990 reordered=82901 duplicates=3961 coherence_rejects=0
```

The rejected records had coherent metadata (`frame_count == status_raw[31:16]`), so this was a release-queue bug rather than a parse/canary failure. The fix removes insert-time stale rejection, unwraps the 16-bit hardware counter into a 32-bit release sequence, services the older ping-pong half first when both halves are full, reports queue saturation separately from `reordered`, and rate-limits reject logging so stderr cannot stall the board. A follow-up **drain resync** patch addresses `queue_full` when only one half is serviced first — see [20260626 DMA reassembler handoff](20260626_dma-reassembler-fix-handoff.md).

**Check:**

1. `dma-scan-canary` — note `frame_start_phase` (often **30**, not 0; this board showed **0** at div 5).
2. Same phase used for **both** ping-pong buffers when parsing.
3. `dma-frames` shows `pad=ok` and `gap=1` for good runs **when `FIFO_DROPS Δ = 0`**.

**Fix in server** (`server/server.c`, `server/dma_frame.h`):

1. Find frame start **per buffer** from canary scan, not once at mmap open only.
2. Keep `ads1278_ddr_sync_for_cpu` before every buffer read.
3. Drop bad frames: padding not zero, canary wrong, metadata mismatch, overflow set, or CH1 out of range / huge step vs previous good frame.
4. Reassemble valid frames with a software-unwrapped sequence and compare-first ping-pong ordering before emit.
5. Log bounded per-buffer reject summaries plus `dma_bad_frames`, `reordered`, `duplicates`, `coherence_rejects`, and `queue_full` counters.

**Quick analysis workaround** until fixed: drop CSV rows with `|ch1| > 2000` or step `> 500` before plotting.

---

## Step 3 — Fix frame loss: PL FIFO / DDR writer throughput (active)

**Root cause (confirmed Step 1):** The **64-frame staged acquisition FIFO** fills faster than the **HP0 DMA writer** drains it at ~24.4 ksps. Drops are counted in `FIFO_DROPS` when `spi_new_data` pushes while the FIFO is full (`ads1278_acq_top.v`). This is **not** fixable in server software — `DMA_OVERWRITE_COUNT` stayed 0 with `--dma-bulk --poll-ms 0`.

### Data path (where to fix)

```text
SPI/TDM (div 5) → staged frame FIFO (64 deep, 320 bit)
                → ads1278_dma_fifo_axis (32 beats × 32 bit = 128 B/record)
                → axis_ram_writer (HP0 AXI bursts → DDR ping-pong)
                → server mmap + DMA_BUF_ACK
```

| Stage | File | Role |
|-------|------|------|
| Drop counter | `fpga/rtl/ads1278_acq_top.v` | `DMA_FIFO_DEPTH = 64`; increment `fifo_drop_count_reg` on push while full |
| Frame FIFO | `fpga/rtl/ads1278_frame_fifo.v` | Synchronous BRAM FIFO — **must infer as block RAM** (see Step 3a) |
| Serialize + canary | `fpga/rtl/ads1278_dma_fifo_axis.v` | One 320-bit pop → 32 stream beats (10 payload + pad + canary) |
| DDR writer | `fpga/rtl/ads1278_dma_phase4.v`, `fpga/rtl/axis_ram_writer.v` | AXI burst writer; `FIFO_WRITE_DEPTH = 1024` |
| Debug MMIO | `FIFO_STATUS (0x2c)`, `FIFO_CAPACITY (0x34)`, `FIFO_DROPS (0x30)` | Level / full / drop count |

### Step 3a — Fix FIFO synthesis for depth > 64 (blocking) — **open**

Raising `DMA_FIFO_DEPTH` in `ads1278_acq_top.v` (64 → 512) is the intended Step 3 buffer increase, but **synth fails** until the frame FIFO RTL is fixed.

**Observed (2026-06-25, Vivado synth on `rp125_14`):**

```text
ERROR: [Synth 8-3391] Unable to infer a block/distributed RAM for 'mem_reg' because the memory
  pattern used is not supported.
Reason: RAM is sensitive to asynchronous reset signal. this RTL style is not supported.
ERROR: [Synth 8-3391] Failed to dissolve the memory into bits because the number of bits
  (163840) is too large.   # 512 × 320 bits
```

Cascade: `ads1278_frame_fifo` → `ads1278_acq_top` → `ads1278_axi_slave` → `red_pitaya_top`.

**Why depth 64 “worked”:** same RTL style does not infer BRAM, but Vivado falls back to ~20k FFs (64 × 320). At depth 512 the flop dissolve hits the 163840-bit limit and synthesis aborts.

**Fix in `fpga/rtl/ads1278_frame_fifo.v`:**

1. Move `mem[...]` writes and reads into **separate `always @(posedge clk)` blocks** with **no async reset** on those blocks.
2. Keep pointer / `level` / `dout` control in a sync-reset block (`!rstn || clear`); do **not** reset RAM contents — `clear` from `~ctrl_enable` already flushes the queue logically.
3. Keep `(* ram_style = "block" *)` on `mem`. Target ~9 BRAM18 at depth 512 × 320 bit.

**Do not use:** `set_param ... dissolveMemorySizeLimit 163840` — that would implement the FIFO as ~164k FFs and is not viable on `xc7z010`.

**Acceptance:** `./fpga-build.sh --target rp125_14` completes `synth_1` with `DMA_FIFO_DEPTH = 512`; implementation reports BRAM inference for `u_frame_fifo/mem`, not massive FF count.

---

### Fix plan (FPGA-first, ordered)

1. **Baseline during div-5 soak (before RTL changes)** — **done** (Step 1)  
   Level pegged at 64, `full` set, `FIFO_DROPS` ↑ — writer is the sustained bottleneck.

2. **Step 3a: Refactor `ads1278_frame_fifo.v` for BRAM inference** — **required before depth increase**  
   See block above. Without this, 256/512 depth changes will not build reliably.

3. **Increase staged FIFO depth (quick buffer, may not suffice alone)**  
   After Step 3a, raise `DMA_FIFO_DEPTH` in `ads1278_acq_top.v` (64 → 256 or **512**). Rebuild bitstream. Re-test div 5: target `FIFO_DROPS Δ = 0`.  
   Depth only absorbs **short** DDR stalls; sustained div 5 still requires writer throughput ≥ sample rate.

4. **Improve HP0 writer sustained throughput (likely required for 24 ksps)**  
   - Profile AXI stalls: `dma_error_count`, `dma_last_bresp`, wrap rate vs sample rate.  
   - Tune `axis_ram_writer.v` (burst length, FIFO depth, back-pressure on `s_axis_tready`).  
   - Confirm HP0 clock / interconnect matches reference Red Pitaya DMA examples (see `.reference/`).  
   - Optional: reduce per-record stream overhead in `ads1278_dma_fifo_axis.v` only if it lowers cycles-per-frame without breaking 128-byte stride (see `docs/feats/dma-frame-record.md`).

5. **Verify ping-pong DDR path is not throttling the writer**  
   Server already ACKs promptly (`dma_buf0/1_full` were 0 during Step 1 snapshots). If `DMA_OVERWRITE_COUNT` rises after FIFO fix, revisit server (Step 3 secondary — unlikely today).

6. **Acceptance retest at div 5**  
   ```text
   ads1278-server --dma-bulk --poll-ms 0
   ```
   Client connected + enabled. Soak ≥ 60 s:
   - `FIFO_DROPS Δ = 0`
   - `DMA_OVERWRITE_COUNT Δ = 0`
   - CSV receive rate ≈ nominal ~24.4 ksps (sort/unwrap `frame_cnt` for loss stats)

### What does **not** fix FIFO drops

- Faster server poll / TCP bulk (consumer already keeps up)
- Legacy mode (decimates instead of lossless DMA)
- CH1 spike filters (Step 2 — separate bug)

See also: `docs/handoffs/20260527b_axi-read-snapshot-and-dma-rate-limits.md` (failure-mode table), `docs/feats/ads1278-acquisition-pipeline.md`.

---

## Step 4 — Prove each rate before calling done

Divider sweep is **not required for triage** (Step 1 closed at div 5). Use this table when validating RTL fixes:

| EXTCLK_DIV | ~fs | Pass criteria |
|------------|-----|---------------|
| 20 | ~6.1 ksps | ~100% rows vs duration; sorted `frame_cnt` gap ≤ 3; no CH1 spikes |
| 15 | ~8.1 ksps | same |
| 10 | ~12.2 ksps | ADC span ~100% of nominal; `FIFO_DROPS Δ = 0` |
| 5 | ~24.4 ksps | sustained capture; `FIFO_DROPS Δ = 0`; `DMA_OVERWRITE Δ = 0`; clean CSV |

Re-validate div 10 after div-5 FIFO fix if div 10 still shows loss in archived CSV.

---

## Step 5 — Done when

- [x] Step 1 on-target triage at div 5 (`FIFO_DROPS` vs `DMA_OVERWRITE`)
- [ ] Step 3a: `ads1278_frame_fifo.v` refactored; synth passes at `DMA_FIFO_DEPTH = 512`
- [ ] div 5: **≥ 24 ksps** with `FIFO_DROPS Δ = 0`, no overwrite during soak, clean CSV
- [ ] div 10: frame loss acceptable or fixed (`FIFO_DROPS Δ = 0`)
- [ ] CH1 spikes: Step 2 server hardening or confirmed absent at target rate
- [ ] Recommended server command documented in `docs/feats/server.md`
- [ ] Parent handoff Issue 5 acceptance criteria met

---

## Key files

| File | Role |
|------|------|
| `fpga/rtl/ads1278_acq_top.v` | Staged FIFO depth, `FIFO_DROPS` counter |
| `fpga/rtl/ads1278_dma_fifo_axis.v` | Frame → AXI stream serialization |
| `fpga/rtl/ads1278_dma_phase4.v` | Capture-mode DMA top, `axis_ram_writer` instance |
| `fpga/rtl/axis_ram_writer.v` | HP0 DDR burst writer |
| `server/server.c` | DMA consumer, bulk emit, buffer ack (not the div-5 loss bottleneck) |
| `server/dma_frame.h` | 128-byte record layout, canary |
| `server/rpdevmem.c` | `dma-frames`, `dma-scan-canary` bring-up tools |
| `data-loss-test/` | Reference legacy vs dma-bulk CSVs |

---

## Related docs

- [Capture / DMA open issues](20260625_capture-logging-and-dma-open-issues.md) — full analysis and tables
- [DMA frame burst alignment](20260524_dma-frame-burst-alignment.md) — 128-byte stride and canary phase
- [DMA rate limits / GP0 hang](20260527b_axi-read-snapshot-and-dma-rate-limits.md) — high divider risks
