# rp_ads1278 — Phase 5 handoff (DMA MMIO control and status)

This handoff documents **Phase 5** of the DMA migration plan: **explicit DMA control and status registers** on the existing **`M_AXI_GP0` AXI4-Lite** block (`ads1278_axi_slave`), decoupled from **`CTRL[1]` (acquisition enable)**. It follows `docs/handoffs/20260416_dma-route-migration-plan.md` § “Phase 5. Add DMA control and status registers” and supersedes the Phase 4 shortcut described in `docs/handoffs/20260421_phase4-pl-ddr-hp0-bringup.md`.

## Summary

- **`dma_phase4_enable` is no longer tied to `ctrl_enable`.** Acquisition (`CTRL` bit 1) and the HP0 test writer are **independent**: enable DMA only via **`DMA_CTRL`**.
- **New MMIO registers** (`0x38`–`0x58`) provide **enable**, **mode**, **DDR base**, **buffer size**, **live status**, **burst write index**, **wrap count**, **AXI write-response error count**, **sticky IRQ/status bits**, and **W1C acknowledge** at `DMA_IRQ_ACK`. The authoritative bit-level map is in the header comment of `fpga/rtl/ads1278_axi_slave.sv` and mirrored in `server/memory_map.h`.
- **`ads1278_axi_slave`** address width was widened to **`AW = 7`** so word addresses up to **`0x16`** decode correctly (`red_pitaya_top.sv` instantiates with `.AW(7)`).
- **`ads1278_dma_phase4`** now takes **`mode_select`**, **`base_addr`**, **`buffer_size_bytes`**, and exports **`write_index`**, **`wrap_pulse`**, **`running`**, **`config_error`**, **`bresp_error_pulse`**, **`last_bresp`** for status aggregation in the slave.
- **Buffer geometry:** `DMA_BUF_SIZE` must be **non-zero**, **multiple of 128 bytes** (16 beats × 8 bytes per 64-bit AXI beat), and the implied burst count **`size / 128`** must be in **`1 … 65536`**. Otherwise **`config_error`** is asserted and the writer does not run (`writer_enable = enable & ~config_error`). **`base_addr == 0`** is treated as “use RTL default” **`0x1E000000`** (same as the old Phase 4 parameter default).
- **Software:** `server/memory_map.h` defines register offsets and bit masks; **`server/rpdevmem.c`** adds **`dma-status`** and makes **`ddr-read` / `ddr-dump`** mmap the region described by **`DMA_BASE_ADDR`** + **`DMA_BUF_SIZE`** (not hard-coded constants alone).

## Why this handoff exists

Phase 5’s goal is **software-visible control and observability** for the PL→DDR path without overloading channel/sample registers. The implementation is in-repo; the next owner should **rebuild the bitstream**, **reload FPGA**, deploy updated **`rpdevmem` / server** if used on-target, and validate **register semantics**, **IRQ** behavior if enabled, and **DDR ownership** for programmed bases.

## Phase 5 checklist (from migration plan)

From `docs/handoffs/20260416_dma-route-migration-plan.md` § “Phase 5. Add DMA control and status registers”:

| Plan item | Status |
|-----------|--------|
| DMA enable (separate from acquisition) | **Done** — `DMA_CTRL[0]` drives `dma_phase4_enable` |
| DMA mode select | **Done** — `DMA_CTRL[2:1]`; only mode **`0`** (pattern) is supported in `ads1278_dma_phase4` today |
| Buffer base address | **Done** — `DMA_BASE_ADDR` |
| Buffer size | **Done** — `DMA_BUF_SIZE` (bytes); see geometry rules above |
| Write index / producer pointer | **Done** — `DMA_WRITE_INDEX` and duplicate in `DMA_STATUS[31:16]` |
| Completion / error visibility | **Partial** — wrap + AXI `BRESP` error sticky bits and counters; no separate “buffer done” handshake yet (Phase 6 ping-pong) |
| FIFO overflow + DMA error counters | **Partial** — existing **`FIFO_*`** regs unchanged; DMA has **`DMA_ERROR_COUNT`** for **`BRESP != OKAY`** |
| Interrupt status + acknowledge | **Done** — `DMA_IRQ_STATUS` + `DMA_IRQ_ACK` (W1C); optional **`DMA_CTRL[8]`** ORs DMA sticky IRQs into the existing **`irq`** line |

## Register map (byte offsets from `ADS1278_MMIO_BASE` `0x42000000`)

| Offset | Name | R/W | Purpose (short) |
|--------|------|-----|------------------|
| `0x38` | `DMA_CTRL` | R/W | `[0]` enable, `[2:1]` mode, `[8]` irq enable |
| `0x3C` | `DMA_BASE_ADDR` | R/W | DDR physical base; `0` → default `0x1E000000` |
| `0x40` | `DMA_BUF_SIZE` | R/W | Bytes; must be `N×128`, `N∈[1,65536]` |
| `0x44` | `DMA_STATUS` | R | Enabled/running/config_err + pending + `last_bresp` + write index mirror |
| `0x48` | `DMA_WRITE_INDEX` | R | Current `axis_ram_writer` burst index (16-bit) |
| `0x4C` | `DMA_WRAP_COUNT` | R | Count of completed buffer wraps (AW at max index) |
| `0x50` | `DMA_ERROR_COUNT` | R | Count of non-OKAY write responses |
| `0x54` | `DMA_IRQ_STATUS` | R | Sticky: `[0]` wrap, `[1]` bresp error, `[2]` config error |
| `0x58` | `DMA_IRQ_ACK` | W1C | Clear selected bits in `DMA_IRQ_STATUS` |

Bit constants for C: `server/memory_map.h` (`ADS1278_DMA_CTRL_*`, `ADS1278_DMA_STATUS_*`, `ADS1278_DMA_IRQ_*`).

## Behavioral changes vs Phase 4 bring-up

- **`CTRL` bit 1 alone does not start DDR test writes.** Use **`DMA_CTRL[0]`** after programming base/size (defaults after reset: base **`0x1E000000`**, size **`0x10000`** match the old carve-out).
- **`rpdevmem ddr-dump` / `ddr-read`** read **`DMA_BASE_ADDR` + `DMA_BUF_SIZE`** from MMIO first; if you reprogram the buffer, update those registers before dumping.

## Suggested on-target smoke test (after new bitstream + `rpdevmem`)

```sh
devmem dma-status
devmem write 0x3c 0x1e000000
devmem write 0x40 0x00010000
devmem write 0x38 0x1
devmem dma-status
devmem ddr-dump 16
devmem write 0x38 0x0
devmem write 0x58 0x7
```

## Key files (source of truth)

| Area | Path |
|------|------|
| Migration plan (Phase 5 definition) | `docs/handoffs/20260416_dma-route-migration-plan.md` |
| Phase 4 context (HP0 path, old shortcut) | `docs/handoffs/20260421_phase4-pl-ddr-hp0-bringup.md` |
| MMIO slave + register map comment | `fpga/rtl/ads1278_axi_slave.sv` |
| Top-level PS/DMA wiring | `fpga/rtl/red_pitaya_top.sv`, `fpga/rtl/red_pitaya_ps.sv` |
| Programmable DMA writer integration | `fpga/rtl/ads1278_dma_phase4.v` |
| SW offsets / masks | `server/memory_map.h` |
| Board debug helper | `server/rpdevmem.c` |

## Design notes and caveats

1. **DDR safety:** Programming **`DMA_BASE_ADDR` / `DMA_BUF_SIZE`** to overlap the running kernel is still dangerous; reserve memory in device tree / bootargs or use a known carve-out.
2. **Coherency:** HP0 is not ACP; `/dev/mem` readback may still need cache discipline for production paths (unchanged from Phase 4 notes).
3. **Mode `≠ 0`:** Currently treated as **unsupported** → **`config_error`**, writer off. Extend `ads1278_dma_phase4` when muxing real capture (migration Phase 7).
4. **`server/server.c`** does not yet speak the new registers; only **`rpdevmem`** and headers were extended. Phase 6+ should wire buffer ownership and server-side consumption.

## Suggested next steps (for the receiving agent)

1. **Vivado build** with updated `AW` and RTL; load bitstream and run the smoke test above.
2. **Phase 6:** ping-pong buffers + explicit “buffer full / software owns” semantics per migration plan.
3. **Server:** add optional DMA arm/disarm path or extend protocol when bulk capture is defined.

## References

- Internal: `docs/handoffs/20260416_dma-route-migration-plan.md` (Phase 5–6)
- Internal: `docs/handoffs/20260421_phase4-pl-ddr-hp0-bringup.md`
- External pattern: [Direct memory access — Red Pitaya Notes](https://pavel-demin.github.io/red-pitaya-notes/dma/?utm_source=chatgpt.com)

## Handoff command compliance

- **Output path**: `docs/handoffs/20260422_phase5-dma-mmio-control.md`
- **Note**: `.cursor/rules/handoff-documents.mdc` was not present in this workspace; structure follows existing handoffs under `docs/handoffs/`.
