# Demod post-edge sample skip handoff

**Date:** 2026-06-29  
**Status:** **Implemented in repo (local changes, not committed at handoff time)**; **bitstream deploy, calibrated `N_SKIP` write, and on-target CH8 ASD comparison still open**.

**Prior context:** [`20260622_demodulation-plan.md`](20260622_demodulation-plan.md) (half-cycle CH1→CH8 demod), [`20260519_modulation-output-and-protocol-v2.md`](20260519_modulation-output-and-protocol-v2.md) (MOD on `exp_p_io[5]`).

---

## Summary

Added an MMIO-only knob to skip the first **N** ADC samples after every MOD edge before CH1 contributes to the half-cycle demod average. This excludes RC settling samples from `sum_pos` / `sum_neg` and reduces demod bias/noise.

| Item | Value |
|------|--------|
| Register | `DEMOD_SKIP @ 0x6C`, R/W, bits `[15:0]` |
| Reset default | `0` (backward compatible — same as pre-change demod) |
| Scope | FPGA RTL + server constant + docs + optional RTL tb |
| **Not in scope** | Protocol bump, client UI, CSV columns, `SET_DEMOD_SKIP` opcode |

**No protocol version bump.** Configure via existing generic MMIO write (`ads1278-rpdevmem` or `/dev/mem`).

---

## Problem

`ads1278_demod` previously averaged **all** CH1 samples in each MOD half-cycle, including the first samples after each edge where the analog chain is still settling. That biases the half-cycle mean and adds noise.

## Solution

On each `new_data` while demod is enabled:

1. **MOD edge** — finalize previous half averages (unchanged); reset `post_edge_count` to `0`.
2. **`post_edge_count < DEMOD_SKIP`** — increment counter only; do **not** add sample to sum/count.
3. **Else** — accumulate sample into `sum_pos` or `sum_neg` as before.

Edge cases preserved:

- `DEMOD_SKIP = 0` → identical to original demod behavior.
- Empty half-cycle (`count == 0`) → existing fallback holds previous `avg_pos` / `avg_neg`.
- Demod disable / reset → clears `post_edge_count` with sums and counts.

---

## Current repo state

### Git

Tracked files modified locally (see **Files changed** below). `fpga/sim/` is untracked. Not committed at handoff time.

Unrelated local WIP in working tree (not part of this feature):

- `notebooks/low_freq_noise.ipynb`
- `notebooks/ch8_demod_noise_MOD10_Gain4.ipynb`

### MMIO

| Offset | Name | Access | Behavior |
|--------|------|--------|----------|
| `0x6C` | `DEMOD_SKIP` | R/W | Bits `[15:0]` = post-edge samples to skip before accumulation |
| Reset | | | `0` |
| Upper half | | | Writes to bits `[31:16]` ignored; reads return `0` in `[31:16]` |

Server constant:

```c
// server/memory_map.h
ADS1278_REG_DEMOD_SKIP = 0x6c
```

---

## Work completed

### 1. FPGA — demod skip logic

**File:** `fpga/rtl/ads1278_demod.v`

- Added input `demod_skip [15:0]`.
- Added `post_edge_count` and `skip_sample` gating around accumulation.
- First post-edge sample is `post_edge_count == 0`; it is skipped when `demod_skip > 0`.

### 2. FPGA — top-level wiring

**File:** `fpga/rtl/ads1278_acq_top.v`

- Added input `demod_skip [15:0]`.
- Passed through to `ads1278_demod` instance (replaces prior tie-off `16'd0`).

### 3. FPGA — AXI register

**File:** `fpga/rtl/ads1278_axi_slave.sv`

- Added `REG_DEMOD_SKIP` (`0x1B` word index → byte offset `0x6C`).
- Added `demod_skip_reg [15:0]`, reset `0`.
- Write decode: byte strobes `[1:0]` only.
- Read mux: zero-extended 16-bit value.
- Register map header comment updated.

### 4. Server

**File:** `server/memory_map.h`

- Added `ADS1278_REG_DEMOD_SKIP = 0x6c`.

No changes to `server/server.c`, `server/protocol.h`, or `server/cmd_parse.c`. Configuration is via direct MMIO only.

### 5. Documentation

Updated:

- `docs/feats/fpga-register-map.md` — `DEMOD_SKIP` row and semantics
- `docs/feats/server-mmio-contract.md` — register row, reset behavior, manual QA step
- `docs/handoffs/20260622_demodulation-plan.md` — short post-edge skip bring-up section appended

### 6. RTL testbench (optional)

**File:** `fpga/sim/ads1278_demod_tb.v` (new, untracked)

Self-checking bench for:

- `demod_skip = 0` — edge sample included in average
- `demod_skip = 3` — first three post-edge samples excluded

---

## Files changed

| Area | File |
|------|------|
| FPGA RTL | `fpga/rtl/ads1278_demod.v`, `fpga/rtl/ads1278_acq_top.v`, `fpga/rtl/ads1278_axi_slave.sv` |
| Server | `server/memory_map.h` |
| Docs | `docs/feats/fpga-register-map.md`, `docs/feats/server-mmio-contract.md`, `docs/handoffs/20260622_demodulation-plan.md` |
| Sim | `fpga/sim/ads1278_demod_tb.v` (new) |

---

## Tests run locally

```bash
make -C server
# server and rpdevmem build OK
```

RTL sim **not run** in handoff environment (`iverilog` / `verilator` / Vivado sim tools not on PATH).

To run the bench when a simulator is available:

```bash
iverilog -g2012 -o /tmp/ads1278_demod_tb.vvp \
  fpga/sim/ads1278_demod_tb.v fpga/rtl/ads1278_demod.v
vvp /tmp/ads1278_demod_tb.vvp
# expect: ads1278_demod_tb PASS
```

---

## Deploy order

1. **FPGA bitstream** (required — old bitstream has no `DEMOD_SKIP` register and hard-wires skip to `0`)
2. **Server** (optional for MMIO constant only; `rpdevmem` works without server rebuild)
3. No client deploy needed

Mismatch: writing `0x6C` on an **old bitstream** hits an unmapped/dead register offset — no demod skip effect.

---

## Calibrating `N_SKIP`

Do **not** set `DEMOD_SKIP` to “samples in 10 ms.” The register is **post-edge skip count**, not a time window.

At `EXTCLK_DIV = 10`:

```text
fs_adc = 125e6 / (2 × 10 × 512) ≈ 12,207 Hz
samples in 10 ms ≈ 122        ← timing reference only
```

Recommended workflow (notebook, before or after deploy):

1. Load a MOD-on recording; use raw CH1.
2. Segment half-cycles; overlay/average rising edges.
3. Fit `V(t) = V_final − ΔV·exp(−t/τ)` or read index at 99% plateau.
4. `N_skip = ceil(k × τ × fs_adc)` with `k = 3..5`.
5. At ~12 kHz and `τ ≈ 2–5 ms`, expect **N ≈ 25–60** (not 122 unless τ is much longer).

Upper bound: keep `N_skip < 0.5 × fs_adc / (2 × f_mod)`. At 10 Hz MOD and `EXTCLK_DIV = 10`, half-cycle ≈ **610** samples — `N_skip = 122` is allowed but skips ~20% of each half.

---

## Manual verification (on target)

After new bitstream:

```bash
# Confirm reset
ads1278-rpdevmem read 0x6c
# expect 0

# Baseline: no skip
ads1278-rpdevmem write 0x6c 0
ads1278-rpdevmem write 0x24 0x6    # enable + demod

# Calibrated skip (example only — use notebook value)
ads1278-rpdevmem write 0x6c <N_SKIP>
ads1278-rpdevmem write 0x24 0x6
```

Acceptance:

1. CH1 raw stream unchanged.
2. CH8 demod updates ~10 Hz with demod enabled.
3. Compare CH8 ASD at `N_SKIP = 0` vs calibrated `N_SKIP` in notebook.
4. Confirm diminishing returns as `N_SKIP` increases.

---

## Operator notes

### What changes vs what does not

| Path | Effect of `DEMOD_SKIP` |
|------|------------------------|
| CH1 MMIO / DMA / CSV | **Unchanged** |
| CH8 with `CTRL[2] = 0` | **Unchanged** (raw CH8) |
| CH8 with `CTRL[2] = 1` | Demod average excludes first N post-edge samples |

### Empty half-cycle behavior

If `N_SKIP` consumes an entire half-cycle, counts stay zero and CH8 can **hold** the previous demod value via the existing divide-by-zero guard.

### MOD off

With `MOD_DIV = 0` (MOD held high), there are no MOD edges — demod skip has no meaningful effect. See [`20260624_mod-off-constant-high.md`](20260624_mod-off-constant-high.md).

---

## Next steps for owner

1. Rebuild and deploy FPGA bitstream with `DEMOD_SKIP` register.
2. Run notebook edge-settling calibration; choose `N_SKIP`.
3. Write `0x6C`, enable demod, compare CH8 ASD `N=0` vs calibrated `N`.
4. (Optional) Run `fpga/sim/ads1278_demod_tb.v` in CI or local sim.
5. Commit when satisfied.

---

## Related docs

- [`docs/feats/fpga-register-map.md`](../feats/fpga-register-map.md) — full register map
- [`docs/feats/server-mmio-contract.md`](../feats/server-mmio-contract.md) — PS MMIO contract
- [`20260622_demodulation-plan.md`](20260622_demodulation-plan.md) — original demod algorithm and enable path
