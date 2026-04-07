# FPGA

This doc is the top-level feature hub for the FPGA layer in `rp_ads1278`. It summarizes what the current FPGA implementation owns, what it exposes to software, and which focused docs describe the main sub-areas in detail.

## Goal

Provide one entry point for understanding the current FPGA layer: how it fits into the project, what behavior is implemented today, and where to go next for build, wiring, acquisition, and MMIO details. The current FPGA implementation aims to make ADS1278 acquisition available to the Red Pitaya PS through a small, software-friendly MMIO interface, while keeping the high-speed sampling path in PL logic.

## Scope

- In scope: the current FPGA layer as a system, including project generation, board IO ownership, acquisition behavior, top-level signal mapping, and the MMIO surface exposed to the PS.
- Out of scope: the TCP server protocol details, host GUI behavior, and any Linux-side abstractions above the raw MMIO contract, plus any bring-up claim that has not yet been validated on real hardware.

## Overview

The current repository now has in-tree implementation for `fpga/`, `server/`, and `client/`. The FPGA layer remains the source of truth for:

- board-facing ADS1278 digital wiring
- acquisition timing and channel latching behavior
- PS-visible MMIO control and status
- Vivado project generation and bitstream deployment flow

At a high level, the FPGA layer does four things today:

1. Drives the external ADS1278 signals on the Red Pitaya E1 expansion connector.
2. Generates `EXTCLK` and `SYNC`, and clocks in the ADS1278 TDM stream on `DOUT1`.
3. Latches eight 24-bit channels and packs acquisition state into a small AXI4-Lite register block.
4. Exposes that register block to the PS over AXI GP0 so the current `server/` can read and control the design.

## User-facing behavior

From the rest of the project’s perspective, the FPGA layer currently provides:

- one fixed board target: `rp125_14`
- one implemented board wiring contract on E1
- one acquisition path for 8-channel ADS1278 TDM capture
- one MMIO control/status block at `0x40000000`
- one script-based build and deployment path

What is implemented today:

| Area | Current behavior |
|------|------|
| Board IO | Uses E1 `exp_p_io[0:4]` for `SCLK`, `DOUT1`, `DRDY`, `SYNC`, and `EXTCLK` |
| Acquisition | Waits for `DRDY`, delays, clocks in 192 bits, latches CH1..CH8, updates `STATUS` |
| Control | Software can enable acquisition, trigger `SYNC`, and set `EXTCLK_DIV` |
| Register access | PS reads and writes a small AXI4-Lite aperture at `0x40000000` |
| Build/deploy | Repo scripts generate the project, build a bitstream, and deploy a `.bit.bin` to Red Pitaya OS 2.x+ |

What is not implemented today:

- no recorded end-to-end validated hardware bring-up result
- no recorded boot-cycle validation result for the `systemd` service path

## Architecture

The FPGA layer is organized around a small set of top-level responsibilities:

1. `red_pitaya_top.sv` is the synthesis top and connects PS, AXI, LEDs, and expansion IO.
2. `red_pitaya_ps.sv` and the generated block design expose the PS-side AXI GP0 interface into the PL.
3. `ads1278_axi_slave.sv` implements the software-visible register block.
4. `ads1278_acq_top.v` owns the acquisition datapath.
5. `ads1278_spi_tdm.v`, `ads1278_extclk_gen.v`, and `ads1278_sync_pulse.v` implement the core ADS1278-facing behaviors.
6. The TCL and XDC files define the Vivado project, block design, and board pin mapping.

The architectural boundary to keep in mind is:

- FPGA owns signal timing, sampling, latching, and MMIO exposure.
- The current `server/` owns PS-side MMIO access, sample interpretation, and network transport.
- The current `client/` owns host-side protocol decoding, plotting, and CSV logging.

## Key files

| Area | File |
|------|------|
| Top-level FPGA hub | `fpga/rtl/red_pitaya_top.sv` |
| PS integration | `fpga/rtl/red_pitaya_ps.sv` |
| Register block | `fpga/rtl/ads1278_axi_slave.sv` |
| Acquisition wrapper | `fpga/rtl/ads1278_acq_top.v` |
| SPI capture | `fpga/rtl/ads1278_spi_tdm.v` |
| Board constraints | `fpga/source/cons_rp125_14/ports.xdc` |
| Project config | `fpga/source/cfg_rp125_14/ads1278.tcl` |
| Block design | `fpga/source/system_design_bd_rp125_14/system.tcl` |
| Build script | `fpga-build.sh` |
| Deploy script | `fpga-deploy.sh` |

## Related docs

- [FPGA Register Map](fpga-register-map.md)
- [ADS1278 Acquisition Pipeline](ads1278-acquisition-pipeline.md)
- [Board IO Wiring](board-io-wiring.md)
- [FPGA Build And Deploy](fpga-build-and-deploy.md)
- [Server MMIO Contract](server-mmio-contract.md)
- [Current status and revised implementation plan](../handoffs/20260303_implementation-plan.md)
- [FPGA status and remaining bring-up work](../handoffs/20260304_fpga-work.md)
