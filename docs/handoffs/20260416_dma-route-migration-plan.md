# rp_ads1278 - DMA route migration plan

This handoff captures a concrete step-by-step plan for moving `rp_ads1278` from the current MMIO latest-sample server architecture to a DMA-backed capture path that can preserve frames at higher acquisition rates.

## Summary

- The current design is not DMA-based. The PS reads the latest FPGA register bank over `M_AXI_GP0` AXI4-Lite via `/dev/mem`.
- The current server is intentionally a latest-sample poller, so it can skip intermediate frames whenever acquisition outruns the server poll loop.
- The current architecture is useful for bring-up, control, and low-rate visualization, but it is not suitable as the long-term lossless capture path.
- A DMA migration should preserve the current MMIO control plane while adding a separate high-throughput data plane from PL into DDR through a PS high-performance memory interface.
- The safest migration path is staged: keep MMIO for control/debug, add PL buffering, add DDR writes, then update the server and protocol around completed DMA buffers.

## Why this handoff exists

The current session established three key points:

- the sample-rate mismatch seen in CSV logs is not primarily a Python logging bug,
- the server only sees the latest coherent MMIO snapshot and therefore can miss hardware frames,
- the right long-term fix for high-rate capture is a DMA-style path rather than tighter user-space polling alone.

The next session should not reopen the basic architectural distinction between the current MMIO path and a DMA path. The remaining work is to turn that distinction into an implementation plan that fits this repository.

## Current state to preserve

Keep the current control/status path working while DMA is introduced. Do not replace it all at once.

- MMIO base: `0x42000000`
- AXI aperture: `0x1000`
- PS-to-PL control path: `M_AXI_GP0` AXI4-Lite
- Current control registers:
  - `CH1` to `CH8`
  - `STATUS`
  - `CTRL`
  - `EXTCLK_DIV`
- Current acquisition behavior:
  - `ads1278_spi_tdm` waits for `DRDY`, shifts 192 bits, latches 8 channels, increments `frame_cnt`
- Current software behavior:
  - server reads the latest coherent snapshot through `/dev/mem`
  - server emits a new `SAMPLE` only when `frame_cnt` changes
- Current limitations:
  - no DMA
  - no shared DDR ring buffer
  - latest-sample semantics only

Important constraints from the current design:

- `new_data` is pulse-style, not sticky.
- `irq` currently mirrors the pulse-style status bit and is not a complete capture-ready contract.
- `EXTCLK_DIV` is currently shared by EXTCLK generation, SPI shift timing, and SYNC pulse width.
- The current Python client and server protocol assume one fixed-size snapshot at a time.

## Current path explained

Today the data path is:

1. The ADS1278 produces one 8-channel conversion frame.
2. `ads1278_spi_tdm` captures that frame in PL logic and latches the latest 8 channel words plus `status`.
3. `ads1278_axi_slave` exposes those latched values as a small AXI4-Lite register block.
4. The ARM processor, acting as AXI master on `M_AXI_GP0`, reads those registers through `/dev/mem`.
5. The C server packages the most recent coherent snapshot into one TCP message.
6. The Python client plots or logs those messages.

Important consequence:

- the FPGA only exposes the latest latched frame in registers,
- intermediate frames are overwritten in PL before software can see them if acquisition outruns polling,
- the current path is therefore a control-and-observability path, not a lossless capture path.

## Target DMA path explained

The target DMA path should look like this:

1. The ADS1278 produces one 8-channel conversion frame.
2. PL capture logic latches the frame and writes it into a PL-side FIFO or stream buffer.
3. A PL-side DMA writer or AXI master transfers buffered frames into DDR through a PS high-performance memory interface.
4. The server consumes completed buffers from DDR instead of reading single MMIO snapshots.
5. The host-facing protocol can then stream or log batches of contiguous frames.

Important architectural split:

- keep `M_AXI_GP0` for control, configuration, counters, and debug registers,
- add a separate data plane for capture writes into DDR,
- do not try to stretch the AXI4-Lite register bank into a high-throughput sample transport.

## Recommended migration plan

### Phase 1. Freeze the current MMIO contract

Goal:

- keep the existing server/client path operational during DMA bring-up.

Actions:

- preserve the current `CTRL`, `EXTCLK_DIV`, and top-level status semantics,
- preserve the existing latest-sample register view for debug,
- avoid breaking the current client while DMA work is still incomplete.

Success criteria:

- current MMIO polling server still builds and runs unchanged,
- existing bring-up tools can still observe `frame_cnt`, `overflow`, and channel values.

### Phase 2. Define one DMA frame format

Goal:

- decide exactly what one captured frame looks like in memory before changing RTL.

Recommended first format:

- one `frame_cnt`
- one flags or `status_raw` word
- eight channels

Recommended first encoding:

- channels stored as signed 32-bit values in memory for simplicity,
- fixed-size records to simplify PL writers and server parsing,
- optional timestamp deferred until later unless there is a strong immediate need.

Questions to settle:

- whether to store raw 24-bit payloads or sign-extended 32-bit values,
- whether to include full `status_raw` per frame or only reduced flags,
- whether to include `extclk_div` in every frame or only in control metadata.

Success criteria:

- one fixed record layout documented in bytes and words,
- no ambiguity about what software should parse from DDR.

### Phase 3. Add a PL-side FIFO behind acquisition

Goal:

- decouple ADC capture timing from DDR write timing.

Actions:

- insert a FIFO or streaming buffer after `ads1278_spi_tdm`,
- write one complete frame into the FIFO whenever a new capture is latched,
- add independent FIFO overflow or dropped-frame counters.

Why this matters:

- DMA and DDR write latency should not back-pressure the SPI state machine directly,
- FIFO depth gives margin between acquisition bursts and memory-service jitter.

Success criteria:

- captured frames enter FIFO reliably,
- FIFO occupancy and overflow are observable through debug registers or counters.

### Phase 4. Add a PL master path to DDR

Goal:

- give PL logic the ability to write captured frames into DDR.

Actions:

- enable an appropriate PS memory-facing interface in the block design,
- connect a DMA-capable writer or custom AXI master from PL to that memory path,
- keep `M_AXI_GP0` in place for AXI4-Lite control/status.

Important note:

- the current GP0 path is PS-master-to-PL-slave and is not the right transport for sustained frame capture into memory.
- the DMA path needs PL-originated writes into DDR.

Success criteria:

- PL can write test-pattern data into a known DDR buffer,
- software can confirm that DDR contents match what hardware wrote.

### Phase 5. Add DMA control and status registers

Goal:

- let software configure and monitor DMA behavior through the existing MMIO control plane.

Recommended new register classes:

- DMA enable
- DMA mode select
- buffer base address
- buffer size
- write index or producer pointer
- completion flags
- FIFO overflow and DMA error counters
- interrupt status and acknowledge bits

Design guidance:

- keep these registers in `ads1278_axi_slave.sv`,
- do not overload the existing sample registers with DMA ownership semantics,
- use explicit counters and flags because DMA bugs are hard to diagnose without visibility.

Success criteria:

- software can arm buffers and read back DMA state,
- hardware can expose whether samples were captured, written, or dropped.

### Phase 6. Start with ping-pong buffers, not a full ring

Goal:

- reduce first-pass complexity while getting end-to-end DMA capture working.

Recommended first design:

- two fixed DDR buffers,
- hardware fills one while software consumes the other,
- completion interrupt or status bit flips ownership.

Why this is recommended:

- easier ownership model than a general ring buffer,
- simpler RTL state machine,
- simpler server logic during bring-up.

Deferred work:

- full circular ring buffer,
- scatter-gather descriptor chains,
- multi-buffer queueing beyond two buffers.

Success criteria:

- software can clearly tell which buffer is full,
- hardware never overwrites a buffer still owned by software without an explicit overflow indication.

### Phase 7. Validate DDR writes with synthetic data first

Goal:

- isolate DMA correctness from ADS1278 timing issues.

Actions:

- before using live ADC frames, configure the DMA path to write a simple incrementing or patterned frame stream,
- verify software can read back the exact expected sequence from DDR,
- only then switch the DMA source from synthetic data to real capture frames.

Success criteria:

- DDR contents match the synthetic generator exactly,
- buffer boundaries and ownership changes behave correctly.

### Phase 8. Feed real ADS1278 frames into DMA

Goal:

- connect the validated DMA path to the actual acquisition output.

Actions:

- switch the FIFO source from synthetic data to the latched acquisition frame,
- carry `frame_cnt` into the DMA record so software can detect gaps,
- verify that DDR buffers contain sequential frame counts while the ADC is running.

Success criteria:

- frame counts in DDR increase monotonically,
- software can detect whether any frames were dropped between capture and memory,
- the data no longer shows the polling-driven `+2` pattern caused by the current server loop.

### Phase 9. Update the server to consume DMA buffers

Goal:

- move software from "read latest snapshot" to "drain completed sample buffers".

Actions:

- keep current MMIO support for control and debug,
- add code to arm DMA buffers and wait for completion,
- read completed buffers from DDR instead of repeatedly reading `CH1` to `CH8`,
- preserve current command handling for enable, sync, and divider control.

Recommended software behavior:

- in DMA mode, the server should treat each completed buffer as a batch of frames,
- in legacy mode, the server can continue using the MMIO latest-sample path.

Success criteria:

- one server binary can operate in either legacy MMIO mode or DMA mode,
- software no longer depends on the poll interval to preserve every frame.

### Phase 10. Add a bulk transport mode

Goal:

- stop forcing a batch-oriented capture path through a single-snapshot protocol.

Options:

- add a new protocol version with bulk sample messages,
- add a new message type that carries multiple frames,
- log to file on the board first and keep the GUI path decimated separately.

Recommended first choice:

- keep the current protocol for low-rate live view,
- add a separate bulk-stream or capture mode for DMA-backed data.

Reason:

- the GUI does not need to draw every sample at high rates,
- capture/logging does need to preserve frames.

Success criteria:

- DMA capture can be consumed without redefining every UI assumption at once,
- live plotting and full-rate recording can evolve independently.

### Phase 11. Add observability before optimization

Goal:

- make failures attributable to a specific stage.

Recommended counters and status:

- ADC frames captured
- FIFO frames written
- FIFO overflow count
- DMA frames written
- DMA buffer completions
- software-consumed buffers
- dropped-buffer or overwrite events

Success criteria:

- when frames are missing, the next session can tell whether they were lost in capture, FIFO, DMA, or software consumption.

### Phase 12. Promote the DMA path only after end-to-end validation

Goal:

- avoid deleting the current debug path too early.

Actions:

- keep MMIO latest-sample mode available during early DMA bring-up,
- use MMIO mode as a debug fallback when DMA is not yet stable,
- only retire or de-emphasize the old path once DMA capture is proven on real hardware.

Success criteria:

- there is always at least one known-good observability path during development,
- the repo does not get stuck with a half-working DMA-only transition.

## Proposed repo impact

### FPGA / block design

Likely touch points:

- `fpga/rtl/ads1278_spi_tdm.v`
- `fpga/rtl/ads1278_acq_top.v`
- `fpga/rtl/ads1278_axi_slave.sv`
- `fpga/rtl/red_pitaya_top.sv`
- `fpga/rtl/red_pitaya_ps.sv`
- `fpga/source/system_design_bd_rp125_14/system.tcl`

Likely new modules:

- FIFO or stream wrapper for captured frames
- DMA writer or AXI master wrapper
- optional interrupt/status helper

### Server

Likely touch points:

- `server/server.c`
- `server/server.h`
- `server/memory_map.c`
- `server/memory_map.h`
- protocol files if a new bulk message format is introduced

Likely new responsibilities:

- buffer programming
- DMA completion handling
- DDR buffer parsing
- mode selection between MMIO and DMA capture

### Client

Likely touch points:

- protocol decoder
- capture/logging path
- live plotting path if bulk messages are introduced

Recommended behavioral split:

- live plot path may decimate or resample for display,
- capture path should preserve all frames made available by DMA.

## Risks and design traps

- Tightening the current user-space poll loop is not a full substitute for DMA; it only delays the point at which frames are missed.
- Reusing the current AXI4-Lite register block as the main data path will not scale.
- DMA without explicit counters and ownership rules will be difficult to debug.
- A full ring buffer is attractive, but starting there may slow bring-up compared with a ping-pong design.
- Changing the wire protocol too early may entangle server, FPGA, and GUI debugging at the same time.
- If the PL writer can overrun software-owned buffers, the design must expose that explicitly instead of silently overwriting data.

## Success criteria for the migration

The DMA route should be considered successful when all of the following are true:

- PL writes contiguous captured frames into DDR, not just the latest frame into MMIO registers.
- software can consume completed buffers without relying on high-frequency `/dev/mem` polling.
- frame counts in captured buffers are sequential except where an explicit overflow or dropped-frame indicator reports otherwise.
- the system preserves frames at rates where the current MMIO polling server loses them.
- the current control plane for enable, sync, and divider configuration remains understandable and testable.

## Suggested order for the next session

1. Document and lock the DMA frame record format.
2. Choose ping-pong buffers as the first implementation target.
3. Add FIFO plus counters in PL.
4. Add PL-to-DDR write path and validate with synthetic data.
5. Add MMIO control/status registers for DMA.
6. Feed real ADS1278 frames into the DMA path.
7. Update the server to consume DMA buffers.
8. Add or stage a bulk transport mode for high-rate capture.
9. Keep MMIO latest-sample mode as a debug fallback until DMA is proven.

## References

- `README.md`
- `docs/feats/fpga.md`
- `docs/feats/fpga-register-map.md`
- `docs/feats/ads1278-acquisition-pipeline.md`
- `docs/feats/server.md`
- `docs/feats/server-mmio-contract.md`
- `docs/notes/AXI_GP0_REGISTER_MAP_HOWTO.md`
- `fpga/rtl/ads1278_spi_tdm.v`
- `fpga/rtl/ads1278_acq_top.v`
- `fpga/rtl/ads1278_axi_slave.sv`
- `fpga/source/system_design_bd_rp125_14/system.tcl`
- `server/server.c`
- `server/memory_map.c`
