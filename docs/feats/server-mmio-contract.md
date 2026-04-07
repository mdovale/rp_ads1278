# Server MMIO Contract

This doc describes the current memory-mapped interface the `server/` process uses when talking to the FPGA acquisition block on the Red Pitaya PS. It is the software-facing contract between the implemented C server and the current FPGA register block.

## Goal

Define the current PS-to-FPGA MMIO interface clearly enough that the existing `server/` implementation, bring-up tools, and current client-facing docs can rely on the same register-level behavior without rediscovering RTL details from scratch.

## Scope

- In scope: physical base address, register offsets, access width, control semantics, status semantics, channel data representation, and current integration caveats that affect server design.
- Out of scope: TCP framing, host-side protocol, GUI behavior, Linux service management, and any future non-MMIO transport such as DMA.

## User-facing behavior

The current FPGA design exposes one AXI4-Lite register block to the PS at physical base address `0x40000000` with a `0x1000` byte aperture. The current `server/` implementation accesses this block through uncached MMIO via `/dev/mem`.

Current server-visible register map:

| Offset | Name | Access | Server-visible meaning |
|------|------|------|------|
| `0x00` | `CH1` | R | Channel 1 sample in bits `[23:0]`, zero-extended to 32 bits |
| `0x04` | `CH2` | R | Channel 2 sample |
| `0x08` | `CH3` | R | Channel 3 sample |
| `0x0C` | `CH4` | R | Channel 4 sample |
| `0x10` | `CH5` | R | Channel 5 sample |
| `0x14` | `CH6` | R | Channel 6 sample |
| `0x18` | `CH7` | R | Channel 7 sample |
| `0x1C` | `CH8` | R | Channel 8 sample |
| `0x20` | `STATUS` | R | Bit `0` = `new_data`, bit `1` = `overflow`, bits `[31:16]` = `frame_cnt` |
| `0x24` | `CTRL` | R/W | Bit `0` = one-shot `SYNC` trigger, bit `1` = acquisition enable |
| `0x28` | `EXTCLK_DIV` | R/W | Shared divider value used by current FPGA clocking logic |

Current behavior a server can rely on:

- The register block is word-oriented and uses 32-bit reads and writes.
- `CTRL` resets to `0`, so acquisition starts disabled after reset.
- `EXTCLK_DIV` resets to `625` (`0x271`).
- Channel registers update together after a complete 192-bit TDM frame is captured.
- `frame_cnt` increments once per latched frame and resets to `0` when acquisition is disabled.
- `overflow` is cleared when acquisition is disabled.
- Writing `CTRL[1] = 1` enables both acquisition and the current EXTCLK generator.
- Writing `CTRL[0] = 1` triggers a one-shot `SYNC` pulse and the bit auto-clears in hardware.

Current behavior a server must account for carefully:

- Channel values are zero-extended, not sign-extended. The server must reinterpret bits `[23:0]` itself if signed output is required.
- `STATUS[0]` is a pulse-style `new_data` indication, not a sticky ready bit.
- `irq` mirrors `STATUS[0]`, so the current interrupt source is also pulse-like rather than latched.
- `EXTCLK_DIV` is currently shared between:
  - ADC external clock generation
  - SPI shift timing
  - `SYNC` pulse width

For a polling-based server, the current safe interpretation is:

- treat the channel words plus `frame_cnt` as the primary observable state
- treat `new_data` as advisory rather than reliable for low-rate polling
- treat `overflow` as "at least one overlap occurred since last disable"

## Architecture

The MMIO contract is implemented by `ads1278_axi_slave`, which is connected to the PS `M_AXI_GP0` AXI4-Lite path. The block design places that slave at `0x40000000` in PS physical address space.

Ownership and data flow are:

1. The PS accesses the FPGA over AXI4-Lite through the shared `axi4_lite_if` bus.
2. `ads1278_axi_slave` decodes reads and writes for `CTRL`, `EXTCLK_DIV`, channel data, and `STATUS`.
3. `ads1278_axi_slave` forwards control values into `ads1278_acq_top`.
4. `ads1278_acq_top` returns:
   - eight 32-bit channel words
   - one packed `status` word
5. `ads1278_axi_slave` exposes those values directly to software and forwards `status[0]` to `irq`.

The packed status word is currently:

- `status = {frame_cnt, 14'd0, overflow, new_data}`

The channel words are currently:

- `{8'd0, sample_24b}`

That means the server contract is intentionally simple today:

- one fixed MMIO base
- one small register block
- no DMA
- no shared DDR ring buffer

## Known risk areas

- A polling server can miss `new_data` because it is pulse-based.
- The current MMIO contract does not include an acknowledgement mechanism for consumed samples.
- The current hardware contract does not expose a missed-frame counter, only a sticky overlap flag.
- Any future remap of the AXI base address in the block design must be reflected in server code and docs together.
- The current server is intentionally a latest-sample MMIO polling server, so protocol and scaling choices above this layer may still evolve in later revisions.

## Manual QA

Useful checks for the current server bring-up path:

- Map `0x40000000` for `0x1000` bytes and confirm reads do not bus-fault on a correctly loaded design.
- Read `CTRL`, `EXTCLK_DIV`, and `STATUS` before enabling acquisition to confirm reset-state expectations.
- Write `CTRL[1] = 1` and confirm `EXTCLK` and acquisition-related behavior begin.
- Read `frame_cnt` repeatedly and confirm it advances during successful acquisition.
- Trigger `SYNC` through `CTRL[0]` and observe the expected acquisition disturbance or recovery behavior.
- Disable acquisition and confirm `frame_cnt` resets and `overflow` clears.

## Key files

| Area | File |
|------|------|
| AXI slave register behavior | `fpga/rtl/ads1278_axi_slave.sv` |
| Acquisition wrapper and status packing | `fpga/rtl/ads1278_acq_top.v` |
| AXI GP0 bring-up reference | `docs/notes/AXI_GP0_REGISTER_MAP_HOWTO.md` |
| Hardware register doc | `docs/feats/fpga-register-map.md` |
| Acquisition behavior doc | `docs/feats/ads1278-acquisition-pipeline.md` |
| Current MMIO consumer | `server/memory_map.c` |
| End-state architecture | `README.md` |

## Related docs

- [FPGA Register Map](fpga-register-map.md)
- [ADS1278 Acquisition Pipeline](ads1278-acquisition-pipeline.md)
- [Server](server.md)
- [Server Protocol](server-protocol.md)
- [Board IO Wiring](board-io-wiring.md)
- [FPGA Build And Deploy](fpga-build-and-deploy.md)
- [FPGA status and remaining bring-up work](../handoffs/20260304_fpga-work.md)
