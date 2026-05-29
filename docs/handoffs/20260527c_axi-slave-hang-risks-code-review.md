# AXI slave hang risks — code review handoff

**Date:** 2026-05-27  
**Board:** `rp-f0ef77` (and similar)  
**Status:** **Code review complete**; RTL fixes beyond the read-snapshot change **not yet implemented**. Snapshot bitstream **build + on-target proof still open**.

**Prior handoffs:**

- `20260527b_axi-read-snapshot-and-dma-rate-limits.md` — read snapshot implemented, Step B repro at div 125
- `20260527_phase9-dma-server-and-mmio-hang-debug.md` — Phase 9 server + GP0 debug matrix
- `20260522b_axi-verification-and-fix-plan.md` — layer A/B/C/D verification plan

---

## Summary

Assuming the failure is a **true GP0 MMIO hang** (`devmem read` blocks → kernel stuck in `/dev/mem` → ~5 s watchdog reset), a detailed review of `fpga/rtl/ads1278_axi_slave.sv` found:

| Finding | Severity | Fix in repo? |
|---------|----------|--------------|
| Read snapshot (`read_*` flops → `RDATA`) | Addresses primary hang class | **Yes** — needs bitstream deploy |
| Write path: no `BVALID` backpressure on `AWREADY` | **High** | **No** |
| No read/write channel arbitration | **Medium** | **No** |
| Snapshot sources still live/combinational at `ARtransfer` | **Medium** | **Partial** |
| `read_pending` one-shot FSM (non-standard) | **Medium** | **No** |
| Write toggle `AWREADY`/`WREADY` without read outstanding check | **Medium** | **No** |
| Side-effect writes (`0x64` ACK) + silent `BVALID` risk | **Medium** | **No** |

**Next owner:** (1) Deploy snapshot bitstream and re-run Step B. (2) If hang persists, apply write-path and arbitration fixes below. (3) If still marginal at high rate, move to Layer D (acq-domain frame snapshot).

---

## Problem statement (unchanged)

**Symptom:** Under `--dma` or tight `devmem read 0x60` loops at aggressive `EXTCLK_DIV`, GP0 access can **hang**. SSH dies; board watchdog-resets ~5 s later.

**Not this failure mode:**

| Symptom | Mechanism |
|---------|-----------|
| `DMA_OVERWRITE_COUNT` climbs, SSH OK | Slow consumer / missing `0x64` ACK |
| `FIFO_DROPS` climbs, SSH OK | Capture faster than DDR staging |
| `overflow: yes` in snapshot | SPI FSM overlap at high rate |

**Confirmed repro (pre-snapshot bitstream):**

```bash
# Arm DMA + acquisition, div 125, then:
while true; do devmem read 0x60; done
# Hang after minutes
```

---

## What the read-snapshot fix already addresses

The current RTL implements a **two-cycle read** with **`read_*` snapshot flops** on `ARtransfer`:

1. **Cycle 1 (`ARtransfer`):** Latch readable state into `read_*` flops.
2. **Cycle 2:** Assert `RVALID`; drive `RDATA` from `read_*`, not live mux.

This fixes the **AXI protocol violation** where `RDATA` could change while `RVALID && !RREADY` — the mechanism most likely to stall Zynq GP0 when polling live `0x60` / `0x20` / channels at high wrap rate.

**Healthy in current code:**

- `RDATA` not updated while `RVALID=1` (held until `Rtransfer`)
- `ARREADY` blocked while `RVALID=1` or `read_pending=1`
- Static control regs (`ctrl_reg`, `extclk_div_reg`, etc.) snapshotted correctly

**Still open:** Bitstream build, deploy, and Step B soak at div **125** for 10+ min.

---

## Remaining unhealthy AXI signs (code review)

All references are to `fpga/rtl/ads1278_axi_slave.sv` unless noted.

### Issue 1 — Write path ignores outstanding `BVALID` (HIGH)

**Location:** write accept + response (~lines 268–380)

```systemverilog
// AWREADY — no check for (!BVALID || BREADY)
bus.AWREADY <= ~bus.AWREADY & bus.AWVALID & bus.WVALID;

// BVALID only re-asserts when ~BVALID
else if (AWtransfer & ~bus.BVALID & Wtransfer) bus.BVALID <= 1'b1;
```

**Problem:** Classic broken Xilinx AXI-lite template pattern ([ZipCPU AXI rules](https://zipcpu.com/blog/2021/08/28/axi-rules.html), [VHDL template fix](https://zipcpu.com/blog/2021/05/22/vhdlaxil.html)). A second write can complete (`slv_reg_wren` fires) while `BVALID=1` and `BREADY=0`. Side effects apply but no new write response is signaled → PS may wait forever.

**Why it matters here:** `--dma` server does **read `0x60` → parse DDR → write `0x64` ACK`** in quick succession. Same class as `SET_EXTCLK_DIV` write hang (Step E in prior handoff).

**Recommended fix:**

```systemverilog
// Gate write accept on free response channel
wire write_accept = (!bus.BVALID || bus.BREADY);
// AWREADY logic includes write_accept (and optionally !read_outstanding)
```

Also gate `slv_reg_wren` or ensure `BVALID`/`BRESP` update correctly for back-to-back writes.

**Verify:** ILA on `AWVALID`, `AWREADY`, `BVALID`, `BREADY` during server ACK loop; formal assert `AWREADY -> (!BVALID || BREADY)`.

---

### Issue 2 — No read/write channel arbitration (MEDIUM)

**Location:** independent read FSM (~386–455) and write FSM (~268–380)

**Problem:** `ARtransfer` and `AWtransfer` can occur on the same cycle. AXI allows this, but shared register state (`dma_buf_full_reg`, `dma_irq_status_reg`) is updated by writes (`0x64`, `0x58`) while reads may snapshot `0x60` on the same posedge.

**Why it matters:** Under server + concurrent `devmem`, read and write traffic overlap. Combined with Issue 1, write side effects may apply without a visible response.

**Recommended fix (pick one):**

- **Light:** Gate `AWREADY` on `(!RVALID || RREADY)` (no new write while read response outstanding).
- **Standard (ZipCPU):** Skidbuffer + explicit `axil_read_ready` / `axil_write_ready` with mutual exclusion.

---

### Issue 3 — Snapshot sources still live/combinational (MEDIUM)

**Location:** snapshot capture (~430–449) and combinational packs (~152–170)

On `slv_reg_rden`, the slave latches:

| Snapshot flop | Source | Still live? |
|---------------|--------|-------------|
| `read_dma_buf_status_reg` | `dma_buf_status_reg` | **Yes** — `always_comb` from `dma_buf_full_reg` |
| `read_dma_status_reg` | `dma_status_reg` | **Yes** — includes `dma_phase4_write_index` |
| `read_dma_write_index_reg` | `dma_write_index_reg` | **Yes** — HP writer index |
| `read_status_reg`, `read_ch_data[]` | `ads1278_acq_top` outputs | **Yes** — SPI/acq |
| `read_fifo_*` | FIFO status from acq | **Yes** |

**Problem:** The snapshot fixes the **RDATA stability** rule but not **Layer D**. At high wrap/SPI rate:

- Setup timing stress on wide snapshot bank at `ARtransfer`
- Same-cycle collision: `ARtransfer` + `dma_phase4_wrap_pulse` → capture may be pre/post wrap (NBA ordering)

Unlikely to cause `RVALID` stuck directly, but may explain **hang persisting after snapshot deploy** or marginal div 125 behavior.

**Recommended fix (Layer D):**

- Register `dma_buf_status` in flops updated only on `dma_phase4_wrap_pulse` and `DMA_BUF_ACK` (not combinational pack).
- Per-frame snapshot in `ads1278_acq_top`; AXI reads only latched frame, not mid-SPI `ch_data` / `status_reg`.

---

### Issue 4 — `read_pending` one-shot FSM (MEDIUM)

**Location:** ~400–407, 452–455, 457–494

```systemverilog
else if (slv_reg_rden)       read_pending <= 1'b1;
else if (read_pending & ~bus.RVALID) read_pending <= 1'b0;

else if (read_pending & ~bus.RVALID) bus.RVALID <= 1'b1;
// RDATA loaded on same condition as RVALID rise
```

**Problem:** Non-standard vs industry pattern `if (!RVALID || RREADY) RDATA <= next`. `read_pending` clears on the same edge `RVALID` rises. Normally equivalent, but brittle: if `RVALID` ever fails to register while `read_pending` clears, state becomes **address accepted, `read_pending=0`, `RVALID=0`** → permanent read stall.

**Recommended fix:** Replace with ZipCPU / alexforencich style output register:

```systemverilog
if (!bus.RVALID || bus.RREADY) begin
  bus.RDATA <= read_mux_out;
  bus.RVALID <= read_has_data;  // or hold until transfer
end
```

Run formal check: `$past(RVALID && !RREADY) |-> $stable(RDATA)`.

---

### Issue 5 — Write toggle `AWREADY`/`WREADY` (LOW–MEDIUM)

**Location:** ~268–281

Toggle pattern requires `AWVALID && WVALID` aligned; no coordination with outstanding read. Adds latency; couples with Issues 1–2 under heavy MMIO.

**Recommended fix:** Replace toggle with level-sensitive `AWREADY` gated on `(!BVALID || BREADY) && (!RVALID || RREADY)` (and skidbuffer if throughput needed).

---

### Issue 6 — Side-effect writes without register `case` entry (LOW–MEDIUM)

**Location:** `dma_buf_ack_mask` / `dma_irq_ack_mask` in `always_comb` (~172–184), applied in dma ownership block (~342)

Writes to `0x64` / `0x58` apply via combinational mask when `slv_reg_wren`. If Issue 1 causes a write with no `BVALID` pulse, **`dma_buf_full_reg` may clear without PS seeing write completion** — looks like hang on write path from software.

---

### Issue 7 — Integration / platform (out of slave RTL, still relevant)

From `20260522b_axi-verification-and-fix-plan.md` — not found in `ads1278_axi_slave.sv` but can produce identical symptom:

| Layer | Check |
|-------|--------|
| **A** | FPGA not programmed / wrong bitstream before MMIO |
| **B** | `axi_protocol_converter` + GP0 reset association |
| **Timing** | Final routed WNS on GP0 → `RVALID`/`RDATA` paths |
| **Software** | Tight poll loops amplify marginal RTL |

---

## Priority-ordered fix plan

### Phase A — Prove snapshot alone (no new RTL)

1. Build + deploy bitstream with current `ads1278_axi_slave.sv` (read snapshot).
2. Run Step B: `while true; do devmem read 0x60; done` at div **125**, DMA+capture, **10+ min**.
3. Log to `/root/ads1278-logs/axi-matrix.log`.

| Result | Next step |
|--------|-----------|
| **Pass** | Phase 9 sign-off at `0x271`; step dividers down |
| **Hang** | Phase B below |

### Phase B — Write-path + arbitration (Issues 1, 2, 5)

1. Gate `AWREADY` / `slv_reg_wren` on `(!BVALID || BREADY)`.
2. Optionally gate writes while `RVALID && !RREADY`.
3. Rebuild bitstream; repeat Step B + `--dma` server soak.
4. Add ILA: `AWVALID`, `AWREADY`, `BVALID`, `BREADY`, `ARVALID`, `ARREADY`, `RVALID`, `RREADY`.

### Phase C — Harden read FSM (Issue 4)

1. Refactor to `!RVALID || RREADY` output registering.
2. Formal or simulation regression on back-to-back reads.

### Phase D — Layer D snapshot (Issue 3)

1. Flop `dma_buf_status` on wrap/ACK only (remove combinational pack for CPU read path).
2. Per-frame latch in acq domain for `status_reg` / `ch_data[]`.
3. Re-run Phase 6 acceptance matrix from `20260522b`.

---

## Validation matrix (after each RTL phase)

Run **10+ min** each; log `{phase, extclk_div, test, hung_y/n, time_to_hang_s}`.

| # | Config | Command |
|---|--------|---------|
| 1 | Idle PL | fast `read 0x28` loop |
| 2 | DMA+capture, div 625 | fast `read 0x60` loop |
| 3 | DMA+capture, div 125 | fast `read 0x60` loop |
| 4 | DMA+capture, div 125 | fast `read 0x20` loop |
| 5 | DMA+capture, div 125 | `write 0x28` then `read 0x28` |
| 6 | Full stack | `ads1278-server --dma` + client, div 625, 5+ min |
| 7 | Full stack | server `--dma`, div 125, 5+ min |

**Pass:** No `devmem` block; no watchdog reset. Optional: ILA shows no stuck `RVALID`/`BVALID`.

---

## Mapping to `--dma` server traffic

| Server action | AXI op | Issues touched |
|---------------|--------|----------------|
| Poll loop | `read 0x60` | 3, 4 (read path) |
| After drain | `write 0x64` ACK | 1, 2, 6 (write path) |
| Client connect / commands | `write 0x38`, `read 0x20`, `write 0x28` | 1, 2, 5 |
| Startup snapshot | multi-read burst | 3, 4 |

---

## References (external)

- [ZipCPU — AXI handshaking rules](https://zipcpu.com/blog/2021/08/28/axi-rules.html) — `RDATA` stability, `BVALID` gating, read/write arbitration
- [ZipCPU — Fixing Xilinx broken AXI-lite](https://zipcpu.com/blog/2021/05/22/vhdlaxil.html) — `ARREADY` must check outstanding `RVALID`
- [ZipCPU — Building the perfect AXI4 slave](https://zipcpu.com/blog/2019/05/29/demoaxi.html) — registered `RDATA`, `ARREADY` when idle
- AMD AR #68101 — GP0 hangs with wide PL slaves (byte-lane upsizing; less likely at 32-bit)

---

## Key files

| Area | Path |
|------|------|
| AXI slave (all issues above) | `fpga/rtl/ads1278_axi_slave.sv` |
| AXI interface | `fpga/rtl/axi4_lite_if.sv` |
| Acquisition live outputs | `fpga/rtl/ads1278_acq_top.v` |
| DMA server MMIO pattern | `server/server.c` (`ads1278_service_dma_buffers`, `ads1278_send_dma_buffer`) |
| MMIO map | `docs/feats/fpga-register-map.md`, `server/memory_map.h` |
| Verification plan | `docs/handoffs/20260522b_axi-verification-and-fix-plan.md` |
| Snapshot + rate limits | `docs/handoffs/20260527b_axi-read-snapshot-and-dma-rate-limits.md` |
| Phase 9 + debug steps | `docs/handoffs/20260527_phase9-dma-server-and-mmio-hang-debug.md` |
| Block design / GP0 | `fpga/source/system_design_bd_rp125_14/system.tcl` |

---

## Suggested order for next session

1. **Deploy snapshot bitstream** (if not already on board).
2. **Step B** at div **125** — decide if Issue 3 partial fix is enough.
3. If hang persists → implement **Phase B** (Issues 1 + 2) in `ads1278_axi_slave.sv`.
4. **ILA** on failing pattern before further RTL churn.
5. If read-only stress passes but `--dma` hangs → focus **write `0x64` / `0x28`** and Issue 1.
6. If marginal at extreme dividers only → **Phase D** acq-domain snapshot.
7. Update `axi-matrix.log`; commit FPGA fixes + this handoff when a phase passes soak.

---

## Success criteria

### Minimum (Phase A)

- [ ] Snapshot bitstream deployed
- [ ] `read 0x60` loop **10+ min** at div **125**, no hang
- [ ] `ads1278-server --dma` + client **5+ min** at div **625** (`0x271`)

### Full GP0 sign-off (after Phase B–D as needed)

- [ ] Validation matrix rows 1–7 pass
- [ ] No stuck `RVALID`/`BVALID` on ILA during fastest failing command (optional)
- [ ] Formal or sim regression for `RDATA` stable while stalled (optional)
