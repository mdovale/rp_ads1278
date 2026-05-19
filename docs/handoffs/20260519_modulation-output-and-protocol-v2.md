# rp_ads1278 — modulation output and protocol v2 handoff

This handoff captures work from 2026-05-19: Speckit analysis of Moku Vref CSV data, FPGA/client/server changes for a programmable modulation square wave on E1 pin 5, and field bring-up issues observed while connecting the updated client to the board.

## Summary

- **Implemented (uncommitted):** Programmable LVCMOS square wave on `exp_p_io[5]` (package pin L16), MMIO register `MOD_DIV` @ `0x2C`, TCP protocol bump to `ads1278_v2` (64-byte messages, `mod_div` field), opcode `SET_MOD_DIV` (5), client **MOD freq** control in Hz.
- **Default hardware intent:** `MOD_DIV = 6_250_000` → **10 Hz** at 125 MHz (`f = 125e6 / (2 × mod_div)`).
- **ADS1278 path unchanged:** Pins 0–4, `EXTCLK_DIV`, `CTRL`, acquisition RTL — modulation is independent and not gated by acquisition enable.
- **Not committed:** 31 tracked files modified; `logged_files/` still untracked (Speckit scripts/plots; `*.csv` gitignored).
- **Field status (operator):** Client connected after server deploy; saw `RP_CAP:ads1278_v1` error before server update; after v2 server, MOD freq UI showed **0.100 Hz** (likely old bitstream or garbage `mod_div` read). Docker-based server build failed locally (daemon not running).

## Why this handoff exists

The next session needs to finish **deploying a matched triple** (FPGA bitstream + server v2 + client) and verify pin 5 and the MOD frequency readback, without re-deriving protocol layout or mistaking UI clamping for true 0.1 Hz output.

## Current repo state

### Git

- All modulation/protocol changes are **local modifications only** — no commit on this branch yet.
- `logged_files/` is **untracked** (analysis artifacts from Speckit runs; CSV files ignored by `.gitignore`).

### Protocol contract (v2 — preserve unless intentionally versioning again)

| Item | Value |
|------|--------|
| Capability line | `RP_CAP:ads1278_v2\n` |
| Command size | 8 bytes LE |
| Message size | **64** bytes LE (was 60 in v1) |
| New opcode | `5` = `SET_MOD_DIV` (`value >= 2`) |
| Message word 7 | `mod_div` (raw FPGA register) |
| Channel words | 8–15 (`ch1`..`ch8`) |

v1 clients **will not connect** to v2 servers (strict capability check). v2 clients **will not connect** to v1 servers.

### MMIO (addition)

| Offset | Name | Access | Behavior |
|--------|------|--------|----------|
| `0x2C` | `MOD_DIV` | R/W | Half-period divider; `f_mod = 125 MHz / (2 × MOD_DIV)` |
| Reset default | | | `6_250_000` → 10 Hz |

Existing registers through `0x28` unchanged. See `docs/feats/fpga-register-map.md`, `docs/feats/server-mmio-contract.md`.

### Board IO (pin 5)

| Signal | E1 | Pin | Direction | Notes |
|--------|-----|-----|-----------|--------|
| MOD | `exp_p_io[5]` | L16 | Output | 3.3 V square wave; runs continuously after bitstream load |
| ADS1278 | `exp_p_io[0:4]` | — | — | Unchanged |

See `docs/feats/board-io-wiring.md`, `README.md`.

### Tests run locally (passing)

- `make -C server test`
- `make -C server`
- `PYTHONPATH=client .venv/bin/python -m pytest client/tests -q` (16 passed)

Cross-build / Docker build on operator Mac: **not verified** in this session (see below).

## Work completed in this session

### 1. Speckit Vref noise analysis (local only)

- Script: `logged_files/moku_vref_speckit_analysis.py`
- Input: `logged_files/Vref noise/Vref_20260518_172209.csv` (Moku logger, 100 Hz, ~1 h)
- Outputs under `logged_files/Vref noise/`: ASD plot, time series, spectra CSV, summary JSON
- Note: 100 Hz capture cannot produce valid spectrum above ~50 Hz Nyquist; extending plot axis to 1 kHz would be misleading without a higher sample-rate capture.

### 2. Modulation feature (FPGA → client)

**FPGA**

- `fpga/rtl/ads1278_axi_slave.sv`: `mod_div_reg`, square-wave counter on `bus.ACLK`, `mod_o` output; read/write `0x2C`.
- `fpga/rtl/red_pitaya_top.sv`: `exp_p_io[5]` driven by `ads_mod`, tri-state enabled (`exp_p_t[5]=0`).
- `fpga/source/cons_rp125_14/ports.xdc`: SLEW/DRIVE on `exp_p_io[5]`.

**Server**

- `server/protocol.h`: v2 capability, 64-byte message, `mod_div` in snapshot.
- `server/memory_map.*`: `ADS1278_REG_MOD_DIV`, snapshot includes `mod_div`.
- `server/cmd_parse.c`: validate `SET_MOD_DIV` (`value >= 2`).
- `server/server.c`: apply command, include `mod_div` in streamed messages.

**Client**

- `client/ads1278_client/protocol.py`: Hz ↔ divider helpers, `pack_set_modulation_frequency`, v2 parse/build.
- `client/ads1278_client/main_window.py`: **MOD freq** spinbox (0.1–100 kHz), **Set MOD** button, status `mod: X.XXX Hz`.
- CSV logger adds `mod_div` column.
- `client/tools/fake_server.py` updated for v2.

### 3. Documentation updated

- `README.md`, `docs/feats/board-io-wiring.md`, `fpga-register-map.md`, `fpga.md`, `server-protocol.md`, `server.md`, `server-mmio-contract.md`, `client.md`, `client/README.md`.

## Field issues observed and diagnosis

### A) `unexpected capability line: 'RP_CAP:ads1278_v1'`

**Cause:** Updated **client** (expects v2) connected to **old server** on the board.

**Fix:** Build and deploy server from current tree; restart `ads1278-server`. Verify:

```bash
nc <rp-ip> 5000
# expect: RP_CAP:ads1278_v2
```

Build options on Mac:

- `./server-build-docker.sh` — requires Docker Desktop running.
- `./server-build-cross.sh` — requires `arm-linux-gnueabihf-gcc` (e.g. `brew install arm-linux-gnueabihf-gcc`).
- Build on-board: `make -C server` over SSH if toolchain available.

Then: `./server-deploy.sh --ip <rp-ip>` and restart service.

### B) MOD freq shows **0.100 Hz** after connect

**Cause (most likely):** Client displays `125e6 / (2 × mod_div)` from server snapshot. UI spinbox **minimum is 0.1 Hz** — any huge or invalid `mod_div` clamps to **0.100 Hz** display.

Common root causes:

1. **New server v2 + old FPGA** — read @ `0x2C` returns garbage (`0xDEADBEEF`, `0xFFFFFFFF`, etc.).
2. **`mod_div` not at default** — e.g. `625_000_000` (100× too large) → exactly 0.1 Hz; or value from accidental **Set MOD** at floor.
3. **Expected for 10 Hz:** `mod_div = 6_250_000` (`0x005F5E10`).

**Fix:** Deploy **new bitstream**, reboot/reload PL, then client **Set MOD** at **10 Hz**, or `rpdevmem` write `0x2C` = `6250000`. Confirm with scope on DIO5_P (L16).

### C) Docker build failure

```
Cannot connect to the Docker daemon at unix:///Users/saruul/.docker/run/docker.sock
```

Not a code defect — start Docker Desktop or use `server-build-cross.sh` / on-target build.

### D) Vivado BD warnings `S_AXI_GP2_*` / `S_AXI_GP3_*`

**Non-critical** — stale PS7 portmap metadata; project uses **M_AXI_GP0** only. Past builds completed bitstream with these warnings. See `docs/handoffs/20260408_remaining-fpga-work.md`.

## What was explicitly NOT changed

- `ads1278_acq_top`, SPI TDM, EXTCLK/SYNC behavior, default `EXTCLK_DIV = 625`.
- Modulation **not** tied to `ctrl_enable` — square wave runs whenever bitstream is loaded.
- On-board SMA ADC/DAC paths still idle (compatibility only).

## Success criteria for next session

1. **Matched deploy:** New FPGA bitstream + `ads1278-server` (v2) + local client from same tree.
2. **Handshake:** `nc` shows `RP_CAP:ads1278_v2`; client connects without capability error.
3. **MOD readback:** Client shows **~10.000 Hz** (or chosen frequency) after **Set MOD**; status line `mod: 10.000 Hz`.
4. **Hardware:** Scope on `exp_p_io[5]` (L16) shows ~3.3 V square wave at set frequency (50% duty).
5. **ADS1278 regression:** Enable acquisition, `frame_cnt` advances, channels plot; EXTCLK divider still works.
6. **Optional:** Commit modulation + v2 changes (exclude `logged_files/` unless intentionally adding scripts only).

## Recommended bring-up sequence

```bash
# Host — FPGA (if PL changed)
./fpga-build.sh
./fpga-deploy.sh --ip <rp-ip>
# reload bitstream per your usual procedure

# Host — server
./server-build-cross.sh    # or docker / on-board make
./server-deploy.sh --ip <rp-ip>
# restart ads1278-server on board

# Host — client
.venv/bin/python -m pip install -e ./client
.venv/bin/python client/main.py
# Connect → Set MOD 10 Hz → Enable → verify plots
```

### MMIO sanity (on board)

```bash
ads1278-rpdevmem snapshot
# expect mod_div: 6250000 after new bitstream reset

ads1278-rpdevmem read 0x2c
# expect 0x005F5E10 (6250000) for 10 Hz default
```

## Key files

| Area | File |
|------|------|
| MOD RTL + register | `fpga/rtl/ads1278_axi_slave.sv` |
| Pin assignment | `fpga/rtl/red_pitaya_top.sv` |
| Constraints | `fpga/source/cons_rp125_14/ports.xdc` |
| Protocol | `server/protocol.h`, `client/ads1278_client/protocol.py` |
| MMIO | `server/memory_map.h` |
| Client UI | `client/ads1278_client/main_window.py` |
| Speckit Vref script | `logged_files/moku_vref_speckit_analysis.py` |

## Open questions / follow-ups

- Confirm operator deployed **bitstream** as well as server; v2 server alone is insufficient for correct `mod_div` and pin 5 drive.
- Decide whether to commit Speckit analysis scripts under `logged_files/` or keep analysis local.
- Consider gating `mod_o` with a CTRL bit or enable if “modulation off” when acquisition disabled is desired (not implemented today).
- Protocol v2 breaks old clients — document in release notes if external tools parse the wire format.

## Related docs

- [Board IO Wiring](../feats/board-io-wiring.md)
- [FPGA Register Map](../feats/fpga-register-map.md)
- [Server Protocol](../feats/server-protocol.md)
- [Client](../feats/client.md)
- [Remaining FPGA work](20260408_remaining-fpga-work.md) (BD warnings)
- [Connection loss triage](20260430_connection-loss-triage-and-decision-tree.md) (long-run stability — separate issue)
