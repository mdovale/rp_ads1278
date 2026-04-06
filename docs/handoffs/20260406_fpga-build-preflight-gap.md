# rp_ads1278 - FPGA Build Preflight Gap

This handoff covers the current mismatch in the FPGA build flow where `fpga-build.sh` expects a custom-core source directory that does not exist, even though the checked-in `make_cores.tcl` explicitly says no custom IP cores are needed.

## Summary

The current build flow has an internal contradiction:

- `fpga-build.sh` defaults to custom-core generation
- `fpga-build.sh` preflight requires `fpga/library/lib_src/my_cores_build_src`
- `fpga/library/lib_src/make_cores.tcl` says no custom IP cores are needed for `rp_ads1278`
- the `my_cores_build_src` directory is not present in the repo

As a result, the default build path can fail before Vivado even starts, for a dependency the project does not currently use.

## Problem

The relevant logic today is:

- `fpga-build.sh` sets `MAKE_CORES=1` by default
- `preflight_check()` errors out if `fpga/library/lib_src/my_cores_build_src` does not exist
- the checked-in `make_cores.tcl` is only a no-op placeholder

That makes the default build behavior misleading and brittle:

- it implies custom IP generation is part of the normal path
- it blocks a clean build on a directory the repo intentionally does not contain
- it forces future developers to guess whether the build script or the repo layout is wrong

## Reproduction

Expected failure path from the current repo state:

1. Run `./fpga-build.sh --target rp125_14`
2. Reach `preflight_check()`
3. Fail on missing `fpga/library/lib_src/my_cores_build_src`

Relevant current files:

- `fpga-build.sh`
- `fpga/library/lib_src/make_cores.tcl`
- `docs/feats/fpga-build-and-deploy.md`

## Recommended Fix

Preferred approach: make the normal build path match the actual project state.

### Recommendation

1. Change the default build behavior so `rp_ads1278` does **not** run custom-core generation unless explicitly requested.
2. Remove the unconditional preflight requirement for `fpga/library/lib_src/my_cores_build_src`.
3. Keep `--make-cores` as an opt-in path for future use, but let `make_cores.tcl` own any real prerequisites if that path is reintroduced later.
4. Update the FPGA build docs so they state clearly that the current repo has no required custom-core generation step.

### Why this is the best fix

- It matches the current checked-in implementation truthfully.
- It removes an unnecessary blocker from the default build path.
- It avoids adding placeholder directories just to satisfy a stale assumption.
- It preserves room for future custom-core generation without baking in today’s contradiction.

## Concrete Implementation Plan

### Code changes

In `fpga-build.sh`:

- Change the default from `MAKE_CORES=1` to `MAKE_CORES=0`
- Update help text so the default behavior is clear
- In `preflight_check()`, stop requiring `fpga/library/lib_src/my_cores_build_src` as part of the normal build path
- If `--make-cores` is used, require only what is actually needed by the real `make_cores.tcl` implementation

Optional refinement:

- Keep the `make_cores.tcl` existence check only when `--make-cores` is explicitly enabled
- Print a short message that custom-core generation is skipped by default for `rp_ads1278`

### Documentation changes

Update:

- `docs/feats/fpga-build-and-deploy.md`
- possibly `docs/feats/fpga.md`

to reflect:

- no custom IP generation is currently required
- the normal build path should work without `my_cores_build_src`
- `--make-cores` is reserved for future use or explicit experimentation

## Alternatives Considered

### Alternative 1: Add an empty `my_cores_build_src` directory

Not recommended.

Why not:

- It preserves the wrong contract
- It suggests required IP sources exist when they do not
- It hides the real issue instead of fixing it

### Alternative 2: Keep default `MAKE_CORES=1`, but just remove the directory preflight check

Acceptable, but weaker than the preferred approach.

Why weaker:

- The default build still claims to generate custom IP even though nothing is generated
- The user experience remains slightly misleading

### Alternative 3: Reintroduce a full custom-core tree from a reference project

Not recommended unless a real FPGA dependency is rediscovered.

Why not:

- It adds noise and maintenance burden
- It is unsupported by the current `rp_ads1278` RTL/TCL set

## Constraints

- `README.md` is the end-state source of truth, but this issue is about current build behavior, so implementation-truthful repo state matters most.
- `.reference/` is read-only.
- The fix should reduce confusion, not add compatibility shims unless they are truly needed.
- Any build-flow change should keep `rp125_14` as the only supported board target.

## Success Criteria

- `./fpga-build.sh --target rp125_14` no longer fails on missing `my_cores_build_src` in the default repo state
- the build script’s default behavior matches the actual repo layout
- docs state clearly whether custom-core generation is required, optional, or unused
- future developers do not need to infer intent from contradictory script behavior

## References

- `fpga-build.sh`
- `fpga/library/lib_src/make_cores.tcl`
- `docs/feats/fpga-build-and-deploy.md`
- `docs/feats/fpga.md`
- `docs/handoffs/20260406_next-development-steps.md`
