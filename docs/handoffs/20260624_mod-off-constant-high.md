# MOD off (constant 3.3 V on pin 5) handoff

**Date:** 2026-06-24  
**Status:** **Implemented in repo (local changes, not committed at handoff time)**; **new bitstream + server + client deploy and on-target pin-5 verification still open**.

**Prior context:** `20260519_modulation-output-and-protocol-v2.md` (programmable MOD square wave on `exp_p_io[5]`, `SET_MOD_DIV`, client MOD freq control).

---

## Summary

Added end-to-end support for turning modulation **off** by writing **`MOD_DIV = 0`**. When off, the FPGA holds **`mod_o = 1`**, so **`exp_p_io[5]`** (package pin L16) drives a steady **3.3 V LVCMOS high**. When on, behavior is unchanged: square wave at `f = 125 MHz / (2 × MOD_DIV)`.

| `MOD_DIV` | Meaning |
|-----------|---------|
| `0` | MOD **off** — output held high |
| `1` | **Invalid** — rejected by server/client |
| `≥ 2` | MOD **on** — square wave at computed frequency |

**No protocol version bump.** Reuses opcode `SET_MOD_DIV` (5) and existing `mod_div` snapshot field (message word 7).

---

## Why this handoff exists

Operators need a software-controlled **NoMOD baseline** (constant high on pin 5) without disconnecting hardware or relying on the slowest possible square wave (0.1 Hz UI floor). The next session should **deploy a matched triple** (bitstream → server → client) and verify pin 5 with a scope/DMM.

**Safety:** On an **old bitstream**, writing `MOD_DIV = 0` clamps to divider `2` and outputs ~**31 MHz**, not DC high. Deploy the new bitstream **before** using MOD off from the updated client.

---

## Current repo state

### Git

15 tracked files modified locally (see **Files changed** below). Not committed at handoff time.

### Protocol contract (unchanged version)

| Item | Value |
|------|--------|
| Capability line | `RP_CAP:ads1278_v3` (client still accepts v2) |
| Opcode | `5` = `SET_MOD_DIV` |
| **New rule** | `value == 0` or `value >= 2`; `0` = MOD off/high |
| Message word 7 | `mod_div`; `0` means off |

### MMIO (updated semantics)

| Offset | Name | Behavior |
|--------|------|----------|
| `0x5C` | `MOD_DIV` | `0` = hold MOD high; `≥ 2` = half-period divider, `125 MHz / (2 × MOD_DIV)` |
| Reset default | | `6_250_000` → **10 Hz** (MOD starts **enabled**) |

See updated `docs/feats/fpga-register-map.md`, `docs/feats/server-mmio-contract.md`, `docs/feats/server-protocol.md`.

---

## Work completed

### 1. FPGA

**File:** `fpga/rtl/ads1278_axi_slave.sv`

- Added `mod_disabled = (mod_div_reg == 32'd0)`.
- When disabled: `mod_o <= 1'b1`, `mod_cnt <= 0`, no toggling.
- When enabled (`mod_div_reg >= 2`): existing counter/toggle logic unchanged.
- Register comment updated: `0 = off (hold MOD high); >=2 half-period`.

**File:** `fpga/rtl/red_pitaya_top.sv`

- Connector comment updated: pin 5 is 10 Hz default square wave, **high when off**.

### 2. Server

**File:** `server/cmd_parse.c`

- `SET_MOD_DIV` accepts `value == 0` or `value >= 2`.
- Error string: `"SET_MOD_DIV requires value 0 or >= 2"`.

**File:** `server/tests/test_cmd_parse.c`

- Asserts `0` valid, `1` invalid, `6250000` valid.

No changes needed in `server/server.c` or `server/memory_map.c` — MMIO write and snapshot readback already pass through `command->value`.

### 3. Client protocol

**File:** `client/ads1278_client/protocol.py`

- `MODULATION_OFF_DIV = 0`
- `modulation_divider_to_frequency_hz(0)` → `0.0`
- `modulation_frequency_to_divider(0.0)` → `0`
- `pack_set_modulation_div(0)` allowed; `pack_set_modulation_div(1)` rejected
- `pack_set_modulation_off()` wrapper added

**File:** `client/tools/fake_server.py`

- Accepts `SET_MOD_DIV` with `value == 0`.

### 4. Client UI

**File:** `client/ads1278_client/controller.py`

- `set_modulation(enabled, frequency_hz)` — off sends `mod_div 0`; on sends frequency.

**File:** `client/ads1278_client/main_window.py`

- **MOD enable** checkbox (default checked).
- Frequency spinbox disabled when unchecked.
- **Set MOD** sends off or frequency based on checkbox.
- Status readback: `mod_div == 0` → `mod: off`; else `mod: X.XXX Hz`.
- Checkbox/frequency sync from server snapshot when connected.

### 5. Documentation

Updated:

- `README.md`
- `docs/feats/client.md`
- `docs/feats/fpga-register-map.md`
- `docs/feats/server-mmio-contract.md`
- `docs/feats/server-protocol.md`

---

## Files changed

| Area | File |
|------|------|
| FPGA | `fpga/rtl/ads1278_axi_slave.sv`, `fpga/rtl/red_pitaya_top.sv` |
| Server | `server/cmd_parse.c`, `server/tests/test_cmd_parse.c` |
| Client | `client/ads1278_client/protocol.py`, `controller.py`, `main_window.py`, `client/tools/fake_server.py` |
| Tests | `client/tests/test_protocol.py`, `client/tests/test_controller_and_main_window.py` |
| Docs | `README.md`, `docs/feats/*.md` (see above) |

---

## Tests run locally (passing)

```bash
PYTHONPATH=client .venv/bin/python -m pytest \
  client/tests/test_protocol.py \
  client/tests/test_controller_and_main_window.py
# 25 passed

make -C server test
# test_cmd_parse, test_protocol_layout, test_dma_frame_layout, test_memory_map — all pass
```

New coverage includes:

- `mod_div 0 ↔ 0 Hz` conversion and `pack_set_modulation_div(0)`
- Rejection of `mod_div 1`
- Controller `set_modulation(False/True, …)` command packing
- Main window readback shows `mod: off` and unchecks MOD enable when `mod_div == 0`

---

## Deploy order

1. **FPGA bitstream** (required — old logic is unsafe for `MOD_DIV=0`)
2. **Server** (`cmd_parse.c` change)
3. **Client** (checkbox + protocol helpers)

Mismatch (new client + old bitstream sending `0`) is **dangerous**.

---

## Manual verification (on target)

After new bitstream:

```bash
# MOD off — pin 5 steady ~3.3 V
ads1278-rpdevmem write 0x5c 0

# MOD on at ~10 Hz
ads1278-rpdevmem write 0x5c 6250000
```

Client path:

1. Connect to board.
2. Uncheck **MOD enable**, click **Set MOD** → status should show `mod: off`, readback `mod_div: 0`.
3. Check **MOD enable**, set **10 Hz**, click **Set MOD** → `mod: 10.000 Hz`, scope shows square wave on pin 5.

Fake server (no board):

```bash
PYTHONPATH=client .venv/bin/python client/tools/fake_server.py
# Connect client, toggle MOD enable, confirm status line
```

---

## Operator notes

### Demod / CH8

With MOD off, `mod_i` is constant high — **no MOD edges**. `ads1278_demod.v` will not produce meaningful lock-in output on CH8. For NoMOD-style baselines, use raw channels (e.g. CH2) or clear `CTRL[2]` (demod enable).

### Analysis notebooks

`notebooks/low_freq_noise.ipynb` uses `f_mod = 125e6 / (2 * mod_div)`. Guard `mod_div == 0` as off (optional follow-up; not required for core feature).

### CSV logging

`mod_div=0` logs correctly in existing CSV columns; no schema change.

---

## Next steps for owner

1. Rebuild and deploy FPGA bitstream with MOD-off RTL.
2. Deploy updated server and client to the board host.
3. Verify pin 5: DC high when off, square wave when on.
4. Commit the 15-file change set when satisfied.
5. (Optional) Update `low_freq_noise.ipynb` to treat `mod_div == 0` as off in `f_mod` calculations.

---

## Related docs

- `docs/feats/fpga-register-map.md` — `MOD_DIV` register semantics
- `docs/feats/server-protocol.md` — `SET_MOD_DIV` validation
- `docs/feats/client.md` — MOD enable checkbox and manual QA step
- `20260519_modulation-output-and-protocol-v2.md` — original MOD feature handoff
