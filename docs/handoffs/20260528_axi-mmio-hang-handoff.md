# AXI / MMIO hang — session handoff (2026-05-28)

**Audience:** Next agent continuing `rp_ads1278` GP0 hang / DMA / acquisition work.  
**Prior docs:** `20260527c_axi-slave-hang-risks-code-review.md`, `20260527b_axi-read-snapshot-and-dma-rate-limits.md`, `20260527_phase9-dma-server-and-mmio-hang-debug.md`

---

## Goal

Eliminate **Red Pitaya SSH freeze + ~5 s watchdog reset** during acquisition / `--dma` operation. Symptoms match **true GP0 MMIO hang** (kernel stuck in `/dev/mem` on register access), not slow consumer or buffer overruns alone.

---

## What was implemented in this session (repo)

### FPGA RTL — `fpga/rtl/ads1278_axi_slave.sv`

- **Phase A (read snapshot):** Already present before session — `read_*` flops on `ARtransfer`; `RDATA` from flops, not live mux.
- **Phase B+C (AXI handshake):** Implemented in working tree:
  - `write_response_ready`, `read_response_ready`, `write_channel_idle`, `read_request_ready`
  - Write accept gated on `(!BVALID || BREADY)`; read/write serialization
  - `BVALID` tied to `slv_reg_wren`; read FSM uses `read_response_ready` pattern
- **Phase D (latched `DMA_BUF_STATUS`):** `dma_buf_status_reg` updated only on `dma_phase4_wrap_pulse`, `DMA_BUF_ACK`, overwrite ACK, `dma_enable_rise` — not combinational pack on every read.

### Server — `server/server.c`

- `ads1278_dma_arm()`: sets `ADS1278_DMA_CTRL_IRQ_ENABLE` when arming DMA.
- `ads1278_service_dma_buffers()`: reads `DMA_IRQ_STATUS` first; returns early unless wrap/overwrite bits set; ACKs IRQ before draining DDR; only reads `0x60` when needed.

### Deploy helper — `scripts/deploy-fpga-to-board.sh`

- After bitstream deploy, **rsync** from remote build tree:
  - `fpga/work125_14/rp_ads1278.runs/impl_1/red_pitaya_top_timing_summary_routed.rpt`
  - `red_pitaya_top_route_status.rpt`, `red_pitaya_top_drc_routed.rpt`, `red_pitaya_top_methodology_drc_routed.rpt`

### NOT implemented in RTL this session (still open)

```systemverilog
// ads1278_axi_slave.sv ~line 537 — STILL PRESENT IN TREE
assign irq = status_reg[0] | (dma_irq_enable & dma_irq_pending);
```

**This is critical:** `status_reg[0]` is one-cycle `new_data` per SPI frame → **~24 kHz IRQ pulses** at `EXTCLK_DIV=5` into PS `IRQ_F2P`. Server IRQ gating does **not** fix PL IRQ generation.

**Recommended one-line fix:**

```systemverilog
assign irq = dma_irq_enable & dma_irq_pending;
```

### NOT implemented

- Phase D acq-domain frame snapshot for `status_reg` / `ch_data` (Layer D in handoff doc).
- `ads1278_frame_fifo.v` synchronous-reset fix (synthesis dissolves FIFO to registers due to async reset — see build log).
- Vivado timing closure / ILA.
- UIO / Linux IRQ driver for PL IRQ.

---

## User bench results (critical)

| Test | Result |
|------|--------|
| Snapshot bitstream + server, div 625, long soak | Hang ~42 min (prior session) |
| **New bitstream** (May 28 build), **no client**, `EXTCLK_DIV=5`, `CTRL enable=1` only | **`devmem write` returned**; board still **rebooted** later |
| No `ads1278-server`, no port 5000, no DMA arm from server | Confirms hang is **not** TCP/client/DMA poll loop alone |

**Interpretation:** Write path may be OK; failure is **after enable** — acquisition running, IRQ/timing/PL stress — not “stuck on `devmem read 0x60`” alone.

---

## Vivado build log (May 28, 2026, remote `MAGI`, Vivado 2020.1)

Path: `/home/saruul/rp_ads1278/fpga/work125_14/rp_ads1278.runs/impl_1/`

| Stage | WNS | TNS |
|--------|-----|-----|
| Route estimate | **-0.650 ns** | -18.754 ns |
| After `phys_opt_design` | **-0.076 ns** | -0.807 ns |
| Final `report_timing_summary` | **FAIL** (critical warning) | |

Bitstream **still generated** (WebPACK allows bitgen with violations).

**Phys_opt touched:** `u_ads1278/u_acq/u_spi_tdm/*` (`ads_sclk`, `wait_cnt`, `state2_carry`), `u_ads1278/mod_cnt_reg`, `extclk_div` paths.

**Synthesis note:** `ads1278_frame_fifo` — `RAM "mem_reg" dissolved into registers` (async reset on `rstn`/`clear`). Bad for timing and resources at high frame rate; fix with sync reset + `ram_style = "block"`.

**DRC:** `REQP-1839` on DMA writer FIFO / `frame_active_reg` async BRAM controls.

**Congestion:** Some tiles ~83–93% (check if paths hit `u_ads1278`).

---

## Architecture context (unchanged)

- **Data plane:** HP DMA → DDR; server `mmap` DDR — correct Red Pitaya pattern.
- **Control plane:** GP0 `ads1278_axi_slave` @ `0x42000000` (user MMIO convention).
- **Prior hang class:** `BVALID` without backpressure, read/write overlap, live `RDATA`, combinational `0x60` — **partially addressed** in RTL, **not proven on board** if bitstream predates B/C or IRQ unchanged.
- **rpll comparison:** rpll uses BRAM + sparse MMIO + IRQ flags; 100 MSPS ref has no Zynq MMIO. Stock RP fast ADC path ≠ E1 SPI path.

---

## Root-cause ranking (for next owner)

1. **PL IRQ storm (high confidence for enable-only reboot)** — `irq = status_reg[0] | ...` while `ctrl_enable` runs. Fix IRQ assignment; rebuild; retest div 5 enable-only **before** long soaks.
2. **Timing failure (high confidence for marginal/metastable behavior)** — WNS negative in shipped bitstream. Pull `red_pitaya_top_timing_summary_routed.rpt`; fix top paths (SPI TDM, mod counters, FIFO BRAM).
3. **Combinational `0x60` / live status** — mitigated by Phase D latch in RTL if that bitstream is deployed; verify on bench.
4. **Server poll without IRQ driver** — server changes reduce `0x60` traffic but do not fix IRQ line.

---

## Recommended next steps (ordered)

1. **RTL:** Change `assign irq` to DMA-only (see above). Optional: sync-reset `ads1278_frame_fifo.v`.
2. **Rebuild bitstream** on `MAGI` (`./fpga-build.sh --target rp125_14 --remote $MAGI --remote-user saruul --vivado vivado2017` or user's Vivado 2020.1 flow).
3. **Pull timing report to Mac** (user asked for this):

   ```bash
   mkdir -p fpga/work125_14/rp_ads1278.runs/impl_1
   scp "$MAGI:/home/saruul/rp_ads1278/fpga/work125_14/rp_ads1278.runs/impl_1/red_pitaya_top_timing_summary_routed.rpt" \
     fpga/work125_14/rp_ads1278.runs/impl_1/
   ```

4. **Bench:** `EXTCLK_DIV=5`, `CTRL=2` (enable only), **no server** — pass/fail gate for IRQ fix.
5. **Then:** div 625/125 soaks with `--dma` + client; log to `axi-matrix.log`.
6. **Optional:** ILA on `BVALID`/`RVALID`/`irq` during failing pattern.

---

## Validation matrix (from handoff 20260527c)

After each RTL phase, run 10+ min each; log `{phase, extclk_div, test, hung_y/n, time_to_hang_s}`.

Minimum bar after IRQ + timing fixes:

- [ ] `read 0x60` loop 10+ min div 125 — no hang
- [ ] `ads1278-server --dma` div 625, 45+ min
- [ ] Same at div 125 with client

---

## Key files

| Area | Path |
|------|------|
| AXI slave | `fpga/rtl/ads1278_axi_slave.sv` |
| Acq / FIFO | `fpga/rtl/ads1278_acq_top.v`, `ads1278_frame_fifo.v`, `ads1278_spi_tdm.v` |
| Server | `server/server.c`, `server/memory_map.h` |
| Deploy / reports | `scripts/deploy-fpga-to-board.sh` |
| Register map | `docs/feats/fpga-register-map.md` |
| Prior handoffs | `docs/handoffs/20260527c_axi-slave-hang-risks-code-review.md`, `20260527_phase9-dma-server-and-mmio-hang-debug.md` |
| Build artifacts (remote) | `fpga/work125_14/rp_ads1278.runs/impl_1/*.rpt` |

---

## Open questions for user

1. Confirm **which bitstream** was on the board for the div-5 enable-only reboot (May 27 vs May 28 build)?
2. Was **`ads1278-server` running** during that test (idle process still maps MMIO)?
3. Exact sequence: `EXTCLK_DIV` write first, then `CTRL`, or both in one session?
4. After IRQ fix, is **timing closure** required before sign-off, or is “good enough” WNS acceptable for bring-up?

---

## Success criteria (updated)

- [ ] IRQ fix bitstream: enable-only at div 5, **no reboot**, 10+ min
- [ ] Final timing WNS ≥ 0 (or documented waiver)
- [ ] Matrix rows 1–7 from `20260527c` pass at target dividers
- [ ] No SSH freeze / watchdog during `--dma` soak
