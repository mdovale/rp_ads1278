# rp_ads1278 — Phase 4 handoff (PL master path to DDR)

This handoff documents **Phase 4** of the DMA migration plan: a **PL-originated AXI write path into DDR** via the PS **high-performance slave port `S_AXI_HP0`**, while keeping the existing **`M_AXI_GP0` AXI4-Lite** control plane unchanged. It follows the intent of `docs/handoffs/20260416_dma-route-migration-plan.md` (Phase 4) and the reference pattern described in [Pavel Demin’s Red Pitaya DMA notes](https://pavel-demin.github.io/red-pitaya-notes/dma/?utm_source=chatgpt.com) (custom burst writer into DDR).

## Summary

- **Block design** (`fpga/source/system_design_bd_rp125_14/system.tcl`): **`PCW_USE_S_AXI_HP0` is enabled** with **`PCW_S_AXI_HP0_DATA_WIDTH {64}`**. An external BD interface port **`S_AXI_HP0`** (slave, AXI3, 64-bit data, 6-bit ID) is created and tied to `processing_system7/S_AXI_HP0`. **`PL_ACLK`** is associated with both **`M_AXI_GP0`** and **`S_AXI_HP0`**; `S_AXI_HP0_ACLK` is clocked from `PL_ACLK` alongside `M_AXI_GP0_ACLK`.
- **RTL** (`fpga/rtl/red_pitaya_ps.sv`): wires flattened **`S_AXI_HP0_*`** signals from the generated `system` wrapper to a new top-level DMA bring-up block **`ads1278_dma_phase4`**.
- **RTL** (`fpga/rtl/ads1278_dma_phase4.v` + helpers): implements a **synthetic 32-bit incrementing stream** (`ads1278_dma_pattern_source`) into a local **`axis_ram_writer`** (reference-style burst writer) plus **`output_buffer`** skid buffers (`reference/axis_ram_writer.v` lineage). Default DDR target is **`0x1E000000`** with a bounded burst-index ceiling (**`BURST_COUNT_MAX = 511`**) matching the writer’s address stepping model.
- **Control gating (temporary)**: `ads1278_axi_slave` exposes **`dma_phase4_enable`**, currently **tied to `CTRL[1]` (acquisition enable)** and threaded through `red_pitaya_top` → `red_pitaya_ps`. This is **bring-up only** until Phase 5 adds explicit DMA MMIO registers.
- **Software constants**: `server/memory_map.h` defines **`ADS1278_DMA_PHASE4_DDR_BASE`** and **`ADS1278_DMA_PHASE4_DDR_SIZE`** for the fixed test region (no server consumer yet).

## Why this handoff exists

Phase 4’s success criterion is **end-to-end proof that PL can write a known pattern into DDR and that software can observe it**. The FPGA and TCL changes above implement the **hardware path** and a **deterministic pattern source**, but **on-target validation** (Vivado build against the updated BD, bitstream load, `/dev/mem` readback, coherency checks) was not completed in the authoring session. The next owner should treat **wrapper port naming** and **live DDR safety** as the highest-risk follow-ups.

## Phase 4 checklist (from migration plan)

From `docs/handoffs/20260416_dma-route-migration-plan.md` § “Phase 4. Add a PL master path to DDR”:

| Plan item | Status |
|-----------|--------|
| Enable PS memory-facing interface for PL masters | **Done in TCL** (`S_AXI_HP0`, 64-bit) |
| Connect DMA-capable / custom AXI master to that path | **Done in RTL** (`ads1278_dma_phase4` → `S_AXI_HP0_*`) |
| Keep `M_AXI_GP0` for AXI4-Lite | **Unchanged** |
| PL writes **test-pattern** data into a **known** DDR buffer | **Implemented** (pattern + fixed base `0x1E000000`) |
| Software confirms DDR contents | **Not done here** — needs board + mmap/CMA workflow |

## Key files (source of truth)

| Area | Path |
|------|------|
| Migration plan (Phase 4 definition) | `docs/handoffs/20260416_dma-route-migration-plan.md` |
| BD: HP0 enable + export | `fpga/source/system_design_bd_rp125_14/system.tcl` |
| PS wrapper + HP0 flattening + DMA block | `fpga/rtl/red_pitaya_ps.sv` |
| Top-level signal stitch | `fpga/rtl/red_pitaya_top.sv` |
| MMIO slave (temporary `dma_phase4_enable`) | `fpga/rtl/ads1278_axi_slave.sv` |
| Phase 4 integration | `fpga/rtl/ads1278_dma_phase4.v` |
| Pattern source | `fpga/rtl/ads1278_dma_pattern_source.v` |
| Burst writer (reference-style) | `fpga/rtl/axis_ram_writer.v` |
| Skid buffer helper | `fpga/rtl/output_buffer.v` |
| Vivado file list | `fpga/source/cfg_rp125_14/ads1278.tcl` |
| SW DDR test region constants | `server/memory_map.h` |
| Reference originals (read-only) | `reference/README.md`, `reference/axis_ram_writer.v` |

## Design notes and caveats

1. **HP0 vs ACP**: The reference BD snippet uses **ACP** (`reference/block_design.tcl`). This project uses **`S_AXI_HP0`** at **64-bit** to match the reference **`axis_ram_writer`** burst width. Cache coherency behavior differs from ACP; software readback may need **flush/invalidate** or a **CMA/non-cacheable** mapping strategy once Linux is involved.
2. **AXI3 `WID`**: The writer drives **`m_axi_wid`**. HP0 on Zynq-7 expects AXI3-style write IDs on this path; keep an eye on synthesis/elaboration warnings if Vivado infers AXI4-only adapters.
3. **Temporary enable = acquisition enable**: **`dma_phase4_enable`** is currently **`ctrl_enable`**. That means **turning on acquisition also turns on continuous DDR test writes** into **`0x1E000000`**. This is useful for bench bring-up but is **not** a safe long-term default on a live Linux system until buffer ownership is explicit (Phase 5 / Phase 6).
4. **DDR address choice**: **`0x1E000000`** is a **fixed carve-out** for early testing only. The next session must confirm it does not collide with the running kernel’s memory map on your Red Pitaya image; adjust **`DDR_BASE_ADDR`** in `ads1278_dma_phase4` and **`ADS1278_DMA_PHASE4_*`** in `server/memory_map.h` together.
5. **Generated `system` wrapper port names**: `red_pitaya_ps.sv` assumes **`S_AXI_HP0_*`** flattened ports on `system`. If Vivado regenerates a different naming convention, **elaboration will fail** until ports are reconciled.

## Suggested next steps (for the receiving agent)

1. **Run Vivado** (`fpga-build.sh --target rp125_14` or your usual flow) and fix any **BD validation** or **wrapper port** mismatches.
2. **Hardware Phase 4 validation**:
   - Load bitstream.
   - Enable acquisition (`CTRL` bit 1) or temporarily gate DMA on a dedicated bit after Phase 5.
   - Map **`ADS1278_DMA_PHASE4_DDR_BASE`** for **`ADS1278_DMA_PHASE4_DDR_SIZE`** via `/dev/mem` (or CMA once available) and verify **monotonic 32-bit words** / burst structure.
3. **Phase 5**: move enable, base address, length, status (`sts_data` / error counters) into **`ads1278_axi_slave`** MMIO registers per the migration plan; remove the **`dma_phase4_enable` → `ctrl_enable`** shortcut.
4. **Phase 7 alignment**: keep synthetic validation until the writer is proven; only then mux the stream source from **`ads1278_acq_top`** frame FIFO output.

## References

- Internal: `docs/handoffs/20260416_dma-route-migration-plan.md` (Phase 4–5)
- External pattern: [Direct memory access — Red Pitaya Notes](https://pavel-demin.github.io/red-pitaya-notes/dma/?utm_source=chatgpt.com)

## Handoff command compliance

- **Output path**: `docs/handoffs/20260421_phase4-pl-ddr-hp0-bringup.md`
- **Note**: `.cursor/rules/handoff-documents.mdc` was not present in this workspace; structure follows existing handoffs under `docs/handoffs/`.
