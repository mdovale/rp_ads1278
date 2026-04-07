# rp_ads1278 - stock FPGA recovery handoff

This handoff captures the current failure mode where the Red Pitaya ARM/Linux side resets immediately after FPGA configuration, and turns that investigation into a concrete recovery plan. The intended approach is explicitly conservative: keep the Red Pitaya design as close to stock and to the working authored references as possible, and only add the minimum ADS1278-specific logic needed for acquisition.

## Summary

- The current `fpga/` tree builds and deploys a bitstream, but the board resets or drops off immediately after the FPGA is configured.
- The strongest current evidence points to a Red Pitaya integration problem in the FPGA top-level and block-design contract, not to the ADS1278 SPI capture state machine itself.
- The current custom FPGA design diverges too far from stock Red Pitaya behavior:
  - it replaces the normal board-side housekeeping path,
  - it places the custom ADS1278 register block at `0x40000000`,
  - it drives expansion and LED pins directly instead of following the stock I/O buffering pattern,
  - it keeps XADC-related ports and constraints in an inconsistent state.
- The safest next step is not to continue incrementally patching the current custom top-level. Instead, rebuild the FPGA integration from the working reference architecture in `.reference/`, preserving stock Red Pitaya structure and inserting ADS1278 support as one additional feature block.
- The intended software architecture remains the same three layers:
  - `fpga/`
  - `server/`
  - `client/`
- `server/` and `client/` should change only as much as needed to follow the corrected FPGA MMIO contract.

## Why this handoff exists

The repo already has the three layers in-tree and the deploy scripts can program the FPGA, but the current FPGA image is not operationally safe because it destabilizes the board after configuration.

The next session should focus on restoring a stable Red Pitaya-compatible FPGA baseline first, then layering the ADS1278 acquisition path back in with minimal changes. This should be treated as a re-integration task using the working reference projects, not as a greenfield redesign.

The user explicitly called out the best sources of truth for this recovery:

- `.reference/rpll_fpga`
- `.reference/rpll_server`
- `.reference/rpll_client`
- `.reference/RedPitaya-FPGA`

Those references should be treated as the preferred template for structure, top-level wiring, PS/PL integration, address-map conventions, and deployment expectations. `.reference/` is read-only, but code can be copied from it into the live repo as needed.

## Problem and reproduction

Observed on real hardware:

1. `fpga-build.sh` produces a bitstream successfully.
2. `fpga-deploy.sh` successfully copies and programs the bitstream.
3. Manual programming with `fpgautil` shows the same behavior.
4. Immediately after FPGA configuration, the Red Pitaya ARM/Linux system resets or becomes unavailable.

Important implications:

- The failure is not specific to the deploy script.
- The failure happens after the FPGA is accepted by the configuration path.
- The problem is therefore more consistent with an invalid or incompatible running PL design than with a bad transfer or a bad `.bit.bin` conversion step.

## Current findings

### 1. The current design replaces stock Red Pitaya behavior at the wrong abstraction layer

The custom design currently exposes a single custom AXI-lite register block and maps it at `0x40000000`, while directly wiring ADS1278 signals at the top-level boundary.

Current evidence:

- `fpga/rtl/red_pitaya_top.sv` instantiates `ads1278_axi_slave` directly as the main PL-facing control block.
- `fpga/source/system_design_bd_rp125_14/system.tcl` maps the only exported custom register aperture at `0x40000000`.
- `docs/feats/fpga-register-map.md` documents that same base address.

This is risky because on stock Red Pitaya systems, `0x40000000` is normally the housekeeping region, not a project-specific acquisition block. Replacing that contract is the most plausible explanation for the board instability after programming.

### 2. The current top-level no longer follows stock Red Pitaya I/O buffering patterns

The current custom top-level directly assigns `exp_p_io[*]`, `exp_n_io[*]`, and `led_o[*]` rather than following the stock `IOBUF`-based handling used in Red Pitaya reference designs.

Current evidence:

- `fpga/rtl/red_pitaya_top.sv` drives expansion pins with direct assignments and reads back from the same inout nets.
- The Vivado log reports repeated `RPBF-3` warnings that IO port buffering is incomplete for `exp_p_io[*]` and `led_o[*]`.

This does not by itself prove the reset cause, but it is a clear sign that the top-level is not preserving the expected board I/O wrapper behavior.

### 3. XADC and constraints are inconsistent

The current design still constrains XADC-related pins even though the PS wrapper and custom top-level do not appear to preserve stock XADC integration cleanly.

Current evidence:

- `fpga/source/cons_rp125_14/ports.xdc` constrains `vinp_i[4]` and `vinn_i[4]` to `K9` and `L10`.
- The Vivado log reports critical warnings that regular IO cannot be placed on those XADC/system monitor sites.
- `fpga/rtl/red_pitaya_ps.sv` still exposes `vinp_i` and `vinn_i`, but the custom wrapper is much thinner than the stock Red Pitaya PS integration and should be compared directly against the working reference before trusting it.

This is a concrete correctness issue that should be fixed even if it is not the only cause of the board reset.

### 4. The block-design and toolchain state are not yet trustworthy

The current build log includes multiple warnings that reduce confidence in the generated design:

- missing `S_AXI_GP2` and `S_AXI_GP3` physical ports in the BD port map,
- a generated wrapper import warning,
- a warning that no associated reset port was found for `M_AXI_GP0`,
- final timing failure (`WNS=-0.062 ns`),
- build performed in `Vivado 2020.1` while the repo build script still advertises `2017.2` for `rp125_14`.

None of these individually proves the reset, but together they are strong evidence that the current FPGA image should not be treated as a known-good foundation.

## Current state to preserve

The recovery work should preserve these project-level goals unless a deliberate change is made across code and docs together.

- Keep `README.md` as the source of truth for end-state architecture and ADS1278 signal intent.
- Keep the three-layer architecture:
  - FPGA on the Red Pitaya PL
  - server on the Red Pitaya ARM
  - Python client on the host
- Keep the ADS1278-facing E1 mapping intent unless a board-level change is required:
  - `exp_p_io[0]` = `SCLK`
  - `exp_p_io[1]` = `DOUT1`
  - `exp_p_io[2]` = `/DRDY`
  - `exp_p_io[3]` = `/SYNC`
  - `exp_p_io[4]` = `EXTCLK`
- Keep the current server/client wire protocol unless the FPGA integration forces a register-map change that must be propagated to `server/` and the docs.
- Keep `.reference/` read-only.

## Recommended recovery strategy

### 1. Rebase the FPGA integration on a working stock-style reference

Do not continue iterating the current custom `red_pitaya_top.sv` as the primary recovery path.

Preferred approach:

1. Start from the working top-level, PS wrapper, constraints, and block-design structure in `.reference/rpll_fpga` and/or `.reference/RedPitaya-FPGA`.
2. Restore stock-compatible Red Pitaya behavior first:
   - housekeeping path,
   - standard system-bus or reference bus structure,
   - proper `IOBUF` handling for expansion pins,
   - stock-compatible XADC wiring or stock-compatible removal of unused analog paths,
   - reference-consistent PS/PL clock and reset wiring.
3. Re-introduce ADS1278 support as one additional peripheral block instead of replacing the board baseline.

The key design rule is:

- preserve reference behavior by default,
- add ADS1278-specific behavior only where it is actually needed.

### 2. Do not keep the ADS1278 block at `0x40000000` if that conflicts with stock housekeeping

The current mapping to `0x40000000` is likely wrong for a stock-preserving Red Pitaya design.

Preferred approach:

- keep stock housekeeping at its stock address,
- place the ADS1278 register block at a separate project-specific address region following the reference bus layout,
- then update:
  - `server/memory_map.h`
  - any other server-side MMIO constants
  - docs that mention the MMIO base
  - deploy-time verification checks

This is a safer change than continuing to impersonate the housekeeping block.

### 3. Preserve the ADS1278 datapath only where it is already self-contained

The current investigation did not identify the ADS1278 acquisition pipeline as the primary board-reset cause.

That means the best reuse candidate is likely:

- `fpga/rtl/ads1278_acq_top.v`
- `fpga/rtl/ads1278_spi_tdm.v`
- `fpga/rtl/ads1278_extclk_gen.v`
- `fpga/rtl/ads1278_sync_pulse.v`

These blocks should be kept if they still meet the intended signal-level behavior after the board integration is rebuilt.

The higher-risk reuse candidate is:

- `fpga/rtl/ads1278_axi_slave.sv`

That module is tightly coupled to the current custom address-map decision and may need to be wrapped, adapted, or replaced to fit the restored stock-style bus architecture.

### 4. Use the reference server and client as validation anchors

The user highlighted that `.reference/rpll_server` and `.reference/rpll_client` are working examples of the same three-layer architecture.

Use them as integration references for:

- what a stable Red Pitaya server deployment path looks like,
- how the server should track MMIO base addresses and register offsets,
- how the client should remain insulated from FPGA-side address-map changes when the network protocol is unchanged.

The likely software consequence of the stock-first FPGA recovery is:

- `client/` may not need functional changes if the server protocol stays the same,
- `server/` may need only a small MMIO base/register-map update if the ADS1278 FPGA block moves away from `0x40000000`.

## Recommended order of work

### 1. Establish the stock/reference FPGA baseline

Goal: identify exactly which top-level and bus architecture should be treated as canonical.

Tasks:

- compare the live repo’s `fpga/rtl/red_pitaya_top.sv` against the working reference top-level in `.reference/rpll_fpga` and `.reference/RedPitaya-FPGA`,
- compare `fpga/rtl/red_pitaya_ps.sv` against the working reference PS wrapper,
- compare `fpga/source/system_design_bd_rp125_14/system.tcl` against the reference block-design structure,
- compare `fpga/source/cons_rp125_14/ports.xdc` and `clocks.xdc` against the reference constraints,
- determine the actual intended Vivado version from the working reference project, not just from current repo assumptions.

Deliverable:

- one explicit decision about which reference tree is the baseline for recovery.

### 2. Restore stock-compatible PS, bus, and board I/O behavior

Goal: make the board survive FPGA programming with no Linux reset.

Tasks:

- replace or heavily rebase the current custom top-level and PS wrapper with stock/reference-derived versions,
- restore proper `IOBUF` handling for expansion connector pins,
- restore stock-compatible LED and GPIO handling,
- fix or remove the inconsistent XADC constraints and ports,
- eliminate current Vivado critical warnings related to illegal XADC pin use and incomplete I/O buffering.

Deliverable:

- a bitstream that programs successfully and leaves the board reachable over SSH or serial afterward.

### 3. Re-integrate ADS1278 as a minimal additive feature

Goal: add only the hardware needed for ADS1278 acquisition while leaving the stock platform intact.

Tasks:

- keep the ADS1278 signal mapping on the E1 connector,
- connect the acquisition datapath into the restored stock-style top-level,
- expose a software-visible register block at a non-conflicting project-specific address,
- update the server MMIO base to the new address if needed,
- keep the current network protocol unchanged unless a change is unavoidable.

Deliverable:

- stable board operation plus successful MMIO access to the ADS1278 registers.

### 4. Rebuild and validate the software stack against the corrected FPGA contract

Goal: make the whole three-layer system work again with the corrected FPGA integration.

Tasks:

- update `server/memory_map.h` and any related server code if the FPGA base address changes,
- verify the server still emits the same capability string and 60-byte message format,
- confirm the client still works against the updated server,
- update docs to reflect the actual restored contract.

Deliverable:

- no board reset on FPGA load,
- successful server startup,
- successful client connection,
- successful enable, disable, divider, and sync operations.

### 5. Record one known-good hardware bring-up path

Goal: convert the recovered design into an ops-ready path.

Tasks:

- record the working Vivado version,
- record the working bitstream build command,
- record the working deploy sequence,
- record any required board-side service shutdown steps before programming,
- record MMIO verification steps,
- record the final wiring and observed acquisition behavior.

Deliverable:

- one reproducible lab procedure for build, deploy, run, and validate.

## What was tried and what failed

### Observed on hardware

- FPGA build succeeded.
- FPGA deploy succeeded.
- Manual `fpgautil` programming also succeeded.
- In both programming paths, the Red Pitaya reset or became unavailable immediately after FPGA configuration.

### Investigated in this session

- reviewed `docs/logs/20260407_fpga-build.txt`,
- reviewed `fpga/rtl/red_pitaya_top.sv`,
- reviewed `fpga/rtl/red_pitaya_ps.sv`,
- reviewed `fpga/source/system_design_bd_rp125_14/system.tcl`,
- reviewed `fpga/source/cons_rp125_14/ports.xdc`,
- reviewed current FPGA feature docs and the existing ops-readiness handoff,
- compared the current MMIO/address-map choice against official Red Pitaya documentation on stock housekeeping and custom bitstream loading.

### Main conclusions from that investigation

- the current failure is more likely caused by board-integration incompatibility than by the ADS1278 capture state machine,
- the current design is not stock-preserving enough to trust,
- the recovery should be driven by the working reference projects rather than continued ad hoc edits to the current custom top-level.

## Constraints

- `README.md` remains the end-state source of truth for system goals and signal intent.
- `.reference/` is read-only.
- Prefer copying and adapting from `.reference/rpll_fpga`, `.reference/rpll_server`, `.reference/rpll_client`, and `.reference/RedPitaya-FPGA` over inventing new architecture.
- Keep the Red Pitaya design as stock as possible.
- Only modify what is needed for ADS1278 integration.
- Do not keep a custom FPGA contract that silently breaks stock Red Pitaya board behavior.
- Do not change the client/server network protocol unless the same session updates code and docs together.

## Success criteria

- Programming the FPGA no longer resets or destabilizes the Red Pitaya ARM/Linux side.
- The recovered FPGA design preserves stock-compatible Red Pitaya board behavior outside the ADS1278-specific feature path.
- The ADS1278 register block lives at a deliberate, documented, non-conflicting address.
- `server/` uses the corrected MMIO contract and runs on the board.
- `client/` connects successfully and exercises the documented control path.
- The FPGA build completes without the current critical XADC and incomplete-I/O-buffering warnings.
- A known-good build and deploy path is documented for future sessions.

## Key files

| Area | File |
|------|------|
| End-state architecture | `README.md` |
| Current top-level RTL | `fpga/rtl/red_pitaya_top.sv` |
| Current PS wrapper | `fpga/rtl/red_pitaya_ps.sv` |
| Current ADS1278 AXI block | `fpga/rtl/ads1278_axi_slave.sv` |
| ADS1278 acquisition wrapper | `fpga/rtl/ads1278_acq_top.v` |
| ADS1278 SPI capture | `fpga/rtl/ads1278_spi_tdm.v` |
| EXTCLK generator | `fpga/rtl/ads1278_extclk_gen.v` |
| SYNC pulse generator | `fpga/rtl/ads1278_sync_pulse.v` |
| Current block design | `fpga/source/system_design_bd_rp125_14/system.tcl` |
| Current constraints | `fpga/source/cons_rp125_14/ports.xdc` |
| Build script | `fpga-build.sh` |
| Deploy script | `fpga-deploy.sh` |
| Server MMIO base | `server/memory_map.h` |
| Current ops handoff | `docs/handoffs/20260407_ops-readiness.md` |
| Build log | `docs/logs/20260407_fpga-build.txt` |
| Authored FPGA reference | `.reference/rpll_fpga` |
| Authored server reference | `.reference/rpll_server` |
| Authored client reference | `.reference/rpll_client` |
| Official FPGA reference | `.reference/RedPitaya-FPGA` |

## References

- `docs/logs/20260407_fpga-build.txt`
- `docs/feats/fpga-build-and-deploy.md`
- `docs/feats/fpga-register-map.md`
- `docs/feats/board-io-wiring.md`
- `docs/handoffs/20260407_ops-readiness.md`
- [Red Pitaya FPGA register map](https://redpitaya.readthedocs.io/en/latest/developerGuide/fpga/regset/in_dev/v0.94.html)
- [Red Pitaya custom FPGA loading](https://redpitaya.readthedocs.io/en/latest/developerGuide/fpga/advanced/fpga_advanced_loading.html)
