# AXI read snapshot fix + DMA rate-limit triage handoff

**Date:** 2026-05-27  
**Board:** `rp-f0ef77` (and similar)  
**Branch:** `dma-work` (local changes **not committed** at handoff time)  
**Status:** **RTL read-snapshot fix implemented in repo**; **bitstream rebuild + on-target proof still open**. Phase 9 server (`--dma`) implemented but not fully signed off. Operator reproduced **`read 0x60` GP0 hang** at div **125**; clarified ping-pong **`0x60` behavior with/without client**.

**Prior handoff:** `20260527_phase9-dma-server-and-mmio-hang-debug.md` (Phase 9 server + hang debug plan). This doc updates RTL status and captures board observations from the follow-on session.

---

## Summary

| Area | State |
|------|--------|
| Phase 8 (128-byte stride, canary, `dma-frames`) | **Passed** at `EXTCLK_DIV=0x271` — `20260524_dma-frame-burst-alignment.md` |
| Phase 9 server (`ads1278-server --dma`) | **Implemented** in `server/server.c`; on-target 5+ min client soak at `0x271` **not signed off** |
| GP0 hang on hot `read 0x60` | **Reproduced** at div **125** (tight loop, minutes); div **5** with `--dma` also seen pre-fix |
| RTL Layer C fix (read snapshot) | **Implemented** in `fpga/rtl/ads1278_axi_slave.sv` — **needs Vivado build + deploy** |
| Speed-limit understanding | Documented below (`overflow`, `FIFO_DROPS`, `DMA_OVERWRITE_COUNT`, GP0 hang) |

**Next owner:** Rebuild/deploy bitstream with read snapshot → re-run Step B (`read 0x60` loop) at div **125**, then Phase 9 validation at **`0x271`**, then step dividers down.

---

## Problem

Under `--dma` and aggressive `EXTCLK_DIV`, GP0 MMIO reads can **hang** (`devmem read` blocks → SSH dead → ~5 s watchdog reset). This is distinct from ping-pong overload where **`DMA_OVERWRITE_COUNT` climbs but SSH stays alive**.

**Primary repro (confirmed this session):**

- Arm DMA + acquisition, set divider to **125** (not only div **5**).
- Run tight loop: `while true; do devmem read 0x60; done`
- **Hang after a few minutes** (values like `0x5`, `0x4`, `0x2`, `0x0` seen before hang — ping-pong status was live).

**Hypothesis (unchanged):** `DMA_BUF_STATUS (0x60)` read data was driven from **live/combinational** status (`dma_buf_full_reg`, wrap logic) while GP0 sampled `RDATA` — same class as live `STATUS (0x20)` / channel reads. See `20260522b_axi-verification-and-fix-plan.md` Layer C.

---

## What was done (this session)

### 1. RTL — GP0 read snapshot (`ads1278_axi_slave.sv`)

Implemented **two-cycle AXI read** with **read-side snapshot flops**:

1. **Cycle 1 (`ARtransfer`):** Accept read address; latch all readable register/live values into `read_*` flops (including `read_dma_buf_status_reg`, `read_status_reg`, `read_ch_data[]`, etc.).
2. **Cycle 2:** Assert `RVALID`; drive `RDATA` from **`read_*` flops**, not live combinational mux.

Also updated `ARREADY` / `read_pending` FSM so reads no longer sample changing PL state on the same edge that completes the AXI beat.

**Not changed:** Ping-pong protocol — `DMA_BUF_ACK (0x64)` W1C semantics, wrap logic, DDR sample path.

**Local only:** No Vivado build run in dev environment (no `verilator`/`vivado` on hand). **Must rebuild bitstream on board build host before validation.**

### 2. Investigation — DMA architecture and rate limits

Clarified for operators:

| Concept | Meaning |
|---------|---------|
| **Frame rate** | ~`125 MHz / (2 × EXTCLK_DIV)` |
| **`0x60`** | Ping-pong **ownership** (buf full bits), not sample data |
| **Samples** | In **DDR** (mmap), configured by `DMA_BASE`/`DMA_SIZE`/`DMA_CTRL` |
| **`overflow: yes`** | SPI FSM overlap — new `DRDY` before previous frame finished (`STATUS[1]`, sticky until disable) |
| **`FIFO_DROPS (0x30)`** | Staged FIFO lost frame before DDR writer |
| **`DMA_OVERWRITE_COUNT (0x68)`** | Hardware wrapped into buffer still marked full (no/f slow `0x64` ACK) |
| **GP0 hang** | Incomplete AXI transaction — different from above |

### 3. Board observations (operator, this session)

| Observation | Interpretation |
|-------------|----------------|
| `read 0x60` loop at div **125** hung after minutes | Confirms Step B failure mode; target for post-snapshot retest |
| div **5**, enable only, `read 0x60` **all zeros** | Expected if **DMA not armed** (`DMA_CTRL ≠ 0x3`) — enable + divider alone does not set buf-full |
| `0x60` **stuck** (0 or 4) **without client** | Expected — server **arms DMA on connect** and **ACKs via `0x64` only with client** |
| `0x60` **cycles** (0, 5, 4, 2, …) **with client** | Expected healthy ping-pong when server drains + ACKs |
| Pre-fix hang at div **5** with `--dma` | Same GP0 class; do not use for sign-off until snapshot bitstream proven |

---

## RTL fix detail (for reviewers)

**File:** `fpga/rtl/ads1278_axi_slave.sv`

**Live sources (still updated by PL):**

- `dma_buf_full_reg`, `dma_active_buf_reg` — on `dma_phase4_wrap_pulse` and `DMA_BUF_ACK`
- `status_reg`, `ch_data[]` — from `ads1278_acq_top`
- `dma_buf_status_reg` — combinational pack of ownership flops (still used as snapshot **source**)

**CPU read path:**

- `REG_DMA_BUF_STAT (0x60)` → `bus.RDATA <= read_dma_buf_status_reg` (snapshot flop)
- Same pattern for `STATUS`, channels, FIFO/DMA status fields

**Writes unchanged:** `0x64` ACK, `0x28` divider, `0x24` CTRL, etc.

---

## Two failure modes (do not conflate)

| Symptom | Mechanism | MMIO works? |
|---------|-----------|-------------|
| `DMA_OVERWRITE_COUNT` ↑, SSH OK | Slow consumer / no ACK | Yes |
| `FIFO_DROPS` ↑, SSH OK | Capture faster than DDR staging | Yes |
| `overflow: yes` in snapshot | SPI `DRDY` overlap | Yes (sticky until disable) |
| `devmem read` hangs | GP0 AXI stall | **No** |

---

## Speed limit ladder (stepping `EXTCLK_DIV` down)

At each divider, run **5+ min** with client on `ads1278-server --dma`. Log: `{div, FIFO_DROPS_Δ, OVERWRITE_Δ, overflow, hung_y/n}`.

| First failure sign | Limit hit |
|--------------------|-----------|
| `devmem read` blocks | **GP0 / MMIO stability** |
| `overflow: yes` | **SPI capture FSM** (ADC rate vs shift timing) |
| `FIFO_DROPS` climbs | **PL FIFO → DDR writer** |
| `DMA_OVERWRITE_COUNT` climbs (SSH OK) | **Server/TCP drain** (Phase 10 bulk path) |
| Client frame gaps, flat `0x68` | **Host/client**, not board capture |

**Typical order after snapshot fix:** `OVERWRITE` → `FIFO_DROPS` → (optional) GP0 stress at extreme div + tight MMIO loops.

---

## `0x60` behavior cheat sheet

| Scenario | Expected `0x60` |
|----------|-----------------|
| Server listening, **no client** | **0** (DMA not armed) or stuck pattern if manually armed without ACK |
| Client connected, `--dma`, server keeping up | Cycles **0 → 5 → 4 → 2 → 0** (approx) |
| Client connected, server too slow | **`0x68` rises**; may see overwrite pending (bit 3) |
| Enable + div only, no `DMA_CTRL=0x3` | **Stays 0** — no wraps marking full |

**Server arms DMA on client connect** (`ads1278_dma_arm()` in `server/server.c`). Disconnect stops DMA (`dma_stop`).

---

## On-target validation (still open)

### A. Deploy snapshot bitstream

1. Build FPGA with modified `ads1278_axi_slave.sv`.
2. Deploy to `rp-f0ef77`.
3. Confirm baseline: `devmem read 0x28` loop OK 10+ min.

### B. Step B — post-fix stress (no server)

```bash
devmem write 0x38 0x0
devmem write 0x58 0xf
devmem write 0x3c 0x1e000000
devmem write 0x40 0x00010000
devmem write 0x24 0x2
devmem write 0x28 125
devmem write 0x38 0x3

while true; do devmem read 0x60; done
```

**Pass:** 10+ min, no hang. Log to `/root/ads1278-logs/axi-matrix.log`.

Repeat at div **271**, then optional div **5** stress only after 125/271 pass.

### C. Phase 9 sign-off (safe rate)

```bash
ads1278-server --dma
# client: SET_ENABLE, EXTCLK_DIV=625 (0x271)
```

Watch 5+ min:

```bash
devmem read 0x30    # FIFO_DROPS — want flat
devmem read 0x68    # OVERWRITES — want flat
devmem read 0x60    # toggles; clears after ACK
```

### D. Step dividers down

625 → 271 → 125 → … Stop at first of: hang, `overflow`, `FIFO_DROPS`, or rising `0x68`.

---

## Success criteria

### Snapshot / GP0

- [ ] Bitstream built and deployed with read snapshot RTL
- [ ] `while true; do devmem read 0x60; done` — **10+ min** at div **125**, DMA+capture, **no hang**
- [ ] Same at div **271**
- [ ] Optional: div **5** stress after above

### Phase 9 software

- [ ] `ads1278-server --dma` + client — **5+ min** at **`EXTCLK_DIV=0x271`**
- [ ] `FIFO_DROPS` delta **0**
- [ ] `DMA_OVERWRITE_COUNT` **flat** while connected
- [ ] Client sequential frames (no systematic gaps)

### Phase 10 (out of scope until GP0 + Phase 9 pass)

- Bulk TCP / board-side logging for high-rate capture without per-frame `SAMPLE`.

---

## Uncommitted repo changes (at handoff)

| Path | Change |
|------|--------|
| `fpga/rtl/ads1278_axi_slave.sv` | Read snapshot + 2-cycle read FSM |
| `server/server.c`, `server/server.h` | Phase 9 `--dma` consumer |
| `docs/feats/server.md`, `server-protocol.md` | DMA mode docs |
| `docs/handoffs/20260416_dma-route-migration-plan.md` | Phase 9 note |
| `docs/handoffs/20260424_phase8-capture-dma.md`, `20260524_*.md` | Validation updates |
| `docs/handoffs/20260527_phase9-dma-server-and-mmio-hang-debug.md` | Untracked prior handoff |

**Not done:** git commit, bitstream build, on-target proof of snapshot fix.

---

## Key files

| Area | Path |
|------|------|
| Read snapshot RTL | `fpga/rtl/ads1278_axi_slave.sv` |
| DMA server | `server/server.c`, `server/server.h` |
| MMIO map | `server/memory_map.h`, `docs/feats/fpga-register-map.md` |
| Frame layout | `server/dma_frame.h`, `docs/feats/dma-frame-record.md` |
| AXI debug plan | `docs/handoffs/20260522b_axi-verification-and-fix-plan.md` |
| Phase 9 + hang debug | `docs/handoffs/20260527_phase9-dma-server-and-mmio-hang-debug.md` |
| Phase 8 pass | `docs/handoffs/20260524_dma-frame-burst-alignment.md` |
| Migration plan | `docs/handoffs/20260416_dma-route-migration-plan.md` |
| Acquisition / overflow | `docs/feats/ads1278-acquisition-pipeline.md` |

---

## Related docs

- [Phase 9 DMA server + GP0 hang debug](20260527_phase9-dma-server-and-mmio-hang-debug.md)
- [AXI/GP0 verification plan](20260522b_axi-verification-and-fix-plan.md)
- [DMA frame burst alignment (Phase 8 pass)](20260524_dma-frame-burst-alignment.md)
- [DMA migration plan](20260416_dma-route-migration-plan.md)
- [Server feature doc](../feats/server.md)

---

## Suggested order for next session

1. **Build + deploy** bitstream with `ads1278_axi_slave.sv` read snapshot.
2. Run **Step B** (`read 0x60` loop) at div **125** — confirm hang is gone (10+ min).
3. Deploy **`ads1278-server --dma`**; run **Phase 9 checklist** at **`0x271`** with client.
4. If pass → **commit** FPGA + server + doc updates on `dma-work`.
5. Step dividers down; record first counter that fails (`overflow`, `FIFO_DROPS`, `0x68`).
6. Phase 10 bulk transport only after GP0 stable + Phase 9 signed off at moderate rates.
