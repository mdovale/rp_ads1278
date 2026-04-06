# rp_ads1278 - Current Status and Revised Implementation Plan

This handoff reflects the repository as it exists today. It replaces the earlier assumption that most FPGA work still needed to be created from scratch.

**Source of truth:** `README.md` describes the intended end-state. `.reference/` remains read-only and is still the best source for copying and adapting the missing `server/` and `client/` layers.

---

## Summary

- The repository already contains a substantial `fpga/` implementation.
- The `server/` and `client/` layers described in `README.md` are still absent.
- Root-level build and deploy scaffolding exists for FPGA and for a future server, but the full three-layer system has not yet been assembled or validated end to end.

---

## Current Implementation Snapshot

### FPGA

The FPGA layer is the only part of the planned architecture that has real implementation today.

Implemented now:

- `fpga/rtl/red_pitaya_top.sv` integrates the PS wrapper, AXI4-Lite bus, and ADS1278 slave.
- `fpga/rtl/ads1278_axi_slave.sv` exposes a register block for CH1..CH8, `STATUS`, `CTRL`, and `EXTCLK_DIV`.
- `fpga/rtl/ads1278_acq_top.v` wires together the SPI TDM receiver, EXTCLK generator, and SYNC pulse generator.
- `fpga/rtl/ads1278_spi_tdm.v` implements DRDY-triggered 192-bit TDM capture, sampling on SCLK rising edges.
- `fpga/rtl/ads1278_extclk_gen.v` and `fpga/rtl/ads1278_sync_pulse.v` implement clock generation and SYNC pulsing.
- `fpga/source/system_design_bd_rp125_14/system.tcl` maps the AXI GP0 register block at `0x40000000` with a `0x1000` byte range.
- `fpga/source/cons_rp125_14/ports.xdc` constrains the README signal mapping on E1 P-side pins:
  - `exp_p_io[0]` = SCLK
  - `exp_p_io[1]` = MISO
  - `exp_p_io[2]` = DRDY
  - `exp_p_io[3]` = SYNC
  - `exp_p_io[4]` = EXTCLK
- `fpga/source/cfg_rp125_14/ads1278.tcl` and the repo-root FPGA scripts provide the current build/deploy entry points.

### Server

The server layer is not implemented yet.

Current state:

- `server-build-cross.sh`, `server-build-docker.sh`, `server-deploy.sh`, and `server.Dockerfile` exist.
- There is no `server/` source tree in the repository.
- There is no `Makefile`, C source, MMIO logic, TCP protocol implementation, or command parser.

### Client

The client layer is not implemented yet.

Current state:

- There is no `client/` source tree in the repository.
- No frame decoder, GUI, logging path, or tests are present.

---

## What This Means For Planning

Earlier handoff assumptions are now outdated in two important ways:

1. Phase 2 is no longer a blank-slate FPGA task. Most of the intended RTL and integration work already exists.
2. The highest-value development work is now software integration: first a minimal server, then a minimal client, then full hardware bring-up.

---

## Revised Phases

### Phase 1: Close FPGA Validation Gaps

Before building higher layers, confirm the current FPGA work is reproducible and documented.

Tasks:

- Run and record a clean FPGA build path for `rp125_14`.
- Resolve the `fpga-build.sh` preflight expectation that `fpga/library/lib_src/my_cores_build_src` exists even though `make_cores.tcl` is currently a no-op.
- Confirm the intended Vivado version for the checked-in TCL flow and document whether it is `2017.2`, `2020.1`, or both.
- Verify register semantics and control behavior against the hardware notes:
  - `CTRL[1]` enable
  - `CTRL[0]` SYNC trigger
  - `EXTCLK_DIV`
  - `STATUS[0]` new data
  - `STATUS[1]` overflow
  - `STATUS[31:16]` frame count

### Phase 2: Implement the Minimal Server

Create the missing `server/` tree by copying and simplifying from `.reference/rpll_server/esw/`.

Minimum viable server responsibilities:

- Map the FPGA register block at `0x40000000`.
- Poll `STATUS` and read CH1..CH8.
- Convert 24-bit samples into a host-friendly frame format.
- Expose TCP streaming and a small command surface for enable, SYNC, and `EXTCLK_DIV`.
- Match deployed binary naming used by `server-deploy.sh` (`ads1278-server`).

### Phase 3: Implement the Minimal Client

Create the missing `client/` tree by adapting `.reference/rpll_client/`.

Minimum viable client responsibilities:

- Connect to the server and verify a capability string or protocol handshake.
- Decode frames containing one counter plus eight channels.
- Provide a simple live plot and basic logging/export.
- Expose controls for start/stop, SYNC, and `EXTCLK_DIV`.

### Phase 4: Hardware Bring-up

Once the FPGA build and server/client exist:

- Load the bitstream.
- Run the server on the Red Pitaya.
- Connect the client.
- Verify channel ordering, rate control, SYNC behavior, and overflow behavior on real hardware.

---

## Relevant Files

| Area | File |
|------|------|
| End-state definition | `README.md` |
| SPI timing notes | `ADS1278_SPI.md` |
| AXI GP0 notes | `docs/notes/AXI_GP0_REGISTER_MAP_HOWTO.md` |
| FPGA top-level | `fpga/rtl/red_pitaya_top.sv` |
| FPGA register block | `fpga/rtl/ads1278_axi_slave.sv` |
| FPGA acquisition wrapper | `fpga/rtl/ads1278_acq_top.v` |
| FPGA SPI TDM logic | `fpga/rtl/ads1278_spi_tdm.v` |
| FPGA build entry point | `fpga-build.sh` |
| Future server build scaffolding | `server-build-cross.sh`, `server-build-docker.sh`, `server-deploy.sh` |
| Reference codebase | `.reference/` |

---

## Success Criteria

The project reaches the README architecture only when all of the following are true:

- FPGA build is reproducible and documented.
- A `server/` implementation exists and can stream frames from the MMIO register block.
- A `client/` implementation exists and can display and log incoming data.
- End-to-end acquisition is exercised on hardware with the ADS1278EVM wiring described in `README.md`.

---

## Updated Checklist

- [x] FPGA build/deploy scaffolding exists
- [x] FPGA block design TCL exists
- [x] FPGA RTL for acquisition, control, and AXI register access exists
- [x] E1 pin mapping is implemented in constraints and top-level RTL
- [ ] FPGA build flow has been cleanly validated and documented
- [ ] `server/` source tree implemented
- [ ] `client/` source tree implemented
- [ ] End-to-end hardware integration tested
