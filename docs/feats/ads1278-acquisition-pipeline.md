# ADS1278 Acquisition Pipeline

This doc describes how the current FPGA acquisition path turns ADS1278 TDM data into eight latched channel registers, a packed status word, and a staged DMA FIFO. It covers the present RTL behavior in `rp_ads1278`, not the intended future networked end state.

## Goal

Describe the current acquisition lifecycle from `DRDY` detection through SPI shifting, channel latching, and status reporting so the implemented server and the remaining bring-up work can rely on the actual RTL behavior.

## Scope

- In scope: the FPGA-side acquisition flow, timing choices implemented in RTL, channel latching behavior, FIFO staging behavior, overflow handling, and how control inputs affect the datapath.
- Out of scope: PS-side MMIO access details, TCP streaming, host plotting, and physical wiring beyond what the acquisition path assumes.

## User-facing behavior

When acquisition is enabled, the FPGA waits for a falling edge on `DRDY`, delays for one full EXTCLK period, then clocks exactly 192 SCLK edges to read eight 24-bit channels from `DOUT1` in TDM order. After the full frame is captured, the FPGA updates all eight channel registers together, pulses `new_data`, increments the 16-bit frame counter, and attempts to queue one sign-extended DMA frame record into the staged PL FIFO.

Current behavior that software or bring-up code can observe:

- Acquisition starts only when `CTRL[1]` enable is set.
- `SCLK` idles low and capture uses CPOL=0, CPHA=0 style timing.
- `DOUT1` is sampled on SCLK rising edges.
- One complete frame is 8 channels x 24 bits = 192 bits.
- The latched channel ordering is CH1 through CH8.
- The output channel words are zero-extended to 32 bits before they reach the register map.
- `STATUS[0]` pulses high for one acquisition clock cycle when a frame is latched.
- `STATUS[1]` becomes sticky if a new `DRDY` falling edge arrives while the pipeline is still waiting or shifting.
- Each completed frame is also repacked into the Phase 2 DMA record layout and pushed into a 64-entry PL FIFO.
- The FIFO is cleared when acquisition is disabled.
- If a completed frame arrives while the FIFO is full, the frame is dropped from the staged DMA path and the FIFO drop counter increments.
- Disabling acquisition clears `overflow` and resets `frame_cnt` to zero.

The current `SYNC` path is separate from the SPI capture state machine:

- Writing the sync trigger generates an active-low `SYNC` pulse.
- The pulse width is one EXTCLK period derived from the current divider value.
- `SYNC` generation is not gated by the acquisition enable bit in the current RTL.

## Architecture

The acquisition path is owned by `ads1278_acq_top`, which wraps four RTL blocks:

- `ads1278_spi_tdm`: waits for `DRDY`, drives `SCLK`, shifts in 192 bits, latches channels, and reports `new_data`, `frame_cnt`, and `overflow`.
- `ads1278_frame_fifo`: queues fixed-size DMA frame records behind the capture path during staged DMA bring-up.
- `ads1278_extclk_gen`: generates the ADC external clock from the 125 MHz system clock.
- `ads1278_sync_pulse`: generates a one-shot active-low `SYNC` pulse.

`ads1278_acq_top` exposes:

- `sclk_o`
- `extclk_o`
- `sync_n_o`
- `ch_data_0` through `ch_data_7`
- packed `status`

The wrapper also defines the current software-visible packing:

- each 24-bit channel sample is zero-extended to 32 bits
- `status = {frame_cnt, 14'd0, overflow, new_data}`
- queued FIFO records use the Phase 2 layout: `frame_count`, `status_raw`, and eight sign-extended 32-bit channels

The same `extclk_div` control word currently feeds all three behaviors:

- the EXTCLK generator
- the SPI shift timing divisor
- the SYNC pulse width generator

## Lifecycle

The SPI capture engine in `ads1278_spi_tdm` runs through four states:

1. `S_IDLE`

- `SCLK` is held low.
- The engine waits for `enable` and a detected falling edge on `DRDY`.

2. `S_WAIT`

- After `DRDY` falls, the engine waits `2 * div_eff` system-clock cycles.
- This implements a one-EXTCLK-period delay before the first SCLK activity.

3. `S_SHIFT`

- The engine toggles `SCLK` using the current divider value.
- On each rising edge, it schedules a sample and shifts one synchronized `MISO` bit into the 192-bit shift register.
- On each falling edge, it advances the bit counter.
- After 192 bits, it transitions to latch.

4. `S_LATCH`

- `SCLK` returns low.
- The 192-bit shift register is unpacked into eight 24-bit channel words.
- `new_data` pulses high.
- `frame_cnt` increments.
- The engine returns to idle.

Overflow behavior:

- If `DRDY` falls again while the engine is in `S_WAIT` or `S_SHIFT`, `overflow` is set.
- `overflow` stays asserted until acquisition is disabled.
- If the staged DMA FIFO is full when `new_data` is emitted, the current MMIO latest-sample path still updates, but the queued DMA record is dropped and the FIFO drop counter increments.

Reset and disable behavior:

- Reset clears the state machine, outputs, channel registers, `frame_cnt`, and `overflow`.
- Disabling acquisition leaves the state machine clocked but clears `overflow` and resets `frame_cnt`.

## Known risk areas

- `new_data` is a pulse, not a sticky "data available" flag, so software polling can miss completed frames.
- The divider value used for EXTCLK is also reused for SPI capture timing, which may not remain the final contract.
- Channel words are zero-extended rather than sign-extended, so software must reinterpret the 24-bit payload correctly.
- `overflow` only records that overlap happened at least once; it does not count how many frames were missed by the SPI engine.
- The staged FIFO has no consumer yet in Phase 3, so it will eventually fill during sustained acquisition and start incrementing the FIFO drop counter.
- `SYNC` is generated independently of the enable bit, which may or may not match the intended operational model.

## Key files

| Area | File |
|------|------|
| Acquisition wrapper | `fpga/rtl/ads1278_acq_top.v` |
| Staged DMA FIFO | `fpga/rtl/ads1278_frame_fifo.v` |
| SPI capture state machine | `fpga/rtl/ads1278_spi_tdm.v` |
| EXTCLK generation | `fpga/rtl/ads1278_extclk_gen.v` |
| SYNC pulse generation | `fpga/rtl/ads1278_sync_pulse.v` |
| Register block integration | `fpga/rtl/ads1278_axi_slave.sv` |
| SPI timing reference note | `ADS1278_SPI.md` |

## Related docs

- [FPGA Register Map](fpga-register-map.md)
- [AXI GP0 register map how-to](../notes/AXI_GP0_REGISTER_MAP_HOWTO.md)
- [Current status and revised implementation plan](../handoffs/20260303_implementation-plan.md)
- [FPGA status and remaining bring-up work](../handoffs/20260304_fpga-work.md)
