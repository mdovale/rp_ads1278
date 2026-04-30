# rp_ads1278 - connection loss triage and decision tree

This handoff captures the current failure where acquisition runs for a while and then the client disconnects, sometimes followed by partial or full board unreachability (`ssh` and `ping` unstable). It is written to guide the next troubleshooting session toward a root cause with minimal ambiguity.

## Summary

- Observed field behavior:
  - instability is more likely at faster rates (`EXTCLK_DIV` around `125`, `375`, `500`)
  - with `EXTCLK_DIV=625`, failure can still occur after 5 to 10 minutes
  - at failure, client loses server connection
  - in some events the board stops responding over network; in others it stays partially reachable
  - after failure, `EXTCLK_DIV` has sometimes been observed as `0`
  - after reconnect, recent shell commands from just before incident can be missing from history
  - SSH banner can report stale `Last login` date despite regular daily logins
  - reprogramming FPGA restores normal behavior
- Current code strongly suggests `EXTCLK_DIV=0` is not a normal command-path state.
- Highest-probability class is still platform or integration instability (PS reboot or PL contract loss), not a client GUI bug.
- Next session should focus on collecting high-value evidence at the exact failure moment before reprogramming FPGA.

## Why this handoff exists

Recent operator reports indicate repeated long-run disconnects and occasional board unreachability under acquisition load. The immediate question is whether the issue is:

- ADC and FPGA capture timing,
- AXI and MMIO path integrity,
- server runtime behavior, or
- board-level reset or crash behavior.

This handoff converts those uncertainties into an explicit decision tree and minimal command set for diagnosing the next failure.

## Problem statement and reproduction

### Reported symptom

- Acquisition starts and works.
- At higher sample rates (lower divider), failure happens sooner.
- At conservative rate (`EXTCLK_DIV=625`), failure can still happen after several minutes.
- One specific stop point observed: frame count around `45946`.
- After failure, readback of `EXTCLK_DIV` can appear as `0`.
- After reconnect, shell history may "rewind" to older commands and omit recent entries.
- SSH banner has shown stale `Last login` date while operator has logged in on later days.
- Re-burning the FPGA bitstream recovers the system.

### Practical reproduction recipe

1. Program known-good bitstream and confirm board is reachable.
2. Start server and client.
3. Enable acquisition.
4. Run with one of:
  - aggressive divider: `125` or `375`
  - moderate divider: `500`
  - baseline divider: `625` for long soak
5. Keep session running until disconnect or board instability appears.

## Current implementation truth relevant to diagnosis

- MMIO base is `0x42000000` with `0x1000` aperture.
- Key offsets:
  - `STATUS` = `0x20`
  - `CTRL` = `0x24`
  - `EXTCLK_DIV` = `0x28`
- FPGA AXI slave reset defaults:
  - `CTRL = 0`
  - `EXTCLK_DIV = 625`
- Server command validation requires `SET_EXTCLK_DIV >= 3`.

Important implication:

- The normal server/client command path should not set divider to `0`.
- Observing `0` usually implies wrong or stale MMIO view, post-reset state mismatch, unloaded or replaced PL image, or broken AXI reachability.

## What was analyzed in this session

- Server command validation logic (`server/cmd_parse.c`)
- Server MMIO read and write path (`server/memory_map.c`, `server/rpdevmem.c`, `server/server.c`)
- FPGA AXI register behavior and reset defaults (`fpga/rtl/ads1278_axi_slave.sv`)
- Acquisition and clocking path (`fpga/rtl/ads1278_acq_top.v`, `fpga/rtl/ads1278_spi_tdm.v`, `fpga/rtl/ads1278_extclk_gen.v`)
- Existing runbooks and recovery notes:
  - `docs/handoffs/20260408_pre-bringup-manual-qa.md`
  - `docs/handoffs/20260407_stock-fpga-recovery.md`
  - `docs/feats/fpga-register-map.md`
  - `docs/feats/server-mmio-contract.md`
- Block-design address mapping (`fpga/source/system_design_bd_rp125_14/system.tcl`)

## New high-value clues from latest report

- During incidents that look like "ARM crash", shell command history can lose recent commands entered just before failure.
- On reconnect, SSH banner has shown `Last login` as an older date (`Mon Apr 27`) despite daily use.

Interpretation:

- This pattern is consistent with abrupt reset or crash behavior where user-space sessions terminate without normal shell history flush.
- Stale `Last login` also raises concern about write persistence, read-only remount, or unclean reset timing around login-accounting writes.
- These clues increase confidence that at least some failures are PS/runtime stability events, not only server socket-path failures.

## Suspects (ranked)

### 1) PS reboot, hang, or abrupt reset under load (highest likelihood)

Why it fits:

- Sometimes `ssh` and `ping` fail during incident.
- Operator reports behavior that looks like board-level availability loss, not just TCP session reset.
- Recent shell history lines can disappear after reconnect, matching unclean session termination.
- SSH `Last login` appearing stale is consistent with runtime instability or persistence anomalies during incidents.
- Reprogramming FPGA appears to restore expected operation quickly.

What would confirm:

- uptime reset or boot counter change after incident
- kernel logs showing watchdog, panic, OOM, lockup, or network driver collapse
- reboot records (`who -b`, `last reboot`) inconsistent with expected continuous runtime

### 2) Runtime persistence or filesystem state degradation after board event

Why it fits:

- Stale login records suggest writes may not always persist as expected.
- Abrupt resets can leave shell history and login-accounting files without latest updates.

What would confirm:

- root filesystem remounted read-only (`mount` shows `ro`)
- kernel logs with storage or filesystem errors (`ext4`, `mmc`, I/O errors, remount events)
- `/var/log/lastlog` or shell history timestamps not advancing after normal logins

### 3) PL image or PS-PL contract lost after board event

Why it fits:

- `EXTCLK_DIV` readback as `0` conflicts with expected reset default (`625`) and command guards.
- Readback zero is consistent with talking to wrong MMIO context or absent expected register behavior.

What would confirm:

- FPGA manager state not `operating`
- readback of multiple control registers nonsensical or all zeros
- mismatch between expected and actual programmed bitstream state

### 4) AXI/MMIO path instability while Linux remains up

Why it fits:

- Client disconnect can occur even if board stays partially reachable.
- Server depends on coherent and repeated MMIO snapshots.

What would confirm:

- board reachable over SSH, but `rpdevmem snapshot` fails, hangs, or returns unstable values
- server process alive but repeatedly failing or disconnecting clients

### 5) Acquisition timing stress at low divider exposing integration weakness

Why it fits:

- faster rates fail sooner.
- long-run stress can trigger latent timing or metastability weaknesses that are not obvious at startup.

What would confirm:

- failure rate strongly correlates with divider
- overflow and frame behavior degrade before disconnect
- no PS reboot, but capture state degrades or stalls

### 6) pure client-side bug (low likelihood)

Why it is less likely:

- reports include board network instability and MMIO anomalies.
- those are outside client GUI responsibility.

## Decision tree for next failure

Run this in order at the moment of failure, before re-burning FPGA.

### Step 0: preserve evidence first

- Do not reboot.
- Do not reprogram FPGA yet.
- Record wall-clock time and last visible frame count.

### Step 1: board reachability

- If both `ping` and `ssh` fail:
  - suspect board crash, reset, or severe network path failure
  - go to Step 2 once access returns
- If `ssh` works:
  - immediately continue to Step 2

### Step 2: check if PS rebooted

On board:

```bash
uptime
cat /proc/uptime
```

- If uptime unexpectedly low:
  - treat as PS reboot event
  - inspect previous boot logs in Step 3
- If uptime continuous:
  - likely no full reboot, continue to Step 2A

### Step 2A: check persistence and login-accounting clues

On board:

```bash
who -b
last reboot | head
ls -l /var/log/lastlog /root/.bash_history
mount | grep " on / "
```

- If reboot records changed unexpectedly:
  - classify as PS reboot/reset event even if previous shell context was ambiguous
- If root filesystem is read-only (`ro`) or file timestamps are not advancing:
  - classify as runtime persistence/filesystem fault class
- If checks look normal:
  - continue to Step 3

### Step 3: kernel and reboot clues

On board:

```bash
journalctl -b -1 -k | egrep -i "watchdog|panic|oom|reset|hang|lockup"
journalctl -b -k | egrep -i "fpga|axi|zynq|net|eth|watchdog|panic|oom|ext4|mmc|i/o error|read-only|remount"
```

- If crash signatures appear:
  - prioritize PS stability path (power, thermal, kernel, watchdog, drivers)
- If no signatures:
  - continue to PL and MMIO checks

### Step 4: FPGA manager state

On board:

```bash
cat /sys/class/fpga_manager/fpga0/state
```

- If not `operating`:
  - PL is not in expected state; classify as PL lifecycle failure
- If `operating`:
  - continue to MMIO coherence checks

### Step 5: MMIO coherence snapshot

On board:

```bash
/usr/local/bin/ads1278-rpdevmem read 0x24
/usr/local/bin/ads1278-rpdevmem read 0x28
/usr/local/bin/ads1278-rpdevmem read 0x20
/usr/local/bin/ads1278-rpdevmem snapshot
```

- If reads fail or hang:
  - classify as MMIO path failure
- If reads succeed but values are impossible or all zeros:
  - suspect wrong PL image, stale mapping, or AXI contract break
- If values are sensible:
  - continue to server process checks

### Step 6: server process and socket state

On board:

```bash
ps aux | egrep "ads1278-server|PID"
ss -ltnp | egrep ":5000|ads1278-server"
```

- If server died:
  - capture exit context and restart behavior
- If server alive but no listener:
  - server path bug or startup failure
- If listener alive but client disconnected:
  - inspect transport and MMIO sampling behavior under load

### Step 7: controlled poke test

Only if MMIO reads are alive:

```bash
/usr/local/bin/ads1278-rpdevmem write 0x28 625
/usr/local/bin/ads1278-rpdevmem read 0x28
/usr/local/bin/ads1278-rpdevmem write 0x24 0x00000002
/usr/local/bin/ads1278-rpdevmem read 0x24
```

- If write-readback works:
  - control path still alive; investigate server lifecycle and high-rate capture path
- If write-readback does not stick:
  - strong AXI or PL contract issue

## Minimum evidence bundle to collect each incident

- timestamp of failure
- divider value in use
- last frame count visible in client
- uptime and `/proc/uptime`
- `who -b` and `last reboot | head`
- root filesystem mount mode (`rw` vs `ro`)
- timestamps of `/var/log/lastlog` and active account shell history file
- FPGA manager state
- `rpdevmem` reads of `0x20`, `0x24`, `0x28`
- `rpdevmem snapshot` output
- server process presence and listening socket state
- relevant `journalctl` snippets from current and previous boot

If this bundle is collected for 2 to 3 incidents across different divider values, root cause discrimination should become much faster.

## Constraints and guardrails

- Keep MMIO addressing convention consistent with current project tooling.
- Do not assume `EXTCLK_DIV=0` came from client command path; validate with command guards first.
- Avoid immediate reprogramming when incident occurs; evidence is lost otherwise.
- Keep current protocol and client unchanged during triage unless a direct defect is proven.

## Success criteria for next session

- Capture one complete incident with evidence from all decision-tree checkpoints.
- Determine whether failure class is:
  - PS reboot or crash,
  - runtime persistence/filesystem fault,
  - PL image or lifecycle loss,
  - AXI and MMIO path fault with PS alive,
  - or server-only runtime failure.
- Produce one concrete fix hypothesis tied to captured evidence, not just symptoms.

## Candidate follow-up actions once class is confirmed

- If PS reboot or crash:
  - harden board runtime (watchdog, thermal, power, kernel-service interactions).
- If runtime persistence/filesystem fault:
  - inspect storage health and ext4/mmc logs, verify rootfs mount mode, and validate login-accounting/history file updates during normal sessions.
- If PL lifecycle loss:
  - verify boot-time and runtime FPGA manager workflow, service ordering, and image persistence policy.
- If AXI and MMIO instability:
  - stress-test MMIO path with standalone `rpdevmem` loop, isolate from network stack.
- If server-only:
  - add runtime logging around snapshot errors, disconnect reasons, and command handling cadence.

## Key files


| Area                             | File                                               |
| -------------------------------- | -------------------------------------------------- |
| Server command validation        | `server/cmd_parse.c`                               |
| Server MMIO access               | `server/memory_map.c`                              |
| Server runtime loop              | `server/server.c`                                  |
| MMIO helper                      | `server/rpdevmem.c`                                |
| MMIO constants                   | `server/memory_map.h`                              |
| AXI slave defaults and registers | `fpga/rtl/ads1278_axi_slave.sv`                    |
| Acquisition top                  | `fpga/rtl/ads1278_acq_top.v`                       |
| SPI capture FSM                  | `fpga/rtl/ads1278_spi_tdm.v`                       |
| EXTCLK generator                 | `fpga/rtl/ads1278_extclk_gen.v`                    |
| BD address map                   | `fpga/source/system_design_bd_rp125_14/system.tcl` |
| Manual QA runbook                | `docs/handoffs/20260408_pre-bringup-manual-qa.md`  |
| Stock recovery context           | `docs/handoffs/20260407_stock-fpga-recovery.md`    |


## References

- `docs/handoffs/20260408_pre-bringup-manual-qa.md`
- `docs/handoffs/20260407_stock-fpga-recovery.md`
- `docs/feats/fpga-register-map.md`
- `docs/feats/server-mmio-contract.md`
- `fpga/source/system_design_bd_rp125_14/system.tcl`

