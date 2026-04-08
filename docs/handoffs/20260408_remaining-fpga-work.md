# rp_ads1278 - remaining FPGA work

This handoff captures the remaining FPGA-side work after the stock-style recovery refactors and the successful `2026-04-08` build. The project is now in a much better place: the board no longer resets when the bitstream is loaded, the old XADC and incomplete-I/O-buffering warning classes are gone, and the build completes with positive timing. The remaining work is now mostly cleanup plus real hardware validation.

## Summary

- The major stock-recovery goal has been achieved:
  - loading the FPGA bitstream no longer crashes or resets Red Pitaya Linux,
  - the MMIO contract has moved to `0x42000000`,
  - the build finishes successfully and generates `.bit` and `.bit.bin`.
- The latest build log is substantially healthier than the earlier broken state:
  - no XADC illegal-placement critical warnings,
  - no `RPBF-3` incomplete I/O buffering warnings,
  - final route timing is positive,
  - `write_bitstream` completes successfully.
- Remaining FPGA work is now in four buckets:
  1. clean up the one remaining real critical-warning class (`dac_pwm_o[*]` IOB constraints),
  2. optionally reduce non-blocking expansion-connector `BUFC-1` warnings,
  3. clean up block-design generation noise where practical,
  4. complete first real hardware bring-up and capture a known-good operator path.

## Why this handoff exists

The earlier handoff `docs/handoffs/20260407_stock-fpga-recovery.md` was about escaping a fundamentally unsafe FPGA integration. The current state is different:

- the design now appears safe enough to load,
- the remaining warnings are smaller and more local,
- the next major value is not architectural redesign,
- the next major value is targeted cleanup plus bench validation.

This handoff is meant to tell the next session exactly what still matters on the FPGA side and in what order it should be tackled.

## Current state

### What is now working

- `fpga-build.sh` completes successfully for `rp125_14`.
- `bootgen` successfully produces the `.bit.bin`.
- The checked-in block design maps the MMIO aperture at `0x42000000`.
- The Red Pitaya no longer resets immediately after FPGA programming.
- The current build log shows:
  - final routed setup timing `WNS=0.108`,
  - final routed hold timing `WHS=0.019`,
  - zero routing failures,
  - zero Vivado errors.

### Important implementation truth

Use these as the current source of truth:

- MMIO base: `0x42000000`
- AXI aperture: `0x1000`
- server MMIO consumer: `server/memory_map.h`
- BD address assignment: `fpga/source/system_design_bd_rp125_14/system.tcl`
- current top-level: `fpga/rtl/red_pitaya_top.sv`
- current board IO mapping: `docs/feats/board-io-wiring.md`

Do not regress back toward the earlier `0x40000000` custom-housekeeping conflict described in the older recovery handoff.

## Latest build-log findings

Source reviewed:

- `docs/logs/20260408_fpga-build.txt`

### Improvements relative to the broken pre-recovery state

- The old XADC placement failures are gone.
- The old `RPBF-3` incomplete I/O buffering warnings are gone.
- The build now routes successfully.
- The final routed timing is positive.

This is the strongest evidence so far that the stock-style refactor moved the design in the right direction.

### Remaining warning classes

#### 1. `dac_pwm_o[*]` IOB critical warnings

The only remaining critical warnings in the build are:

- `Place 30-722` on `dac_pwm_o[0..3]`
- corresponding `PLIO-8` warnings later in the flow

Why they happen:

- `fpga/rtl/red_pitaya_top.sv` ties `dac_pwm_o` low:
  - `assign dac_pwm_o = 4'h0;`
- `fpga/source/cons_rp125_14/ports.xdc` still applies:
  - `set_property IOB TRUE [get_ports {dac_pwm_o[*]}]`

That means Vivado is being asked to pack an I/O register for signals that are not driven by a suitable flop path.

Assessment:

- This is a real cleanup target.
- It does not currently look like an ADS1278-path blocker.
- It is the highest-priority remaining FPGA cleanup item because it is the only remaining critical-warning class.

Recommended action:

- remove `IOB TRUE` from `dac_pwm_o[*]` unless there is a specific need to preserve registered PWM outputs for stock compatibility.

#### 2. Expansion `BUFC-1` warnings on `gen_exp_iobuf[*]`

These warnings occur at bitstream generation time and say the input side of some `IOBUF` instances has no internal load.

Why they happen:

- the design now uses a generic `IOBUF` wrapper for all `exp_p_io[*]` and `exp_n_io[*]`,
- many of those pins are intentionally unused,
- some are output-only from the ADS1278 point of view,
- the input side of those buffers is therefore intentionally unconsumed.

Assessment:

- These warnings are expected given the current generic wrapper approach.
- They are much less concerning than the old `RPBF-3` warnings.
- They do not look like a blocker for first hardware bring-up.

Recommended action:

- defer for now unless you want a cleaner build log,
- later, optionally specialize the wrapper:
  - use `IBUF` for true input-only pins,
  - use `OBUFT` or plain output buffering for true output-only pins,
  - avoid instantiating generic `IOBUF` on permanently unused connector pins.

#### 3. Block-design / generated-project warnings

Remaining non-fatal warnings include:

- missing `S_AXI_GP2_*` and `S_AXI_GP3_*` physical ports in the BD portmap,
- generated wrapper already imported,
- out-of-context constraint overwrite,
- missing associated reset metadata for `M_AXI_GP0`.

Assessment:

- these look like generated-project / IP-integrator hygiene issues,
- not like a current board-safety issue,
- worth cleaning later, but not worth blocking bring-up on today.

Recommended action:

- defer until after first successful hardware acquisition,
- then clean the BD generation flow so the project regenerates without wrapper-import churn and stale PS7 metadata.

#### 4. Power-analysis warning

- `Power 33-332` says vector-less switching suggests high-fanout resets are asserted excessively.

Assessment:

- this is about power estimation quality, not functionality,
- not a bring-up blocker.

Recommended action:

- ignore for now unless power analysis becomes relevant.

## What should be done next

### Immediate next step

Run the manual QA / bring-up checklist in:

- `docs/handoffs/20260408_pre-bringup-manual-qa.md`

That should be treated as the primary next action, not more large FPGA refactoring.

### FPGA cleanup tasks to do before or shortly after bring-up

#### Task 1. Remove stale `IOB TRUE` on `dac_pwm_o[*]`

Goal:

- eliminate the remaining critical warnings that are clearly caused by the current constraints/RTL mismatch.

Files:

- `fpga/source/cons_rp125_14/ports.xdc`
- optionally `fpga/rtl/red_pitaya_top.sv` if the stock-compatibility tie-off is revised

Success criteria:

- no more `Place 30-722` or `PLIO-8` warnings for `dac_pwm_o[*]`
- build still completes and the board still programs safely

#### Task 2. Keep first bring-up focused on functional validation

Goal:

- prove the live ADS1278 path works before chasing cosmetic build-log cleanup.

Checks:

- MMIO reads/writes at `0x42000000`
- `EXTCLK_DIV` readback
- enable readback
- scope-visible `EXTCLK`
- scope-visible `/SYNC`
- idle `SCLK` with no ADC
- live `/DRDY`, `SCLK`, and sample streaming with ADC attached

Success criteria:

- `frame_cnt` advances when the EVM is wired and enabled
- client plots update
- no unexplained divider snap-back

#### Task 3. Optionally clean up expansion-buffer warnings

Goal:

- reduce `BUFC-1` noise without regressing the now-correct stock-style top-level behavior.

Files:

- `fpga/rtl/red_pitaya_top.sv`
- possibly `fpga/source/cons_rp125_14/ports.xdc`

Potential approach:

- keep the current logical mapping,
- but instantiate only the buffer primitive actually needed per pin direction,
- or stop buffering/constraining permanently unused `exp_n_io[*]` pins if that is safe for stock compatibility.

Success criteria:

- fewer or no `BUFC-1` warnings
- no reintroduction of `RPBF-3`
- no regression in bench behavior

#### Task 4. Clean up BD-generation noise

Goal:

- make the FPGA project regenerate more cleanly and more predictably.

Files:

- `fpga/source/system_design_bd_rp125_14/system.tcl`
- `fpga/regenerate_project_and_bd.tcl`
- any related project-generation Tcl

Potential approach:

- ensure wrapper generation/import happens exactly once,
- prune stale PS7 metadata if possible,
- verify the AXI reset association is explicit enough for Vivado to stop inventing defaults.

Success criteria:

- fewer repeated BD/IP warnings during project regeneration,
- no change to the generated address map or working hardware behavior unless intentional

## Recommended order of work

1. Run the no-hardware portions of `20260408_pre-bringup-manual-qa.md`.
2. If desired, make the `dac_pwm_o[*]` constraint cleanup before first live wiring.
3. Perform first controlled ADS1278EVM bring-up.
4. If acquisition works, record one known-good build/deploy/wiring procedure.
5. Only after that, spend time on `BUFC-1` and BD-generation cleanup.

## What was tried and what failed

### Earlier state

The earlier custom top-level had serious integration issues:

- board reset after FPGA programming,
- XADC-related critical warnings,
- incomplete I/O buffering warnings,
- untrustworthy board behavior.

### Current state

Those earlier failure classes appear to have been substantially addressed, but full end-to-end ADS1278 acquisition has not yet been proven on hardware.

## Constraints

- `README.md` remains the end-state source of truth.
- `.reference/` remains read-only.
- Keep the current `0x42000000` address-map decision unless there is a deliberate, repo-wide reason to change it.
- Do not regress back toward non-stock Red Pitaya integration patterns that destabilize the board.
- Prefer small, bench-verified cleanups over broad FPGA restructuring.
- Keep the server/client protocol unchanged unless an unavoidable FPGA contract change requires synchronized updates.

## Success criteria

- The current FPGA image continues to program without resetting the board.
- The no-hardware QA checklist passes cleanly.
- The ADS1278EVM can be wired and observed producing:
  - valid `EXTCLK`,
  - valid `/DRDY`,
  - `SCLK` bursts,
  - advancing `frame_cnt`,
  - non-static sample data in the client.
- The remaining `dac_pwm_o[*]` critical warnings are removed.
- The build log is cleaner without reintroducing any of the earlier stock-compatibility failures.
- One reproducible known-good hardware bring-up path is documented.

## Key files

| Area | File |
|------|------|
| Latest build log | `docs/logs/20260408_fpga-build.txt` |
| Pre-bring-up checklist | `docs/handoffs/20260408_pre-bringup-manual-qa.md` |
| Prior recovery handoff | `docs/handoffs/20260407_stock-fpga-recovery.md` |
| Current top-level RTL | `fpga/rtl/red_pitaya_top.sv` |
| AXI register block | `fpga/rtl/ads1278_axi_slave.sv` |
| Acquisition wrapper | `fpga/rtl/ads1278_acq_top.v` |
| SPI capture | `fpga/rtl/ads1278_spi_tdm.v` |
| EXTCLK generator | `fpga/rtl/ads1278_extclk_gen.v` |
| SYNC pulse generator | `fpga/rtl/ads1278_sync_pulse.v` |
| Current constraints | `fpga/source/cons_rp125_14/ports.xdc` |
| Current block design | `fpga/source/system_design_bd_rp125_14/system.tcl` |
| Server MMIO base | `server/memory_map.h` |

## References

- `README.md`
- `docs/logs/20260408_fpga-build.txt`
- `docs/feats/fpga-build-and-deploy.md`
- `docs/feats/fpga-register-map.md`
- `docs/feats/server-mmio-contract.md`
- `docs/feats/board-io-wiring.md`
- `docs/handoffs/20260407_stock-fpga-recovery.md`
- `docs/handoffs/20260408_pre-bringup-manual-qa.md`
