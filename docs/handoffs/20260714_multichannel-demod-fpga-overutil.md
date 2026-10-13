# Multi-channel demod FPGA over-utilization handoff

**Date:** 2026-07-14  
**Board / part:** `rp125_14` → `xc7z010clg400-1` (Zynq-7010)  
**Build host:** remote Vivado 2020.1 (`fpga-build.sh --target rp125_14 --remote "$MAGI"`)  
**Status:** Shared-divider RTL refactor is implemented locally, but not yet validated by simulation or Vivado in this environment. The last completed Vivado run still failed at `place_design` with `DRC UTLZ-1` LUT/CARRY4 over-utilization (~2× device capacity). **No verified new bitstream produced yet.**

**Prior context:** [`20260622_demodulation-plan.md`](20260622_demodulation-plan.md) (original CH8-only demod), [`20260629_demod-post-edge-skip.md`](20260629_demod-post-edge-skip.md) (`DEMOD_SKIP`), multi-channel demod + CSV/UI/docs work in repo (local, uncommitted at handoff time).

---

## Summary

| Finding | Implication |
|---------|-------------|
| `synth_1` **Complete** | RTL elaborates; failure is resource fit, not syntax |
| `place_design` **ERROR** — 3× `UTLZ-1` | Design needs ~34k LUTs and ~8.6k CARRY4; 7010 has 17.6k LUTs and 4.4k CARRY4 |
| Original root cause: **8× `ads1278_demod`** | Each instance had **two** combinational 48÷16 signed dividers → ~16 parallel dividers |
| Refactor now in tree | `ads1278_demod_bank` keeps per-channel accumulators and shares one iterative `ads1278_demod_divider` |
| BRAM: 6 blocks used / 120 avail | **Not** the bottleneck |
| REQP-1839/1840 warnings (42) | BRAM async-reset hygiene; **warnings only**, not blocking |
| `fpga-deploy.sh` can still load **old** `ads1278.bit.bin` | Local artifact from pre-change build; **do not treat as multi-channel demod** |

**Next owner:** Run RTL simulation and the remote Vivado build, confirm utilization &lt; 100%, then perform on-target demod-all-channels validation.

---

## Symptom

Remote build command:

```bash
./fpga-build.sh --target rp125_14 \
  --remote "$MAGI" \
  --remote-user saruul \
  --remote-vivado vivado2020
```

Result:

```text
ERROR: impl_1 finished with status: place_design ERROR
```

Blocking DRC (during `place_design` precondition):

```text
ERROR: [DRC UTLZ-1] Resource utilization: CARRY4 over-utilized ...
  requires 8619 ... only 4400 available

ERROR: [DRC UTLZ-1] Resource utilization: LUT as Logic over-utilized ...
  requires 33997 ... only 17600 available

ERROR: [DRC UTLZ-1] Resource utilization: Slice LUTs over-utilized ...
  requires 34060 ... only 17600 available
```

Synthesis cell usage (same build) for reference:

| Cell | Count |
|------|------:|
| CARRY4 | 8,607 |
| LUT2 | 17,181 |
| LUT3 | 12,886 |
| LUT4 | 2,309 |
| LUT5 | 989 |
| LUT6 | 837 |
| RAMB36E1 | 5 |
| RAMB18E1 | 1 |

---

## Root cause

### What changed

The over-utilizing version instantiated **eight** independent `ads1278_demod` modules (`u_demod_ch0` … `u_demod_ch7`). When `CTRL[2]` (demod enable) is set, each channel’s MMIO read and DMA payload use that channel’s demod output instead of raw SPI data.

Previously only one channel (CH8 path in the original plan) used demod. Replicating the module eight times scales divider logic ~8×.

### Why dividers dominate

`ads1278_demod.v` computes half-cycle averages with **combinational signed division**:

```verilog
wire signed [31:0] pos_avg_next =
    (count_pos != 16'd0) ? (sum_pos / $signed({16'd0, count_pos})) : avg_pos;
wire signed [31:0] neg_avg_next =
    (count_neg != 16'd0) ? (sum_neg / $signed({16'd0, count_neg})) : avg_neg;
```

- `sum_*` is 48-bit signed; `count_*` is 16-bit → Vivado infers large LUT/CARRY4 divider networks.
- **8 instances × 2 dividers = 16 parallel dividers** → ~193% LUT and ~196% CARRY4 on `xc7z010`.

Accumulators (48-bit adders) also replicate (synthesis reports 48× 48-bit adders), but the dividers are the main cost.

### What did *not* cause the failure

- BRAM over-use (only ~5% of RAMB36 budget)
- DSP over-use (demod does not map to DSP48)
- Timing failure (placement never ran)
- `drc.disableLUTOverUtilError` — only demotes error to warning; design still cannot place

---

## Secondary issue: BRAM async-reset DRC (non-blocking)

42 warnings, capped at 20 per rule in log:

| Rule | Location | Cause |
|------|----------|--------|
| REQP-1839 | `u_ads1278/u_acq/u_frame_fifo/mem_reg_*` | `wr_ptr`, `rd_ptr`, `level` use `always @(posedge clk or negedge rstn)` |
| REQP-1839 | `ps/u_dma_phase4/u_writer/fifo_0/...` | `frame_active_reg` async reset drives BRAM enable |
| REQP-1840 | `u_frame_fifo/mem_reg_4` | Same FIFO, RAMB18 slice |

`ads1278_frame_fifo.v` lines 56–60: pointer/level registers reset asynchronously while driving inferred block RAM addresses. Fix when touching FIFO: **synchronous reset only** on BRAM control paths.

This was already noted in [`20260528_gp0-enable-hang-vivado-timing-handoff.md`](20260528_gp0-enable-hang-vivado-timing-handoff.md). Still worth fixing; it is **not** the reason this build failed.

---

## Deploy trap (stale bitstream)

After the failed build, `fpga-deploy.sh` may still find:

```text
fpga/work125_14/rp_ads1278.runs/impl_1/ads1278.bit.bin
```

That file is from an **earlier successful implementation** (pre–8× demod). `fpgautil -b` can report success while the loaded design does **not** include multi-channel demod RTL.

**Do not use on-target behavior from that bitstream to validate this feature.**

---

## Recommended fixes (priority order)

### 1. Shared divider FSM (recommended)

Implemented locally: keep **per-channel state** (`sum_pos`, `sum_neg`, counts, `demod_out`) in `ads1278_demod_bank`, but replace the combinational `/` operations with **one time-shared iterative divider** in `ads1278_demod_divider`.

- Expected savings: ~7× divider LUT/CARRY4 vs current 8× full demod
- Algorithm unchanged; demod outputs update after the saved MOD-edge batch drains through the shared divider
- Touched: `ads1278_demod_bank.v`, `ads1278_demod_divider.v`, `ads1278_acq_top.v`, `ads1278.tcl`, and demod simulation benches

### 2. Time-multiplex single demod core

One `ads1278_demod` (or one shared state machine + divider) processes channels round-robin across 8 cycles after each `spi_new_data`.

- Smallest footprint
- Requires sample holding and careful `new_data` gating
- Verify acquisition clock budget at target `EXTCLK_DIV`

### 3. Avoid division (if counts are bounded)

If `count_pos` / `count_neg` per half-cycle are bounded and known at compile time or via MMIO, replace `/ count` with **barrel shift** or **reciprocal multiply** for that fixed range.

- Needs analysis at production `MOD_DIV`, `EXTCLK_DIV`, and `DEMOD_SKIP`
- Highest efficiency if valid

### 4. Larger FPGA (last resort)

`xc7z020` has ~3× LUTs and ~3.7× CARRY4 vs 7010. Would require different board support — **not** a drop-in fix for `rp125_14`.

### Do not

- Ship with `drc.disableLUTOverUtilError` hoping placement succeeds
- Leave 8× combinational dividers and expect 7010 to fit

---

## Related repo changes (feature WIP, same branch)

Multi-channel demod was implemented across layers before the FPGA fit issue was found:

| Area | Files (representative) |
|------|-------------------------|
| FPGA RTL | `fpga/rtl/ads1278_acq_top.v`, `fpga/rtl/ads1278_demod_bank.v`, `fpga/rtl/ads1278_demod_divider.v`, `fpga/rtl/ads1278_axi_slave.sv` |
| FPGA sim | `fpga/sim/ads1278_demod_tb.v`, `fpga/sim/ads1278_demod_multichannel_tb.v`, `fpga/sim/ads1278_demod_divider_tb.v` |
| Client | `client/ads1278_client/main_window.py`, `controller.py`, `csv_logger.py`, `tools/fake_server.py` |
| Server | `server/csv_logger.c`, `server/csv_logger.h` |
| Tests | `client/tests/…`, `server/tests/test_csv_logger.c`, `server/tests/test_cmd_parse.c` |
| Docs | `docs/feats/client.md`, `ads1278-acquisition-pipeline.md`, `fpga-register-map.md`, `server.md`, `server-protocol.md`, `server-mmio-contract.md` |

Software/docs assume all channels demodulate when `CTRL[2]` is set. **FPGA bitstream does not yet match** until the shared-divider refactor is simulated, implemented, and a new build passes `impl_1`.

---

## Verification checklist (after fix)

### Build

```bash
./fpga-build.sh --target rp125_14 --remote "$MAGI" --remote-user saruul --remote-vivado vivado2020
```

Pass criteria:

- [ ] `impl_1` status `write_bitstream Complete!`
- [ ] Post-route utilization: LUT &lt; 85%, CARRY4 &lt; 85% (headroom for closure)
- [ ] REQP-1839/1840 reduced or eliminated if FIFO reset was fixed

Check synthesis report on build host:

```text
.../fpga/work125_14/rp_ads1278.runs/synth_1/red_pitaya_top_utilization_synth.rpt
```

### Simulation

```bash
iverilog -g2012 -o /tmp/ads1278_demod_divider_tb.vvp \
  fpga/sim/ads1278_demod_divider_tb.v fpga/rtl/ads1278_demod_divider.v
vvp /tmp/ads1278_demod_divider_tb.vvp

iverilog -g2012 -o /tmp/ads1278_demod_tb.vvp \
  fpga/sim/ads1278_demod_tb.v \
  fpga/rtl/ads1278_demod_bank.v fpga/rtl/ads1278_demod_divider.v
vvp /tmp/ads1278_demod_tb.vvp

iverilog -g2012 -o /tmp/ads1278_demod_multichannel_tb.vvp \
  fpga/sim/ads1278_demod_multichannel_tb.v \
  fpga/rtl/ads1278_demod_bank.v fpga/rtl/ads1278_demod_divider.v
vvp /tmp/ads1278_demod_multichannel_tb.vvp
```

Local note from this implementation pass: `iverilog`, `verilator`, and `vivado` were not present on `PATH`, so these commands still need to be run in an HDL-capable environment.

### On-target

1. Deploy **new** bitstream only after successful `impl_1`.
2. Enable acquisition + demod (`CTRL[2]`).
3. Confirm all eight channel MMIO reads (`CH1`–`CH8`) show demod-held values at MOD rate, not raw high-rate samples.
4. DMA CSV with demod-rate logging on multiple selected channels.
5. Compare against single-channel baseline if a known-good CH8 demod capture exists (`logged_files/deMod_data_v2.csv`).

---

## Quick reference: device budget vs current design

| Resource | xc7z010 avail | Design needs | Util % |
|----------|--------------:|-------------:|-------:|
| Slice LUTs | 17,600 | 34,060 | 194% |
| CARRY4 | 4,400 | 8,619 | 196% |
| RAMB36 | 20 | ~5 | 25% |
| DSP48 | 80 | ~0 | — |

---

## Open questions

1. **Latency budget:** The implemented shared divider drains one 8-channel batch sequentially. Register/DMA semantics still hold demod values; validate unusually fast MOD settings against the measured batch latency after simulation.
2. **Per-channel `DEMOD_SKIP`:** Currently one `demod_skip` bus feeds all eight instances — is that intentional for all channels?
3. **CH8 special case:** Original plan demodulated CH1 physics on CH8 readout; all-channel demod uses each channel’s own ADC input. Confirm with user that per-channel self-demod is the desired physics, not CH1-referenced demod on every channel.
