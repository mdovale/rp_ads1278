# rp_ads1278 - Next Development Steps

This handoff is for the next implementation session. It captures the current repository state and the most valuable order of work.

> Historical note: this handoff predates the in-tree `server/` and `client/` implementations. For the current repo state, start with `README.md`, `docs/feats/server.md`, `docs/feats/client.md`, and `docs/feats/fpga-build-and-deploy.md`.

## Summary

- The FPGA layer is implemented substantially enough to define the hardware/software contract.
- The server and client layers are still missing entirely.
- The next session should avoid redoing FPGA architecture work and instead use the new `docs/feats/` FPGA docs as the starting point for build validation and server implementation.

## Current Status

### Implemented

- FPGA RTL exists for:
  - AXI4-Lite register access
  - ADS1278 TDM capture
  - EXTCLK generation
  - SYNC pulse generation
- Top-level Red Pitaya integration exists in `fpga/rtl/red_pitaya_top.sv`.
- Block-design TCL exists and maps the MMIO aperture at `0x40000000`.
- Constraints for the E1 connector mapping exist in `fpga/source/cons_rp125_14/ports.xdc`.
- Root-level FPGA build and deploy scripts exist.
- Root-level server build and deploy scaffolding exists.

### Missing

- No `server/` source tree.
- No `client/` source tree.
- No recorded clean FPGA build result.
- No end-to-end hardware bring-up record.

## Constraints

- `README.md` is the end-state source of truth.
- `.reference/` is read-only, but it is the intended source for copying and adapting missing server/client code.
- The current hardware/software contract is MMIO over AXI GP0, not DMA to DDR.

## Read These First

Before doing new implementation work, read the FPGA feature-doc set in this order:

1. `docs/feats/fpga.md`
2. `docs/feats/fpga-build-and-deploy.md`
3. `docs/feats/board-io-wiring.md`
4. `docs/feats/ads1278-acquisition-pipeline.md`
5. `docs/feats/fpga-register-map.md`
6. `docs/feats/server-mmio-contract.md`

Use the feature docs as the primary working summary. Drop into RTL, TCL, and shell scripts only when:

- validating that the docs still match the code
- fixing a documented gap
- implementing the missing `server/` or `client/` layers

## Recommended Order Of Work

### 1. Validate The FPGA Build Flow

Goal: make the checked-in FPGA implementation reproducible.

Tasks:

- Start from `docs/feats/fpga-build-and-deploy.md`.
- Run a clean `rp125_14` build.
- Resolve the `fpga-build.sh` core-generation preflight mismatch around `my_cores_build_src`.
- Record the Vivado version that actually works with the current TCL.
- Confirm bitstream naming and deployment assumptions used by `fpga-deploy.sh`.
- If behavior differs from the current docs, update the relevant feature doc as part of the same session.

### 2. Define The Server Contract Before Writing The Server

Goal: turn the current FPGA register block into a stable software target.

Tasks:

- Start from `docs/feats/server-mmio-contract.md`, `docs/feats/fpga-register-map.md`, and `docs/feats/ads1278-acquisition-pipeline.md`.
- Freeze the current register offsets and meanings from `ads1278_axi_slave.sv`.
- Decide the minimal network frame format.
- Decide the minimal command set:
  - enable or disable acquisition
  - trigger SYNC
  - set `EXTCLK_DIV`
- Decide whether the server will poll `STATUS` only or use an interrupt path later.
- Treat the current docs as the baseline contract unless the RTL is deliberately changed.

### 3. Implement A Minimal Server

Goal: make the FPGA observable from Linux on the Red Pitaya.

Minimum scope:

- Use `docs/feats/server-mmio-contract.md` as the hardware-facing contract.
- Add `server/Makefile`.
- Add a `/dev/mem` MMIO layer for `0x40000000`.
- Read CH1..CH8 and `STATUS`.
- Stream a simple frame over TCP.
- Accept basic control commands for enable, SYNC, and divider writes.

Suggested source material:

- `.reference/rpll_server/esw/`

### 4. Implement A Minimal Client

Goal: prove the streaming path with the smallest useful host UI.

Minimum scope:

- Connect to the server.
- Decode one counter plus eight channels.
- Plot live traces.
- Show connection state and frame counter.
- Allow start/stop, SYNC, and divider control.
- Log to CSV.

Suggested source material:

- `.reference/rpll_client/`

### 5. Run First Hardware Bring-up

Goal: validate the complete chain on the board with the ADS1278EVM.

Checks:

- Use `docs/feats/board-io-wiring.md` and `docs/feats/ads1278-acquisition-pipeline.md` as the bring-up checklist context.
- Acquisition starts and stops cleanly.
- Channel ordering is stable.
- `EXTCLK_DIV` changes sample cadence as expected.
- `SYNC` produces the expected recovery behavior.
- Overflow behavior is observable and understandable.

## Key Files

| Area | File |
|------|------|
| End-state definition | `README.md` |
| FPGA hub doc | `docs/feats/fpga.md` |
| FPGA build/deploy doc | `docs/feats/fpga-build-and-deploy.md` |
| FPGA wiring doc | `docs/feats/board-io-wiring.md` |
| FPGA acquisition doc | `docs/feats/ads1278-acquisition-pipeline.md` |
| FPGA register doc | `docs/feats/fpga-register-map.md` |
| Server MMIO contract doc | `docs/feats/server-mmio-contract.md` |
| SPI timing note | `ADS1278_SPI.md` |
| AXI GP0 note | `docs/notes/AXI_GP0_REGISTER_MAP_HOWTO.md` |
| Future server scaffolding | `server-build-cross.sh`, `server-build-docker.sh`, `server-deploy.sh` |

## Success Criteria For The Next Session

- The FPGA build flow is either proven or its blocking issue is fixed and documented.
- A concrete register-map and frame-format contract exists for software.
- Work begins in `server/` rather than reopening already-implemented FPGA architecture questions.
- Any newly discovered FPGA behavior changes are reflected in the relevant `docs/feats/` doc instead of only in ad hoc notes.
