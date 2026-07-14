# FPGA Register Map

This doc covers the current MMIO register block exposed by the FPGA acquisition path in `rp_ads1278`. It is the software-facing contract between the Red Pitaya PS and the ADS1278 acquisition logic, and it is the main interface the current `server/` implementation consumes.

## Goal

Define the current register-level behavior that software can rely on when reading samples, enabling acquisition, triggering `SYNC`, configuring the shared clock divider, configuring the modulation output divider, and tuning demod post-edge sample skipping.

## Scope

- In scope: the AXI GP0 register aperture, register offsets, read and write behavior, reset values, and the RTL blocks that own those registers.
- Out of scope: the network protocol, host-side client behavior, and any later DMA-based transport. This doc describes the current MMIO register block only.

## User-facing behavior

Software running on the Red Pitaya PS sees a single AXI4-Lite register block at physical base address `0x42000000` with a `0x1000` byte aperture. Reads and writes are 32-bit word-oriented.

The current register map is:

| Offset | Name | Access | Current behavior |
|------|------|------|------|
| `0x00` | `CH1` | R | Channel 1 sample, or CH1 demod output when `CTRL[2]` is set |
| `0x04` | `CH2` | R | Channel 2 sample |
| `0x08` | `CH3` | R | Channel 3 sample |
| `0x0C` | `CH4` | R | Channel 4 sample |
| `0x10` | `CH5` | R | Channel 5 sample |
| `0x14` | `CH6` | R | Channel 6 sample |
| `0x18` | `CH7` | R | Channel 7 sample |
| `0x1C` | `CH8` | R | Channel 8 sample, zero-extended from 24 bits into bits `[23:0]` |
| `0x20` | `STATUS` | R | Bit `0` = `new_data`, bit `1` = `overflow`, bits `[31:16]` = `frame_cnt` |
| `0x24` | `CTRL` | R/W | Bit `0` = `sync_trigger`, bit `1` = acquisition enable, bit `2` = demod enable |
| `0x28` | `EXTCLK_DIV` | R/W | Shared half-period divider used by the current clocking path |
| `0x2C` | `FIFO_STATUS` | R | Bits `[15:0]` = FIFO level in frames, bit `16` = empty, bit `17` = full |
| `0x30` | `FIFO_DROPS` | R | Count of queued DMA frames dropped because the staged FIFO was full |
| `0x34` | `FIFO_CAPACITY` | R | Configured staged FIFO depth in frames (`64`) |
| `0x38` | `DMA_CTRL` | R/W | Bit `0` = DMA enable, bits `[2:1]` = DMA mode (`0` = pattern, `1` = capture), bit `8` = IRQ enable |
| `0x3C` | `DMA_BASE_ADDR` | R/W | Physical DDR base for the DMA test buffer |
| `0x40` | `DMA_BUF_SIZE` | R/W | DMA buffer size in bytes, aligned to 128-byte bursts |
| `0x44` | `DMA_STATUS` | R | DMA enabled/running/error status and current write index |
| `0x48` | `DMA_WRITE_INDEX` | R | Current DMA writer burst index |
| `0x4C` | `DMA_WRAP_COUNT` | R | Number of completed buffer wraps |
| `0x50` | `DMA_ERROR_COUNT` | R | Number of non-OKAY AXI write responses |
| `0x54` | `DMA_IRQ_STATUS` | R | Sticky DMA interrupt/status bits |
| `0x58` | `DMA_IRQ_ACK` | W1C | Clear `DMA_IRQ_STATUS` bits |
| `0x5C` | `MOD_DIV` | R/W | `0` holds MOD high; `>= 2` is the modulation square-wave half-period divider, `125 MHz / (2 * MOD_DIV)` |
| `0x60` | `DMA_BUF_STATUS` | R | Ping-pong ownership: bit `0` = buffer 0 full, bit `1` = buffer 1 full, bit `2` = active hardware buffer, bit `3` = overwrite pending |
| `0x64` | `DMA_BUF_ACK` | W1C | Software-consumed buffer acknowledgement: bit `0` clears buffer 0 full, bit `1` clears buffer 1 full |
| `0x68` | `DMA_OVERWRITE_COUNT` | R | Count of times DMA advanced into a buffer still marked full |
| `0x6C` | `DEMOD_SKIP` | R/W | Bits `[15:0]` = number of ADC samples to skip after each MOD edge before CH1 contributes to the demod half-cycle average |

Current read and write semantics:

- Reading `CH1` through `CH8` returns the last latched 24-bit sample for each channel, zero-extended to 32 bits.
- Reading `STATUS` returns the current `new_data` pulse, overflow flag, and 16-bit frame counter.
- Writing `CTRL[1] = 1` enables acquisition and clock generation. Clearing it disables both.
- Writing `CTRL[2] = 1` replaces CH1 with the held half-cycle demod output computed from raw CH1. Clearing it restores raw CH1. CH8 remains raw in both states.
- Writing `CTRL[0] = 1` triggers a one-shot `SYNC` pulse. The bit auto-clears in hardware on the next bus clock.
- `EXTCLK_DIV` resets to `625` (`0x271`), which corresponds to a nominal `100 kHz` output from a `125 MHz` input clock using the current divider formula.
- `FIFO_STATUS` reports staged DMA FIFO occupancy for bring-up and debug without changing the legacy MMIO latest-sample path.
- `FIFO_DROPS` resets to `0` when acquisition is disabled.
- `FIFO_CAPACITY` is a read-only constant for software-visible bring-up checks.
- `DMA_BUF_STATUS` exposes the first-pass ping-pong ownership state. A buffer full bit means hardware has completed that DDR buffer and software owns it until it writes the matching bit to `DMA_BUF_ACK`.
- `DMA_BUF_SIZE` is interpreted as one ping-pong buffer size; buffer 0 starts at `DMA_BASE_ADDR`, and buffer 1 starts at `DMA_BASE_ADDR + DMA_BUF_SIZE`.
- If DMA wraps into a buffer whose full bit is still set, hardware increments `DMA_OVERWRITE_COUNT` and sets the overwrite-pending bit instead of silently hiding the ownership violation.
- `MOD_DIV` resets to `6,250,000`, which corresponds to a nominal `10 Hz` modulation square wave from a `125 MHz` input clock. Writing `0` disables toggling and holds the MOD output high.
- `DEMOD_SKIP` resets to `0`, preserving the original demod behavior. When non-zero, the first `DEMOD_SKIP[15:0]` ADC samples after every MOD edge are excluded from `sum_pos` / `sum_neg`; if a half-cycle has no accumulated samples, the demod path keeps the previous average through the existing empty-count guard.

Important current caveats:

- `STATUS[0]` is a one-clock `new_data` pulse generated inside the acquisition RTL, not a sticky data-ready flag. Polling software can miss it.
- `irq` is driven directly from `STATUS[0]`, so the interrupt source is also pulse-like rather than latched.
- Channel registers are zero-extended, not sign-extended. Software must interpret bits `[23:0]` as signed data if signed conversion is required.
- `EXTCLK_DIV` currently feeds both the EXTCLK generator and the SPI TDM acquisition timing path.

## Architecture

The register block is implemented in `ads1278_axi_slave`, which is the AXI4-Lite slave attached to the PS `M_AXI_GP0` path. The block design maps this slave into the PS physical address space at `0x42000000`, leaving the stock housekeeping region at `0x40000000` untouched.

Control and data flow are:

1. The PS issues AXI4-Lite reads and writes through the shared `axi4_lite_if` bus.
2. `ads1278_axi_slave` decodes register accesses and exposes control registers:
   - `ctrl_reg`
   - `extclk_div_reg`
   - `mod_div_reg`
   - `demod_skip_reg`
   - DMA phase-4 control registers
3. Those control signals feed `ads1278_acq_top`, which owns the acquisition datapath.
4. `ads1278_acq_top` instantiates:
   - `ads1278_frame_fifo` for staged DMA buffering
   - `ads1278_demod` for CH1 half-cycle demod output on CH1 when enabled
   - `ads1278_spi_tdm` for DRDY-triggered 8 x 24-bit capture
   - `ads1278_extclk_gen` for the ADC external clock
   - `ads1278_sync_pulse` for active-low `SYNC`
5. The acquisition block returns:
   - eight channel words
   - a packed `status` word
   - staged FIFO debug words
6. `ads1278_axi_slave` exposes those values through the read mux and forwards `status[0]` as `irq`.
7. `ads1278_axi_slave` also generates the modulation output directly from `mod_div_reg` and exposes it to `red_pitaya_top.sv` for `exp_p_io[5]`; `0` holds the output high and `>= 2` generates a square wave.

Reset and lifecycle notes:

- `CTRL` resets to `0`, so acquisition starts disabled.
- `EXTCLK_DIV` resets to `625`.
- `MOD_DIV` resets to `6,250,000`, so the modulation output starts at `10 Hz`. Writing `0` holds the output high.
- `DEMOD_SKIP` resets to `0`, so CH1 demod includes every raw CH1 sample until software writes a calibrated skip count.
- `frame_cnt` resets to `0` when acquisition is disabled.
- `overflow` is cleared when acquisition is disabled.
- The channel registers update only when a full 192-bit frame is captured and latched.

## Known risk areas

- The current `new_data` behavior is convenient for RTL but awkward for software polling because it is not sticky.
- `STATUS` does not currently expose a latched "sample available until acknowledged" bit.
- The staged FIFO has no consumer yet, so long captures can intentionally drive it full during Phase 3 bring-up.
- DMA mode `1` (capture) drains the acquisition FIFO into DDR as `ads1278_dma_frame` records on a **128-byte stride** (40-byte payload + padding + word-31 canary `0xAD127831`). Acquisition (`CTRL` bit 1) and DMA (`DMA_CTRL` bit 0) must both be enabled for live ADC capture. See `docs/feats/dma-frame-record.md`.
- Sharing `EXTCLK_DIV` between the ADC clock generator and the SPI shift timing may not match the final desired hardware contract.
- The base address is defined in the block design, so any future BD remap must be kept in sync with software documentation and code.

## Key files

| Area | File |
|------|------|
| AXI slave register definition | `fpga/rtl/ads1278_axi_slave.sv` |
| Acquisition wrapper | `fpga/rtl/ads1278_acq_top.v` |
| Staged DMA FIFO | `fpga/rtl/ads1278_frame_fifo.v` |
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
