# rp_ads1278 — AXI/GP0 verification and fix plan

Step-by-step handoff to locate and fix the FPGA/AXI stall that blocks PS MMIO access under load. Assumes the failure chain is always **incomplete AXI transaction → kernel blocks in `/dev/mem` → 5 s watchdog reset**. Skips reboot-classification and non-FPGA suspects.

Companion to:

- `docs/handoffs/20260522_mmio-hang-root-cause-hypotheses.md`
- `docs/handoffs/20260430_connection-loss-triage-and-decision-tree.md`

## Summary

**Working assumption:** PS hangs because an AXI GP0 read or write never completes (`RVALID` or `BVALID` never returns). The ARM thread blocks in `/dev/mem`; systemd stops petting the hardware watchdog; the board hard-resets ~5 s later.

**Goal:** Pin the stall to one layer in the PL path, apply the matching fix, and pass a soak acceptance matrix.

**AXI path (single clock domain today):**

```text
ARM (PS)  →  M_AXI_GP0  →  axi_protocol_converter  →  ads1278_axi_slave  →  ch_data / status mux
              ↑ fclk[0] @ 125 MHz, frstn[0]
```

**Layers to discriminate:**

| Layer | Component | Typical stall signature |
| --- | --- | --- |
| **A** | PS7 GP0 / address map | Any register, enable off, even single reads |
| **B** | `axi_protocol_converter` | Back-to-back reads; intermittent under rate |
| **C** | `ads1278_axi_slave` FSM | Specific register or write path; snapshot burst |
| **D** | `ads1278_acq_top` on same clock | Only with enable + active acquisition / low divider |

## Prerequisites

Run all board tests only after ads1278 is loaded and MMIO is healthy:

```bash
/usr/local/bin/ads1278-rpdevmem read 0x24    # expect 0x00000000
/usr/local/bin/ads1278-rpdevmem read 0x28    # expect 0x00000271
mkdir -p /root/ads1278-logs
```

If either read returns garbage (`0xff`, `0`), redeploy ads1278 before proceeding.

Log results to `/root/ads1278-logs/axi-matrix.log` using one line per test:

```text
{test_id, enable, extclk_div, last_cmd, hung_yes/no, time_to_hang_s}
```

---

## Phase 1 — Software trigger matrix (no Vivado)

**Goal:** Learn which MMIO access pattern causes the stall.

### Step 1.1 — Single-register baseline (idle PL)

Acquisition **disabled** (`CTRL=0`). One read at a time, human-paced:

```bash
/usr/local/bin/ads1278-rpdevmem read 0x00   # CH1
/usr/local/bin/ads1278-rpdevmem read 0x20   # STATUS
/usr/local/bin/ads1278-rpdevmem read 0x24   # CTRL
/usr/local/bin/ads1278-rpdevmem read 0x28   # EXTCLK_DIV
/usr/local/bin/ads1278-rpdevmem read 0x2c   # MOD_DIV
```

| Result | Diagnosis |
| --- | --- |
| All succeed | Single idle reads OK → continue to rate/load tests |
| One offset hangs | Register mux or address decode for that register |
| Random offset hangs | Integration/timing, not register semantics |

### Step 1.2 — Rate sweep on one register

Loop **`0x28` only** (static control reg):

```bash
# slow — 10+ min
while true; do /usr/local/bin/ads1278-rpdevmem read 0x28; sleep 1; done

# fast — until hang or 10+ min
while true; do /usr/local/bin/ads1278-rpdevmem read 0x28; done
```

| Result | Diagnosis |
| --- | --- |
| Slow OK, fast hangs | Timing or AXI handshake under back-to-back traffic |
| Both OK 10+ min | Raw MMIO rate alone is not the trigger |

### Step 1.3 — Full snapshot pattern (mimics server)

Server performs ~12 reads per snapshot (`server/memory_map.c`: STATUS → 8× CH → CTRL → EXTCLK_DIV → MOD_DIV → STATUS):

```bash
while true; do /usr/local/bin/ads1278-rpdevmem snapshot; done
```

| Result | Diagnosis |
| --- | --- |
| Hangs here but Step 1.2 OK | Multi-register burst or a register in the snapshot sequence |
| OK idle, fails with enable | Acquisition + AXI concurrency |

### Step 1.4 — Enable acquisition, repeat 1.2 and 1.3

```bash
/usr/local/bin/ads1278-rpdevmem write 0x24 0x2   # enable
# repeat Step 1.2 fast loop on 0x28
# repeat Step 1.3 snapshot loop
```

Sweep divider (field: lower div → faster frames → faster server poll):

```bash
/usr/local/bin/ads1278-rpdevmem write 0x28 125
/usr/local/bin/ads1278-rpdevmem write 0x28 375
/usr/local/bin/ads1278-rpdevmem write 0x28 625
```

| Result | Diagnosis |
| --- | --- |
| Hang only with enable + fast divider | PL acquisition exposes AXI marginality |
| Hang with enable off after 1.2 passed | Recheck write path (AXI write stall) |

### Step 1.5 — Write-path isolation

```bash
/usr/local/bin/ads1278-rpdevmem write 0x28 625
/usr/local/bin/ads1278-rpdevmem write 0x24 0x2
/usr/local/bin/ads1278-rpdevmem write 0x24 0x0
```

| Result | Diagnosis |
| --- | --- |
| Reads OK, writes hang | AW/W/B channel or write FSM in slave |
| Both hang under load | Full slave or protocol converter path |

### Step 1.6 — Server as MMIO generator

```bash
ads1278-server --poll-ms 1000          # slow soak
# then normal (default poll rate)
```

| Result | Diagnosis |
| --- | --- |
| Slow OK, fast hang | Sustained GP0 traffic under acquisition |
| Idle server hangs after `Listening` | Startup snapshot succeeded; not continuous polling — suspect incomplete transaction or shared PL logic |

### Phase 1 → layer mapping

| Phase 1 pattern | Most likely layer |
| --- | --- |
| Any register, any rate, enable off | **A or B** |
| Only under fast back-to-back reads | **B or C** |
| Only snapshot / CH reads, not `0x28` alone | **C or D** |
| Only with enable + low divider | **D (+ timing on C)** |
| Writes only | **C** write channel |

---

## Phase 2 — Static FPGA checks (before RTL changes)

Rebuild and inspect **final routed** timing (not mid-place estimates):

```tcl
report_timing_summary -file timing.rpt
report_timing -max_paths 20 -path_type setup -file setup_paths.rpt
```

**Pass criteria:** final `WNS >= 0`, `WHS >= 0`. Fix timing before soak if violated.

Filter setup report for paths touching:

- `M_AXI_GP0_*`
- `axi_protocol_converter`
- `ads1278_axi_slave` / `RVALID` / `ARREADY`
- `ch_data` / `status_reg` → `RDATA`

Thin margin (`WNS < 0.2 ns`) on AXI paths + Phase 1 “fast reads fail” → timing fix is primary.

### Reset and clock audit

Known weak spot from prior builds: **`M_AXI_GP0` has no associated reset port** warning.

Verify in BD / implementation log:

| Check | Expected |
| --- | --- |
| `bus.ACLK` | `fclk[0]` (125 MHz) |
| `bus.ARESETn` | `frstn[0]` |
| `axi_protocol_converter_0/aresetn` | `PL_ARESETn` = `frstn[0]` |
| `M_AXI_GP0` ASSOCIATED_RESET | `PL_ARESETn` |
| Address map | `0x42000000`, range `0x1000` |
| Slave + acq clock | Same `bus.ACLK` / `bus.ARESETn` |

**Fix if audit fails:** explicitly associate PS7 GP0 reset in BD; regenerate; one reset net drives converter + PL slave + `PL_ARESETn` port.

Reference implementation truth:

- Top: `fpga/rtl/red_pitaya_top.sv` — AXI on `fclk[0]`, not ADC PLL domain
- BD: `fpga/source/system_design_bd_rp125_14/system.tcl`
- PS wrapper: `fpga/rtl/red_pitaya_ps.sv`

---

## Phase 3 — ILA hardware proof (definitive)

Use when Phase 1 shows hangs and Phase 2 timing/reset look OK (or after timing fix still hangs).

### Minimum probe set

On `bus` between PS wrapper and `ads1278_axi_slave`:

| Signal | Stuck pattern → diagnosis |
| --- | --- |
| `ARVALID` & `!ARREADY` | Address phase never accepted |
| `ARVALID` & `ARREADY` then `!RVALID` | Read data never returned — **primary stall signature** |
| `RVALID` & `!RREADY` | PS not completing (rare) |
| `AWVALID` / `WVALID` / `!BVALID` | Write stall |

Also probe `ctrl_enable`, `status_reg[0]`, SPI FSM state if hang correlates with enable.

### Procedure

1. Build bitstream with ILA on the probe set above.
2. Run the exact failing Phase 1 command (e.g. fast `snapshot` loop with enable + div 125).
3. After reconnect, read ILA capture.

**Interpretation:**

- Last transaction: `ARVALID=1`, `RVALID=0` for extended period → incomplete AXI read (matches assumed failure chain).
- Hang coincides with SPI `S_SHIFT` → acquisition + AXI interaction (layer **D**).

---

## Phase 4 — Isolation bitstreams

Fastest way to split layer **C** vs **D** vs **A/B**.

### Bitstream X — stub AXI slave only

- Keep PS BD + protocol converter unchanged.
- Replace `ads1278_axi_slave` with minimal slave: read-only ID @ `0x00`, scratch @ `0x04`.
- No `ads1278_acq_top`, no SPI, no IRQ.

Soak: Phase 1.2 fast read loop + Phase 1.3 snapshot-like burst.

| Result | Conclusion |
| --- | --- |
| Never hangs | Fault is in **C+D**, not PS/converter/map |
| Still hangs | Fault is **A or B** |

### Bitstream Y — real slave, acquisition tied off

- Full register map; `ctrl_enable=0` hardwired; acq outputs static; IRQ disconnected.

| Result | Conclusion |
| --- | --- |
| X OK, Y OK | **D** (live acquisition) causes stall |
| X OK, Y hangs | **C** (slave FSM / mux) without acq |
| X hangs | **A/B** |

---

## Phase 5 — Fixes by diagnosed layer

### Layer A/B — PS / converter / map / reset

1. Regenerate BD from `system.tcl`; confirm GP0 address + reset association.
2. Ensure `PL_ARESETn` releases synchronously after `PL_ACLK` is stable.
3. Compare PS wiring against stock Red Pitaya reference (`.reference/RedPitaya-FPGA`).
4. Re-run Phase 1 fast-read soak on stub bitstream X.

### Layer C — `ads1278_axi_slave` FSM / timing

1. **Register the read datapath:** latch `ch_data[]` / `status_reg` into dedicated flops on read strobe; avoid combinational mux from actively changing acq outputs.
2. Review `RVALID` / `ARREADY` FSM in `fpga/rtl/ads1278_axi_slave.sv` — ensure no stuck states; `RVALID` clears on `RREADY`.
3. Re-run timing; add interface delay constraints only as last resort.
4. Soak Phase 1.3 / 1.4 again.

### Layer D — acquisition + AXI concurrency

1. **Light fix:** frame snapshot registers in acq domain; AXI reads only the snapshot (no read during SPI shift).
2. **Structural fix:** run acquisition on `adc_clk` (PLL domain); AXI slave on `fclk[0]`; CDC via dual-clock FIFO or per-frame snapshot + 2FF control sync.
3. Optionally tie `irq = 0` during bring-up if PL→PS interrupt noise complicates ILA interpretation.

### Rate sensitivity with passing timing

1. Pipeline stage on `RDATA` path.
2. Server diagnostic: read STATUS + one channel only — if hang disappears, permanent fix is FPGA snapshot registers + reduced server read set.

---

## Phase 6 — Acceptance matrix

Run **20+ min each** without hang before calling the fix done:

| # | Config | Command |
| --- | --- | --- |
| 1 | Idle PL | fast `read 0x28` loop |
| 2 | Enabled, div 625 | `snapshot` loop |
| 3 | Enabled, div 125 | `snapshot` loop |
| 4 | Full stack | `ads1278-server` + client, div 125 |
| 5 | Full stack | server + client, div 625, long soak |

Optional: ILA confirms every transaction completes with full handshake, or no failures occur.

---

## Recommended order of work

1. **Phase 1 matrix** on board → fill `axi-matrix.log`, identify layer.
2. **Phase 2** timing + reset audit on current bitstream.
3. **Bitstream X** (stub slave) → 30 min soak with fastest failing Phase 1 command.
4. If X passes → **Bitstream Y** or **Phase 3 ILA** on real design.
5. Apply **Phase 5 fix** for diagnosed layer.
6. **Phase 6** acceptance matrix.

---

## Mapping from prior handoffs

| Prior observation | Verification step |
| --- | --- |
| Lower `EXTCLK_DIV` fails sooner (20260430) | Phase 1.4 divider sweep + 1.6 poll rate |
| Server alone can drop SSH (20260522) | Phase 1.3 snapshot vs 1.2 single-read; Step 1.6 idle server |
| `M_AXI_GP0` reset warning | Phase 2 reset audit |
| Negative WNS in old logs | Phase 2 timing on AXI paths |
| Wrong bitstream after reset | Not AXI root cause — redeploy ads1278 before each test |

---

## Success criteria

- Phase 1 matrix completed with `axi-matrix.log` showing which pattern hangs first.
- Fault narrowed to one layer (A/B/C/D) via matrix + stub bitstream and/or ILA.
- Fix applied for that layer.
- Phase 6 acceptance matrix passes 20+ min per row without watchdog reset.
- Optional: ILA shows no stuck `RVALID` on failing soak command.

## Key files

| Area | File |
| --- | --- |
| AXI slave + IRQ | `fpga/rtl/ads1278_axi_slave.sv` |
| Acquisition | `fpga/rtl/ads1278_acq_top.v`, `fpga/rtl/ads1278_spi_tdm.v` |
| PS / FCLK / AXI bus | `fpga/rtl/red_pitaya_top.sv`, `fpga/rtl/red_pitaya_ps.sv` |
| Block design / address map | `fpga/source/system_design_bd_rp125_14/system.tcl` |
| MMIO snapshot loop | `server/memory_map.c` |
| Server poll path | `server/server.c` |
| MMIO contract | `docs/feats/server-mmio-contract.md`, `docs/feats/fpga-register-map.md` |
| AXI integration notes | `docs/notes/AXI_GP0_REGISTER_MAP_HOWTO.md` |
| Prior hypotheses | `docs/handoffs/20260522_mmio-hang-root-cause-hypotheses.md` |
| Prior triage | `docs/handoffs/20260430_connection-loss-triage-and-decision-tree.md` |
| FPGA integration risks | `docs/handoffs/20260407_stock-fpga-recovery.md` |
| Latest build log | `docs/logs/20260408_fpga-build.txt` |

## References

- `docs/handoffs/20260522_mmio-hang-root-cause-hypotheses.md`
- `docs/handoffs/20260430_connection-loss-triage-and-decision-tree.md`
- `docs/handoffs/20260407_stock-fpga-recovery.md`
- `docs/notes/AXI_GP0_REGISTER_MAP_HOWTO.md`
- AMD Zynq-7000 TRM (UG585) — AXI GP port behavior
