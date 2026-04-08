# FPGA Register Map

This doc covers the current MMIO register block exposed by the FPGA acquisition path in `rp_ads1278`. It is the software-facing contract between the Red Pitaya PS and the ADS1278 acquisition logic, and it is the main interface the current `server/` implementation consumes.

## Goal

Define the current register-level behavior that software can rely on when reading samples, enabling acquisition, triggering `SYNC`, and configuring the shared clock divider.

## Scope

- In scope: the AXI GP0 register aperture, register offsets, read and write behavior, reset values, and the RTL blocks that own those registers.
- Out of scope: the network protocol, host-side client behavior, and any later DMA-based transport. This doc describes the current MMIO register block only.

## User-facing behavior

Software running on the Red Pitaya PS sees a single AXI4-Lite register block at physical base address `0x42000000` with a `0x1000` byte aperture. Reads and writes are 32-bit word-oriented.

The current register map is:

| Offset | Name | Access | Current behavior |
|------|------|------|------|
| `0x00` | `CH1` | R | Channel 1 sample, zero-extended from 24 bits into bits `[23:0]` |
| `0x04` | `CH2` | R | Channel 2 sample |
| `0x08` | `CH3` | R | Channel 3 sample |
| `0x0C` | `CH4` | R | Channel 4 sample |
| `0x10` | `CH5` | R | Channel 5 sample |
| `0x14` | `CH6` | R | Channel 6 sample |
| `0x18` | `CH7` | R | Channel 7 sample |
| `0x1C` | `CH8` | R | Channel 8 sample |
| `0x20` | `STATUS` | R | Bit `0` = `new_data`, bit `1` = `overflow`, bits `[31:16]` = `frame_cnt` |
| `0x24` | `CTRL` | R/W | Bit `0` = `sync_trigger`, bit `1` = acquisition enable |
| `0x28` | `EXTCLK_DIV` | R/W | Shared half-period divider used by the current clocking path |

Current read and write semantics:

- Reading `CH1` through `CH8` returns the last latched 24-bit sample for each channel, zero-extended to 32 bits.
- Reading `STATUS` returns the current `new_data` pulse, overflow flag, and 16-bit frame counter.
- Writing `CTRL[1] = 1` enables acquisition and clock generation. Clearing it disables both.
- Writing `CTRL[0] = 1` triggers a one-shot `SYNC` pulse. The bit auto-clears in hardware on the next bus clock.
- `EXTCLK_DIV` resets to `625` (`0x271`), which corresponds to a nominal `100 kHz` output from a `125 MHz` input clock using the current divider formula.

Important current caveats:

- `STATUS[0]` is a one-clock `new_data` pulse generated inside the acquisition RTL, not a sticky data-ready flag. Polling software can miss it.
- `irq` is driven directly from `STATUS[0]`, so the interrupt source is also pulse-like rather than latched.
- Channel registers are zero-extended, not sign-extended. Software must interpret bits `[23:0]` as signed data if signed conversion is required.
- `EXTCLK_DIV` currently feeds both the EXTCLK generator and the SPI TDM acquisition timing path.

## Architecture

The register block is implemented in `ads1278_axi_slave`, which is the AXI4-Lite slave attached to the PS `M_AXI_GP0` path. The block design maps this slave into the PS physical address space at `0x42000000`, leaving the stock housekeeping region at `0x40000000` untouched.

Control and data flow are:

1. The PS issues AXI4-Lite reads and writes through the shared `axi4_lite_if` bus.
2. `ads1278_axi_slave` decodes register accesses and exposes two control registers:
   - `ctrl_reg`
   - `extclk_div_reg`
3. Those control signals feed `ads1278_acq_top`, which owns the acquisition datapath.
4. `ads1278_acq_top` instantiates:
   - `ads1278_spi_tdm` for DRDY-triggered 8 x 24-bit capture
   - `ads1278_extclk_gen` for the ADC external clock
   - `ads1278_sync_pulse` for active-low `SYNC`
5. The acquisition block returns:
   - eight channel words
   - a packed `status` word
6. `ads1278_axi_slave` exposes those values through the read mux and forwards `status[0]` as `irq`.

Reset and lifecycle notes:

- `CTRL` resets to `0`, so acquisition starts disabled.
- `EXTCLK_DIV` resets to `625`.
- `frame_cnt` resets to `0` when acquisition is disabled.
- `overflow` is cleared when acquisition is disabled.
- The channel registers update only when a full 192-bit frame is captured and latched.

## Known risk areas

- The current `new_data` behavior is convenient for RTL but awkward for software polling because it is not sticky.
- `STATUS` does not currently expose a latched "sample available until acknowledged" bit.
- Sharing `EXTCLK_DIV` between the ADC clock generator and the SPI shift timing may not match the final desired hardware contract.
- The base address is defined in the block design, so any future BD remap must be kept in sync with software documentation and code.

## Key files

| Area | File |
|------|------|
| AXI slave register definition | `fpga/rtl/ads1278_axi_slave.sv` |
| Acquisition wrapper | `fpga/rtl/ads1278_acq_top.v` |
| SPI TDM capture | `fpga/rtl/ads1278_spi_tdm.v` |
| EXTCLK generation | `fpga/rtl/ads1278_extclk_gen.v` |
| SYNC pulse generation | `fpga/rtl/ads1278_sync_pulse.v` |
| PS bus wiring | `fpga/rtl/red_pitaya_ps.sv` |
| Top-level integration | `fpga/rtl/red_pitaya_top.sv` |
| Block-design address map | `fpga/source/system_design_bd_rp125_14/system.tcl` |
| MMIO bring-up note | `docs/notes/AXI_GP0_REGISTER_MAP_HOWTO.md` |

## Related docs

- [AXI GP0 register map how-to](../notes/AXI_GP0_REGISTER_MAP_HOWTO.md)
- [Current status and revised implementation plan](../handoffs/20260303_implementation-plan.md)
- [FPGA status and remaining bring-up work](../handoffs/20260304_fpga-work.md)
