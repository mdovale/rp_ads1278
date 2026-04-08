# FPGA Build And Deploy

This doc describes the current checked-in FPGA build and deployment flow for `rp_ads1278`. It covers the repo scripts, project-generation TCL entry points, expected outputs, and the known gaps that still prevent this path from being treated as fully validated.

## Goal

Document how the repository currently builds the `rp125_14` FPGA image and deploys it to a Red Pitaya running OS 2.x+, using the implementation that is actually checked into the repo today.

## Scope

- In scope: `fpga-build.sh`, `fpga-deploy.sh`, the Vivado TCL entry points they invoke, expected output locations, supported execution modes, and current deployment assumptions.
- Out of scope: board-level electrical wiring, MMIO register semantics, server/client runtime behavior, and a claim that the flow has already been hardware-validated end to end.

## User-facing behavior

The current repo exposes one FPGA build entry point and one FPGA deploy entry point:

- `./fpga-build.sh --target rp125_14`
- `./fpga-deploy.sh --target rp125_14 --ip <red-pitaya-host>`

Current script-level behavior:

| Step | Behavior |
|------|------|
| Build target | Only `rp125_14` is accepted |
| Build modes | Local Vivado, Docker-based Vivado, and remote SSH-based Vivado are supported by the script |
| Project generation | Build regenerates the Vivado project and block design from checked-in TCL |
| Synthesis top | The intended synthesis top is `red_pitaya_top`, not the block-design wrapper |
| Output location | Bitstreams are expected under `fpga/work125_14/rp_ads1278.runs/impl_1/` |
| Output naming | The build script normalizes outputs to `ads1278.bit` and `ads1278.bit.bin` when possible |
| Build result validation | The build script fails if the normalized `ads1278.bit` and `ads1278.bit.bin` outputs are not present at the end of the flow |
| Deployment format | Deployment requires `.bit.bin` format for Red Pitaya OS 2.x+ FPGA Manager |
| Deployment method | Deploy copies the bitstream to the board over `scp` and optionally programs it with `fpgautil -b` |

Current build-script assumptions:

- If no explicit Vivado path is given, `fpga-build.sh` looks for `vivado` in `PATH`.
- For `rp125_14`, the local fallback Vivado path is `/opt/Xilinx/Vivado/2017.2/bin/vivado`.
- The block-design TCL itself was generated with Vivado `2020.1` and only warns when versions differ.
- The default supported build path skips custom core generation because the repo does not currently contain the optional `fpga/library/lib_src/my_cores_build_src` tree.

Current deployment-script assumptions:

- The board is reachable over SSH.
- The target OS provides `/opt/redpitaya/bin/fpgautil`.
- The deploy path is intended for Red Pitaya OS 2.x+.
- The remote user defaults to `root`.

## Architecture

The current FPGA build flow is composed of one shell entry point plus a small TCL stack:

1. `fpga-build.sh` validates the target and required project files.
2. It optionally runs a custom-core generation step inside `fpga/library/lib_src/`.
3. It writes a temporary TCL launcher that sources `fpga/regenerate_project_and_bd.tcl`.
4. `regenerate_project_and_bd.tcl`:
   - loads `fpga/tcl/board_config_rp125_14.tcl`
   - deletes the old board work directory
   - sources `fpga/source/cfg_rp125_14/ads1278.tcl`
   - sources `fpga/source/system_design_bd_rp125_14/system.tcl`
   - generates the BD wrapper
   - explicitly resets the synthesis top back to `red_pitaya_top`
5. `fpga-build.sh` launches `impl_1` through `write_bitstream`.
6. After implementation, the script tries to produce a `.bit.bin` using `bootgen`.
7. The script normalizes final filenames to `ads1278.bit` and `ads1278.bit.bin`.

Project-configuration ownership:

- `fpga/tcl/board_config_rp125_14.tcl` defines the board part, work directory, and source/config paths.
- `fpga/source/cfg_rp125_14/ads1278.tcl` lists RTL files, marks SystemVerilog sources, and adds constraints.
- `fpga/source/system_design_bd_rp125_14/system.tcl` defines the block design and address map.

The deployment flow is simpler:

1. `fpga-deploy.sh` resolves a bitstream path.
2. It prefers `ads1278.bit.bin` under `fpga/work125_14/rp_ads1278.runs/impl_1/`.
3. It copies the bitstream to the board with `scp`.
4. If programming is enabled, it runs `fpgautil -b <bitstream>` on the board.
5. It then checks FPGA Manager state and performs an optional `devmem` probe.

## Known risk areas

- The optional `--make-cores` path still depends on repo content that is not currently checked in, so it should be treated as unsupported unless that source tree is added deliberately.
- The build flow is present in-tree, but this repo does not yet record a known-good clean build result.
- The local build script assumes Vivado `2017.2` for `rp125_14`, while `fpga/source/system_design_bd_rp125_14/system.tcl` declares itself a `2020.1` generated script and only warns on mismatch.
- Deployment requires `.bit.bin`; a raw `.bit` is rejected by the deploy script.

## Manual QA

Useful current checks for this feature area:

- Confirm `./fpga-build.sh --target rp125_14` reaches preflight successfully from the default repo state.
- Confirm the produced output directory is `fpga/work125_14/rp_ads1278.runs/impl_1/`.
- Confirm both `ads1278.bit` and `ads1278.bit.bin` exist after a successful build.
- Confirm `./fpga-deploy.sh --target rp125_14 --ip <host>` can copy and program the `.bit.bin`.
- After deployment, confirm FPGA Manager reports `operating`.
- If `devmem` is available on the board, confirm reads at `0x42000000` succeed after programming.

## Key files

| Area | File |
|------|------|
| Build entry point | `fpga-build.sh` |
| Deploy entry point | `fpga-deploy.sh` |
| Project regeneration flow | `fpga/regenerate_project_and_bd.tcl` |
| Board configuration | `fpga/tcl/board_config_rp125_14.tcl` |
| Vivado project source list | `fpga/source/cfg_rp125_14/ads1278.tcl` |
| Block design | `fpga/source/system_design_bd_rp125_14/system.tcl` |
| Placeholder custom-core step | `fpga/library/lib_src/make_cores.tcl` |

## Related docs

- [FPGA Register Map](fpga-register-map.md)
- [ADS1278 Acquisition Pipeline](ads1278-acquisition-pipeline.md)
- [Board IO Wiring](board-io-wiring.md)
- [FPGA status and remaining bring-up work](../handoffs/20260304_fpga-work.md)
