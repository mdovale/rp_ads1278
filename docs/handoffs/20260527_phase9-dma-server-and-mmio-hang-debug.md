# Phase 9 DMA server + GP0 hang debug handoff

**Date:** 2026-05-27  
**Board:** `rp-f0ef77` (and similar)  
**Status:** Phase 8 parse/drop tests **passed** at `EXTCLK_DIV=0x271`. Phase 9 **`ads1278-server --dma`** implemented in repo; **on-target Phase 9 validation and AXI hang fix still open**. Operator saw **same freeze** at **`EXTCLK_DIV=5`** in **`--dma`** mode.

---

## Summary

This session moved the project from “DDR parse works with `devmem`” to “server can consume ping-pong buffers,” and clarified that **full buffers** and **GP0 AXI stalls** are different failure modes.

| Area | State |
|------|--------|
| Phase 8 (128-byte stride, canary, `dma-frames`) | **Passed** on-target at `0x271` — see `20260524_dma-frame-burst-alignment.md` |
| Phase 9 (server DDR consumer + `DMA_BUF_ACK`) | **Implemented** (`server/server.c --dma`); **not fully validated** on board with client |
| GP0 freeze at aggressive divider | **Reproduced** with `ads1278-server --dma` and `EXTCLK_DIV=5` — treat as **AXI/MMIO hang**, not ping-pong “no response” |
| RTL fix for live read mux | **Not done** — follow `20260522b_axi-verification-and-fix-plan.md` Layer C/D |

**Next owner:** (1) Validate Phase 9 at safe divider (`0x271`). (2) Isolate and fix GP0 stall on hot `--dma` path (`read 0x60` / command `read 0x20` / write `0x28`).

---

## What was done

### Phase 8 — on-target validation (complete)

- **128-byte DDR stride + canary** `0xAD127831` confirmed with `devmem dma-frames` (`pad=ok`, `gap=1`).
- **Short test (2 s):** `FIFO_DROPS` delta **0**, counts **1→64**, `frame_start_phase=30` (canary at word **29**; do not use fixed `ddr-read 31` alone).
- **Long soak (300 s script):** `FIFO_DROPS` **0** throughout; `DMA_OVERWRITE_COUNT` rose (10→21→33 by 90 s) **without** server ACK — expected.
- Board-local scripts: `dma-drop-test.sh`, `dma-drop-test-long.sh` (not in repo; copy to board).

Details: `docs/handoffs/20260524_dma-frame-burst-alignment.md`.

### Phase 9 — server implementation (in repo, needs board proof)

**CLI:**

```text
ads1278-server [--dma] [--dma-base ADDR] [--dma-size BYTES] [--poll-ms N] ...
```

Defaults: `--dma-base 0x1e000000`, `--dma-size 0x00010000` (page-aligned).

**Behavior (`--dma`):**

1. At startup: mmap **both** ping-pong DDR halves (`base` and `base + size`).
2. On client connect: program DMA (`DMA_CTRL=0x3` capture), clear IRQ/ACK, same as bring-up.
3. Main loop: **`read DMA_BUF_STATUS (0x60)`** every `--poll-ms`; if buf0/buf1 full → parse DDR (128-byte stride, canary phase) → emit one legacy **`SAMPLE` per frame** → **`write DMA_BUF_ACK (0x64)`**.
4. On disconnect: `DMA_CTRL=0`.
5. **Does not** poll `CH1`–`CH8` on the hot path. Commands still use MMIO (`SET_ENABLE`, `SET_EXTCLK_DIV`, etc.).

**Legacy mode (default):** unchanged latest-sample MMIO polling.

**Files:** `server/server.c`, `server/server.h`; docs updated in `docs/feats/server.md`, `docs/feats/server-protocol.md`, migration plan Phase 9 note.

**Build:** `make -C server` and `make -C server test` pass locally.

### Operator incident — `EXTCLK_DIV=5` + `--dma` freeze

- User set divider to **5** (extremely fast vs passing tests at **`0x271`**).
- **`ads1278-server --dma`** — same **SSH/`devmem` hang / watchdog** class as pre-DMA issues.
- **Not** explained by “buffer full blocks AXI”: full buffers expose **`0x60` / `0x68`** via normal reads; freeze = **incomplete GP0 transaction**.

**Hypothesis (consistent with `20260522b`):** In `--dma`, the hot GP0 read is **`0x60`**, whose read data is **combinational** from `dma_buf_full_reg` / wrap logic updated on **`dma_phase4_wrap_pulse`** while the AXI slave samples `RDATA` — same class as reading live **`STATUS`/channels** in legacy mode. Setting divider to **5** is also a **write to `0x28`** plus immediate **`read 0x20`** on command ACK path.

---

## Two failure modes (do not conflate)

| Symptom | Mechanism | MMIO still works? |
|---------|-----------|-------------------|
| `DMA_OVERWRITE_COUNT` climbs, SSH OK | Ping-pong full, no/f slow **`DMA_BUF_ACK`** | Yes — `read 0x60`, `read 0x68` return |
| SSH dead, `devmem read` hangs, ~5 s reset | **GP0 `RVALID`/`BVALID` stuck** | No |

Phase 9 fixes the **first** (when consumer keeps up). It does **not** fix the **second** (RTL/AXI under extreme load).

---

## MMIO map relevant to `--dma`

| Offset | Register | CPU | Source at read mux | `--dma` hot path? |
|--------|----------|-----|-------------------|-------------------|
| `0x20` | `STATUS` | R | Live SPI (`frame_cnt`, pulses) | On **commands** only |
| `0x24` | `CTRL` | R/W | Flop | Commands |
| `0x28` | `EXTCLK_DIV` | R/W | Flop | **Write** when changing rate |
| `0x38` | `DMA_CTRL` | R/W | Flop | Connect/disconnect |
| `0x60` | `DMA_BUF_STATUS` | **R only** | **Combinational** from `dma_buf_full`, `active_buf`, overwrite pending | **Poll every loop** |
| `0x64` | `DMA_BUF_ACK` | **W only** | Clears full bits in `dma_buf_full_reg` | After drain |
| `0x68` | `DMA_OVERWRITE_COUNT` | R | Flop (increments on wrap into full buf) | Debug |

**Note:** CPU never writes `0x60`. CPU writes **`0x64`**. PL updates the state behind **`0x60`** on every buffer wrap.

---

## How to validate Phase 9 (safe rate)

**Prerequisites:** Current bitstream + deployed `ads1278-server` from this repo. `devmem` → `ads1278-rpdevmem`.

```bash
ln -sf /usr/local/bin/ads1278-rpdevmem /usr/local/bin/devmem
```

### 1. Start DMA server

```bash
ads1278-server --dma
# stderr: Listening on port 5000 using /dev/mem (DMA mode)
```

### 2. Enable acquisition (separate SSH or client)

```bash
devmem write 0x24 0x2
devmem write 0x28 0x271
```

Or client: `SET_ENABLE 1` after connect (server arms DMA on connect but does not enable ADC by itself).

### 3. Connect client (or minimal TCP consumer)

Keep one client connected for several minutes.

### 4. Watch counters (while server running)

```bash
devmem read 0x30    # FIFO_DROPS — want 0 or flat
devmem read 0x68    # DMA_OVERWRITE_COUNT — want flat (Phase 9 ACK working)
devmem read 0x60    # buf full bits may toggle; should clear after ACK
```

**Pass:** `FIFO_DROPS` delta **0**; `DMA_OVERWRITE_COUNT` **does not climb** like the 300 s soak **without** server (where it went 10→21→33…).

**Fail (overload, not necessarily hang):** `OVERWRITES` rise but SSH OK → server too slow (TCP/divider); tune rate or Phase 10 bulk path.

**Fail (hang):** `devmem read` blocks → stop; use debug section below; **do not** use div 5 for Phase 9 sign-off.

### 5. Optional: compare legacy vs DMA

```bash
ads1278-server              # legacy — skips frames at high rate
ads1278-server --dma        # should preserve frames if GP0 stable
```

---

## How to debug the GP0 hang (`--dma`, aggressive divider)

Log to `/root/ads1278-logs/axi-matrix.log` (create dir). One line per test:

```text
{test_id, dma_mode, extclk_div, last_cmd, hung_yes/no, time_to_hang_s}
```

Base protocol: `docs/handoffs/20260522b_axi-verification-and-fix-plan.md`.

### Prerequisites

```bash
devmem read 0x24
devmem read 0x28
# Expect sane values after load; if 0xff/0 or hang, redeploy bitstream first
```

### Step A — Confirm hang is GP0, not “buffer full”

With **`--dma`**, acquisition on, **`EXTCLK_DIV=0x271`** first:

```bash
devmem read 0x60
devmem read 0x68
```

Both must return immediately. Then try **`0x271`** with server `--dma` for 5+ min before any stress.

Only after that, reproduce stress (e.g. div **125**, then **63** — avoid jumping to **5** until matrix says so).

### Step B — Isolate `--dma` hot read (`0x60`)

**Stop server** to avoid contention. Arm DMA like server:

```bash
devmem write 0x38 0x0
devmem write 0x58 0xf
devmem write 0x3c 0x1e000000
devmem write 0x40 0x00010000
devmem write 0x24 0x2
devmem write 0x28 5          # or 125 for softer stress
devmem write 0x38 0x3
```

Loop **only** what the DMA server polls:

```bash
while true; do devmem read 0x60; done
```

| Result | Interpretation |
|--------|----------------|
| Hangs | **`0x60` read path** under hot DMA/acq — prime RTL target (snapshot/latch `dma_buf_status` on read) |
| OK 10+ min | Hot read OK at that divider; hang may need **server + TCP** or **command path** |

### Step C — Isolate command-path live read (`0x20`)

```bash
while true; do devmem read 0x20; done
```

| Result | Interpretation |
|--------|----------------|
| Hangs | **`STATUS`** / SPI live mux — same as legacy snapshot issue |
| OK but B hung | Focus on **`0x60`** |

### Step D — Static flop baseline

```bash
while true; do devmem read 0x28; done
```

| Result | Interpretation |
|--------|----------------|
| Hangs at div 5 | Broader GP0 timing/FSM (Layer A/B/C), not only live mux |
| OK | Likely **live mux** registers (`0x20`, `0x60`, FIFO/DMA status) at high wrap rate |

### Step E — Write path (setting divider)

Hang **immediately** when client sets `EXTCLK_DIV=5` may be **write `0x28`** (`BVALID`) not read:

```bash
devmem write 0x24 0x2
devmem write 0x28 5
devmem read 0x28
```

If write hangs → write-channel / FSM debug.

### Step F — Server running, narrow repro

1. `ads1278-server --dma`
2. Connect client; send **only** `SET_EXTCLK_DIV` stepping **625 → 271 → 125** (not 5).
3. Note whether hang is on **command** or after sustained polling.

### Step G — FPGA-side follow-up (`20260522b`)

If B/C implicate live mux on **`0x60`** / **`0x20`**:

1. **Layer C fix:** Register/latch read datapath in `ads1278_axi_slave.sv` for registers fed by changing PL state (channels, `STATUS`, **`dma_buf_status`**).
2. **Layer D:** Per-frame snapshot in acq domain if SPI/AXI interaction persists.
3. **ILA** on GP0: `ARVALID`, `ARREADY`, `RVALID`, `RREADY` during failing loop on `0x60`.
4. Re-run acceptance matrix at div **125** then **271** before div **5**.

---

## Interpretation table (`--dma`)

| Observation | Likely cause |
|-------------|----------------|
| `OVERWRITES` up, SSH OK | Slow consumer / TCP; increase `--poll-ms` or lower rate; not AXI stall |
| `FIFO_DROPS` up, SSH OK | Capture faster than DDR path; lower `EXTCLK_DIV` |
| Any `devmem read` hangs | **GP0 AXI stall** — `20260522b` |
| Hang only at div 5, OK at `0x271` | Rate-induced live-mux / timing issue |
| `read 0x60` loop hangs, `read 0x28` OK | Target **`DMA_BUF_STATUS`** mux + wrap logic |
| Hang right after SET_EXTCLK_DIV | **Write `0x28`** or following **`read 0x20`** |

---

## Success criteria

### Phase 9 sign-off (software)

- [ ] `ads1278-server --dma` runs 5+ min with client at **`EXTCLK_DIV=0x271`**
- [ ] `FIFO_DROPS` delta **0** (or explained)
- [ ] `DMA_OVERWRITE_COUNT` **flat** while server connected (ACK keeps up)
- [ ] Client receives sequential samples (no systematic `+2` gap from polling)

### GP0 / AXI sign-off (hardware + software)

- [ ] `while true; do devmem read 0x60; done` stable 10+ min at **div 125** with DMA+capture on
- [ ] Same at **div 271** with `ads1278-server --dma`
- [ ] Phase 6 acceptance matrix in `20260522b` passes after RTL fix
- [ ] div **5** only after above (optional stress, not required for Phase 9)

---

## Suggested RTL direction (if `0x60` read implicated)

In `ads1278_axi_slave.sv`, treat **`dma_buf_status_reg`** like channel/`STATUS` data:

- On AXI read strobe to `0x60`, latch **`dma_buf_full_reg`**, **`dma_active_buf_reg`**, and overwrite pending into **stable flops** before driving `RDATA`.
- Optionally double-buffer for metastability if wrap pulse aligns with read (same clock domain still benefits from clean snapshot).

Do **not** confuse with ping-pong protocol change: **`0x64` ACK** semantics stay the same.

---

## Key files

| Area | Path |
|------|------|
| DMA server | `server/server.c`, `server/server.h` |
| MMIO map | `server/memory_map.h`, `docs/feats/fpga-register-map.md` |
| Frame layout | `server/dma_frame.h`, `docs/feats/dma-frame-record.md` |
| AXI slave (read mux) | `fpga/rtl/ads1278_axi_slave.sv` |
| DMA ownership logic | `fpga/rtl/ads1278_axi_slave.sv` (`dma_buf_full_reg`, wrap pulse) |
| Bring-up tool | `server/rpdevmem.c` (`devmem`) |
| Phase 8 results | `docs/handoffs/20260524_dma-frame-burst-alignment.md` |
| AXI debug plan | `docs/handoffs/20260522b_axi-verification-and-fix-plan.md` |
| Migration plan | `docs/handoffs/20260416_dma-route-migration-plan.md` |
| Connection loss triage | `docs/handoffs/20260430_connection-loss-triage-and-decision-tree.md` |

---

## Related docs

- [DMA frame burst alignment (Phase 8 pass)](20260524_dma-frame-burst-alignment.md)
- [Phase 8 capture handoff](20260424_phase8-capture-dma.md)
- [DMA migration plan](20260416_dma-route-migration-plan.md)
- [AXI/GP0 verification plan](20260522b_axi-verification-and-fix-plan.md)
- [Server feature doc](../feats/server.md)

---

## Suggested order for next session

1. Deploy cross-built `ads1278-server`; run **Phase 9 validation** at `0x271` (checklist above).
2. If pass → commit Phase 9 server + doc updates.
3. Run **Step B** (`read 0x60` loop) at div **125** with DMA armed — log to `axi-matrix.log`.
4. If `0x60` hangs → implement **read snapshot** in `ads1278_axi_slave.sv`; rebuild bitstream; re-test matrix.
5. Only then retry **`--dma` + client** at stepped dividers; leave div **5** for last stress.
6. Phase 10 (bulk TCP) remains out of scope until GP0 stable at moderate rates.
