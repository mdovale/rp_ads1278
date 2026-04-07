# rp_ads1278 - ops readiness handoff

This handoff captures the current state of `rp_ads1278` after an audit of `fpga/`, `server/`, `client/`, and the docs, with the specific goal of getting the project from "implemented enough for software bring-up" to "credible for repeatable lab ops on real hardware."

> Update after follow-up repo fixes: the in-tree gaps called out here around `fpga-build.sh`, `fpga-deploy.sh`, stale feature docs, the client divider UI, and the `README.md` clock wording have been addressed. The remaining ops-readiness gap is hardware validation and recording one known-good bring-up path.

## Summary

- The three layers are mostly aligned with the intended architecture in `README.md`.
- `server/` and `client/` are implemented, locally testable, and agree on the current v1 TCP protocol.
- The repo-side blockers around FPGA build defaults, deploy verification, and stale current-state docs have now been closed in-tree.
- The main remaining blocker to ops readiness is the lack of a recorded end-to-end hardware validation run.
- The next session should focus on proving the FPGA-to-board bring-up path on real hardware, not redesigning the client or server.

## Follow-up update

The following gaps from the original audit are now resolved in-tree:

- `fpga-build.sh` now defaults to the supported `--skip-cores` path instead of requiring missing custom-core sources.
- `fpga-build.sh` now fails if the expected normalized outputs `ads1278.bit` and `ads1278.bit.bin` are not produced.
- `fpga-deploy.sh` now verifies MMIO accessibility at `0x40000000`, which matches the block design, server code, and MMIO docs.
- The Python client now prevents `EXTCLK_DIV` values below the server minimum of `3`.
- `README.md` and the main FPGA/server protocol docs now describe the current repo truthfully instead of using stale "future server/client" wording.
- The older planning handoffs now carry short historical notes so they are less likely to be mistaken for current-state docs.

What is still not proven in this repo session:

- a known-good clean Vivado build result on a supported toolchain,
- a successful bitstream deploy to a Red Pitaya,
- MMIO accessibility verified on real hardware after programming,
- server startup on the board,
- Python client validation against the real board/server path,
- boot-cycle validation of the `systemd` startup path.

## Why this handoff exists

The repo now has all three layers in-tree, but the ops question is stricter than "does code exist?" The important remaining question is whether a future operator can:

1. build or obtain a correct FPGA image,
2. deploy it with trustworthy verification,
3. deploy and run the server on the board,
4. connect the Python client,
5. confirm real acquisition behavior on the ADS1278EVM,
6. follow docs that reflect the current repo truthfully.

The audit result is:

- mostly yes for server and client,
- not yet yes for the FPGA build and hardware validation story.

## Current repo state

### Implemented and aligned in source

- `README.md` still works as the end-state intent for the three-layer architecture.
- `fpga/` maps the MMIO aperture at `0x40000000`, uses the documented E1 wiring, and exposes the expected register block.
- `server/` maps `0x40000000`, exposes `RP_CAP:ads1278_v1\n`, listens on port `5000`, accepts 8-byte commands, and emits 60-byte messages.
- `client/` validates the capability line, decodes the 60-byte message layout, plots eight channels, sends the three commands, and logs `SAMPLE` messages to CSV.
- `systemd-service-deploy.sh` exists, so there is a checked-in path toward boot-time service startup once the FPGA and server deployment path are trustworthy.

### Verified locally in this session

- `cd server && make test` passed.
- `cd server && make` completed successfully.
- `PYTHONPATH=client .venv/bin/python -m pytest client/tests -v` passed.

### Not yet proven in this session

- No Vivado build was run here.
- No bitstream was deployed to a Red Pitaya here.
- No board-level or ADS1278EVM hardware validation was run here.
- No systemd boot-cycle validation was run here.

## Main blockers to ops readiness

### 1. FPGA build default path is still misleading and brittle

The main build script still defaults to a custom-core generation path that the repo does not actually provide.

Current evidence:

- `fpga-build.sh` sets `MAKE_CORES=1` by default.
- `fpga-build.sh` preflight requires `fpga/library/lib_src/my_cores_build_src`.
- that directory is not in the repo.
- `fpga/library/lib_src/make_cores.tcl` is only a placeholder.
- `docs/handoffs/20260406_fpga-build-preflight-gap.md` already documents this contradiction clearly.

Operational consequence:

- a clean FPGA build from the default command path is not currently trustworthy,
- future operators will not know whether they should fix the script, add a missing tree, or always use `--skip-cores`.

Recommended fix:

1. Make the default build path match the real repo state.
2. Prefer `MAKE_CORES=0` by default unless a real custom-core requirement reappears.
3. Update the docs so the default supported build command is truthful.

### 2. FPGA deploy verification probes the wrong address

The block design, server code, and MMIO docs all use `0x40000000`, but `fpga-deploy.sh` still performs its optional `devmem` verification at `0x42000000`.

Current evidence:

- `fpga/source/system_design_bd_rp125_14/system.tcl` assigns `0x40000000`.
- `server/memory_map.h` uses `ADS1278_MMIO_BASE 0x40000000u`.
- `docs/feats/fpga-build-and-deploy.md` already calls out the `0x42000000` mismatch.
- `fpga-deploy.sh` still probes `0x42000000`.

Operational consequence:

- a deploy may succeed while the verification message is misleading,
- operators can waste time debugging the wrong thing after programming the FPGA.

Recommended fix:

1. Change the deploy verification address to `0x40000000`.
2. Re-test the script against a real board.
3. Update the related docs at the same time.

### 3. The docs do not yet tell one clean current-state story

The detailed server and client docs are mostly consistent with the code, but some FPGA docs and several handoffs still claim `server/` or `client/` do not exist.

Current evidence:

- `docs/feats/fpga.md` still says there is no in-tree `server/` or `client/`.
- `docs/feats/fpga-register-map.md` and `docs/feats/server-protocol.md` still use "future server" or "future client" language.
- `docs/handoffs/20260406_next-development-steps.md` and `docs/handoffs/20260407_python-client-implementation.md` are now stale about repo state.

Operational consequence:

- new contributors can follow the wrong docs,
- the repo does not currently present a clean "here is what exists today" operational narrative.

Recommended fix:

1. Update `docs/feats/fpga.md` to reflect that `server/` and `client/` now exist.
2. Remove or rewrite "future server" and "future client" wording where the software is now implemented.
3. Add one short current-state note in the stale handoffs, or leave them alone but make sure the feature docs clearly supersede them.

### 4. No recorded clean end-to-end hardware validation yet

This is the biggest real ops gap. The repo documents intent and partial validation well, but not a known-good full chain on real hardware.

Unknowns still needing proof on a real board:

- clean FPGA build with the documented toolchain,
- deploy and program success,
- MMIO accessibility at `0x40000000` after programming,
- server startup on the board,
- client connection and state updates,
- acquisition enable or disable behavior,
- stable channel ordering,
- expected effect of `EXTCLK_DIV`,
- expected effect of `SYNC`,
- understandable overflow behavior,
- real electrical viability of the Red Pitaya GPIO-to-ADS1278EVM `EXTCLK` path.

Operational consequence:

- the repo is ready for controlled bring-up work,
- it is not yet ready to be called an established operations baseline.

### 5. Minor quality and UX cleanup remains

These are not primary blockers, but they are worth fixing once the hardware path is proven:

- `client/ads1278_client/main_window.py` allows divider values below the server minimum of `3`, so users can trigger avoidable `ERROR` responses.
- the root `README.md` uses `kSa/s` wording for `EXTCLK` where the examples table uses frequency units, which is easy to misread.
- there is still drift between current feature docs and older handoffs.

## What was tried and what failed

### Verified successfully in this audit

- local server unit tests and local server build passed,
- local client test suite passed,
- code review of the three layers showed the expected protocol and MMIO alignment.

### Not completed here

- no FPGA build execution,
- no cross-build execution on this host,
- no board deployment,
- no hardware acquisition run.

### Previously recorded failures or gaps that still matter

- `docs/handoffs/20260406_fpga-build-preflight-gap.md` documents the default FPGA build preflight contradiction,
- `docs/handoffs/20260407_python-client-implementation.md` records that earlier host-side cross-build verification for the server was not completed because the cross compiler and Docker path were unavailable on that host.

Those earlier environment-specific failures do not block the next ops-readiness session, but they are reminders that the "documented path" still needs one clean, repeatable proof run.

## Recommended order of work

### 1. Close the FPGA build-script contradiction

Goal: make the default build path match the repo as checked in.

Tasks:

- update `fpga-build.sh` so default behavior does not require missing custom-core sources,
- keep any custom-core path opt-in only,
- update `docs/feats/fpga-build-and-deploy.md`,
- update `docs/feats/fpga.md` if needed.

### 2. Fix deploy verification and confirm the real MMIO base

Goal: make deploy feedback trustworthy.

Tasks:

- change the `devmem` verification in `fpga-deploy.sh` from `0x42000000` to `0x40000000`,
- verify that the MMIO base still matches `fpga/source/system_design_bd_rp125_14/system.tcl`,
- confirm the docs and script all agree afterward.

### 3. Produce one known-good FPGA build result

Goal: prove the repo can generate the expected bitstream outputs.

Tasks:

- run the supported `rp125_14` build flow,
- record the Vivado version that actually works,
- confirm output artifact names and locations,
- record any required flags,
- update docs if the observed behavior differs from the current feature doc.

### 4. Run first full hardware bring-up and record results

Goal: convert the project from "implemented on paper and in code" to "observed working on hardware."

Tasks:

- deploy the bitstream to a Red Pitaya,
- verify FPGA manager state and MMIO accessibility,
- deploy the server binary,
- run `ads1278-server` on the board,
- connect the Python client,
- verify initial `SAMPLE`, `Enable`, `Disable`, `SYNC`, and divider changes,
- confirm channel ordering and overflow behavior,
- document the actual wiring and operator steps that worked.

### 5. Validate the boot-time service path

Goal: confirm the systemd startup story is real, not just scripted.

Tasks:

- use `systemd-service-deploy.sh` on a real board after the manual path is proven,
- confirm the service loads the bitstream and starts the server on boot,
- confirm the board comes back reachable and the client can reconnect after reboot,
- document any boot timing or dependency quirks.

### 6. Clean up the docs to reflect the current repo

Goal: give future operators one consistent set of docs.

Tasks:

- update `docs/feats/fpga.md`,
- update stale wording in `docs/feats/fpga-register-map.md` and `docs/feats/server-protocol.md`,
- consider a short top-level status note in `README.md`,
- keep old handoffs as historical records, but do not let them be the primary current-state docs.

## Constraints

- `README.md` is the end-state source of truth for architecture and intent.
- `.reference/` is read-only.
- Do not reopen the server protocol unless code and docs are updated together.
- Keep `rp125_14` as the supported board target unless there is a deliberate scope change.
- Prefer implementation-truthful docs over speculative or future-facing wording.

## Success criteria

- `./fpga-build.sh --target rp125_14` works from the default repo state, or the documented supported command is explicit and validated.
- `fpga-deploy.sh` verifies the correct MMIO base and no longer points operators at the wrong address.
- one known-good bitstream build and deploy path is recorded.
- the server runs on a Red Pitaya against the actual FPGA image.
- the client connects to the real server and exercises the documented command set successfully.
- the wiring and observed ADS1278EVM behavior are recorded in docs.
- the main feature docs reflect the current repo truthfully.
- the repo can support repeatable lab bring-up without relying on tribal knowledge.

## Key files

| Area | File |
|------|------|
| End-state architecture | `README.md` |
| FPGA build script | `fpga-build.sh` |
| FPGA deploy script | `fpga-deploy.sh` |
| FPGA build doc | `docs/feats/fpga-build-and-deploy.md` |
| FPGA feature hub | `docs/feats/fpga.md` |
| FPGA register map | `docs/feats/fpga-register-map.md` |
| Block-design address map | `fpga/source/system_design_bd_rp125_14/system.tcl` |
| FPGA wiring constraints | `fpga/source/cons_rp125_14/ports.xdc` |
| Server MMIO contract | `docs/feats/server-mmio-contract.md` |
| Server protocol doc | `docs/feats/server-protocol.md` |
| Server MMIO base | `server/memory_map.h` |
| Server deploy script | `server-deploy.sh` |
| Boot-time service deploy | `systemd-service-deploy.sh` |
| Client feature doc | `docs/feats/client.md` |
| Client UI | `client/ads1278_client/main_window.py` |
| Prior FPGA build gap handoff | `docs/handoffs/20260406_fpga-build-preflight-gap.md` |
| Prior stale planning handoff | `docs/handoffs/20260406_next-development-steps.md` |
| Prior client planning handoff | `docs/handoffs/20260407_python-client-implementation.md` |

## References

- `README.md`
- `docs/feats/fpga.md`
- `docs/feats/fpga-build-and-deploy.md`
- `docs/feats/fpga-register-map.md`
- `docs/feats/server-mmio-contract.md`
- `docs/feats/server-protocol.md`
- `docs/feats/server.md`
- `docs/feats/client.md`
- `docs/handoffs/20260406_fpga-build-preflight-gap.md`
- `docs/handoffs/20260406_next-development-steps.md`
- `docs/handoffs/20260407_python-client-implementation.md`
