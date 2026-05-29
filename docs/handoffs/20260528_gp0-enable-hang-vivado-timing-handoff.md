# GP0 enable hang — Vivado timing + IRQ handoff

**Date:** 2026-05-28  
**Board:** `rp-f0ef77` (and similar)  
**Build host:** remote Vivado (`MAGI` / `fpga-build.sh --remote`)  
**Status:** **Enable-only reboot reproduced** with `EXTCLK_DIV=5`, `CTRL` enable, no client. **Final routed timing still fails** (`WNS=-0.650` before phys_opt; `-0.076` after phys_opt). **IRQ still wired to per-frame `status_reg[0]`.**

**Prior handoffs:** `20260527_phase9-dma-server-and-mmio-hang-debug.md`, `20260527c_axi-slave-hang-risks-code-review.md`, `20260527b_axi-read-snapshot-and-dma-rate-limits.md`

---

## Summary

| Finding | Implication |
|---------|-------------|
| `devmem write` for `0x28` + `0x24` **returned** | GP0 **write path** likely OK for those transactions |
| Board **rebooted** with no client, only enable + div 5 | Failure is **after** enable — acquisition + PL activity, not server DMA loop |
| Final bitstream: **timing failed** signoff (`WNS=-0.650` route est.; `-0.076` after phys_opt) | Marginal paths can still cause instability even when AXI “works” |
| RTL: `assign irq = status_reg[0] \| (dma_irq_enable & dma_irq_pending)` | **~24 kHz IRQ storm** at div 5 when enabled — strong match for reboot |
| Synthesis: `ads1278_frame_fifo` **dissolved into registers** (async reset) | High-rate acquisition stresses timing/resources |

**Next owner:** (1) Fix IRQ in RTL and rebuild. (2) Pull timing report (commands below). (3) Retest enable-only at div 5, then soak at div 625/271. (4) FIFO BRAM + timing closure as needed.

---

## Repro that matters (no client)

Sequence on board (user report):

1. Deploy bitstream + server from repo (includes Phase A snapshot + server IRQ-status gating in software; **does not** fix PL `irq` line).
2. `EXTCLK_DIV = 5` via `devmem` (write returned).
3. `CTRL` enable (write returned).
4. No other activity — board **froze / watchdog ~5 s**.

**Interpretation:** Not a stuck `devmem read` on the write itself. Likely **sustained PL activity** after enable: SPI at ~12.5 MHz EXTCLK, frame FIFO push, and **IRQ_F2P** toggling every frame via `status_reg[0]`.

At div 5:

```text
EXTCLK ≈ 125 MHz / (2 × 5) = 12.5 MHz
Data rate ≈ EXTCLK / 512 ≈ 24.4 kHz frames/s
```

---

## Vivado build (2026-05-28, `work125_14`)

Remote path (on build machine):

```text
/home/saruul/rp_ads1278/fpga/work125_14/rp_ads1278.runs/impl_1/red_pitaya_top_timing_summary_routed.rpt
```

### Timing summary

| Stage | WNS (ns) | TNS (ns) | Notes |
|-------|----------|----------|--------|
| Post-route estimate | **-0.650** | -18.754 | Router warning: timing not met |
| After `phys_opt_design` | **-0.076** | -0.807 | Improved; still failing |
| Final `report_timing_summary` | **Failed** | — | Critical warning |

Bitstream was still generated (WebPACK allows this), but **do not treat as timing-clean**.

### Phys_opt focused on acquisition clocking

Log excerpts show critical-path work on:

- `u_ads1278/u_acq/u_spi_tdm/ads_sclk`, `wait_cnt`, `state2_carry`
- `u_ads1278/mod_cnt_reg`, `extclk_div_reg`
- `ps/system/processing_system7/inst/FCLK_CLK_unbuffered[0]`

These align with **aggressive `EXTCLK_DIV`** and SPI TDM using the same divider.

### Synthesis note — frame FIFO

```text
ads1278_frame_fifo: RAM "mem_reg" dissolved into registers
Reason: RAM is sensitive to asynchronous reset signal
```

64-deep × 320-bit FIFO implemented as **registers** instead of BRAM → bad for timing and power at high frame rates. Fix: synchronous reset/clear on FIFO.

### Other DRC (non-blocking for bitgen)

- `REQP-1839`: DMA writer FIFO / `frame_active_reg` async on BRAM controls — fix when touching DMA path.
- `dac_pwm_o[*]` IOB constraints — RP DAC path, not E1 acquisition.
- Unused expansion `BUFC-1` — benign.

---

## RTL fixes (priority order)

### 1. IRQ — stop per-frame pulses on PS (highest priority for enable-only reboot)

**Current** (`ads1278_axi_slave.sv`):

```systemverilog
assign irq = status_reg[0] | (dma_irq_enable & dma_irq_pending);
```

**Recommended:**

```systemverilog
// PS IRQ only for sticky DMA events (wrap / error / overwrite), not every SPI frame.
assign irq = dma_irq_enable & dma_irq_pending;
```

- Keep `status_reg[0]` on `STATUS` and LED if desired; do **not** drive `irq`.
- Server already gates on `DMA_IRQ_STATUS` before reading `0x60`; that does not change PL behavior.

### 2. Phase B/C AXI (already in repo, verify in deployed bitstream)

- Write `BVALID` gating, read/write serialization, read FSM — see `20260527c_axi-slave-hang-risks-code-review.md`.
- Confirm deployed `.bit` was built from RTL that includes these changes.

### 3. `ads1278_frame_fifo` — keep BRAM (timing + resources)

Replace async `rstn`/`clear` handling with a BRAM-friendly synchronous reset scheme so synthesis keeps `(* ram_style = "block" *) mem[]`.

---

## Pull timing report from Mac (SSH)

Set host and local dir:

```bash
export MAGI=your.build.host.example.edu   # same host as fpga-build.sh

mkdir -p /Users/saruul/Desktop/rp_ads1278/fpga/work125_14/rp_ads1278.runs/impl_1

scp "$MAGI:/home/saruul/rp_ads1278/fpga/work125_14/rp_ads1278.runs/impl_1/red_pitaya_top_timing_summary_routed.rpt" \
  /Users/saruul/Desktop/rp_ads1278/fpga/work125_14/rp_ads1278.runs/impl_1/
```

Optional — sync entire `impl_1` reports folder:

```bash
rsync -avz "$MAGI:/home/saruul/rp_ads1278/fpga/work125_14/rp_ads1278.runs/impl_1/" \
  /Users/saruul/Desktop/rp_ads1278/fpga/work125_14/rp_ads1278.runs/impl_1/
```

### Quick local analysis

```bash
# Violated paths (grep is enough for a first pass)
grep -E "^\|.*VIOLATED|WNS" \
  /Users/saruul/Desktop/rp_ads1278/fpga/work125_14/rp_ads1278.runs/impl_1/red_pitaya_top_timing_summary_routed.rpt \
  | head -40

# Paths into ads1278 (acquisition)
grep "u_ads1278" \
  /Users/saruul/Desktop/rp_ads1278/fpga/work125_14/rp_ads1278.runs/impl_1/red_pitaya_top_timing_summary_routed.rpt \
  | head -30
```

Share the grep output when opening a follow-up RTL task.

---

## Validation matrix (after IRQ + timing fixes)

| # | Config | Pass criterion |
|---|--------|----------------|
| 1 | Idle PL, `read 0x28` loop 10 min | No hang |
| 2 | `EXTCLK_DIV=5`, enable only, 10+ min | No reboot |
| 3 | `EXTCLK_DIV=5`, enable, tight `read 0x60` loop 10 min | No hang |
| 4 | `EXTCLK_DIV=271`, `--dma` + client 45+ min | No hang |
| 5 | `EXTCLK_DIV=125`, enable only, 10+ min | No hang |

Log: `{phase, extclk_div, test, hung_y/n, notes}`.

---

## Bench checks (enable-only debug)

```bash
# IRQ counter before/after enable (adjust irq name for your kernel)
grep -E "xilinx|fpga|irq" /proc/interrupts

devmem write 0x28 0x00000005   # EXTCLK_DIV — must return
devmem write 0x24 0x00000002   # CTRL enable — must return

# After enable (should not hang):
devmem read 0x2c    # FIFO_STATUS
devmem read 0x60    # DMA_BUF_STATUS (combinational in RTL — hot path in old designs)
```

---

## Success criteria

### Minimum (after IRQ fix + rebuild)

- [ ] `EXTCLK_DIV=5`, enable only, **10+ min**, no reboot
- [ ] `red_pitaya_top_timing_summary_routed.rpt` shows **WNS ≥ 0** (or agreed waiver with documented paths)

### Full sign-off

- [ ] Matrix rows 1–5 pass
- [ ] IRQ fix in bitstream (not only server software)
- [ ] Frame FIFO in BRAM (or accepted register cost documented)
- [ ] Phase 9 `--dma` soak at div 271 and 125

---

## Key files

| Area | Path |
|------|------|
| IRQ assignment | `fpga/rtl/ads1278_axi_slave.sv` |
| AXI slave (B/C) | `fpga/rtl/ads1278_axi_slave.sv` |
| Frame FIFO | `fpga/rtl/ads1278_frame_fifo.v` |
| Acquisition | `fpga/rtl/ads1278_acq_top.v`, `ads1278_spi_tdm.v` |
| Server DMA path | `server/server.c` |
| Routed timing | `fpga/work125_14/rp_ads1278.runs/impl_1/red_pitaya_top_timing_summary_routed.rpt` (remote) |
| Register map | `docs/feats/fpga-register-map.md` |

---

## Suggested order for next session

1. Apply IRQ one-liner + rebuild bitstream.
2. SCP timing report; fix top 10 paths (likely `u_ads1278/...`).
3. Enable-only retest at div 5 — if pass, IRQ was the smoking gun.
4. Close timing or document waiver; fix frame FIFO reset.
5. Full matrix with `--dma` and client at safe dividers.
