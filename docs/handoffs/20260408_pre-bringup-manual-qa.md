# rp_ads1278 - pre-bring-up manual QA checklist

This is a bench-facing runbook for validating the current `rp_ads1278` FPGA, MMIO path, server, client, and Red Pitaya output pins before first physical bring-up of the ADS1278EVM.

Use it in two stages:

1. First, validate the Red Pitaya with the ADS1278EVM disconnected.
2. Only then wire the ADC board and repeat the key checks under load.

---

## Summary

- The big recovery milestone is complete: loading the FPGA bitstream with `fpgautil -b` no longer crashes or resets Red Pitaya Linux.
- The current no-ADC behavior is mostly explained by the code:
  - the server prints only its startup line,
  - the client connects and turns green,
  - the capability line is `RP_CAP:ads1278_v1`,
  - one initial `SAMPLE` is sent,
  - `frame_cnt` stays at `0` if no acquisition frames are arriving,
  - plots stay blank or effectively static because no further `SAMPLE` messages are emitted.
- The current implementation truth is that the FPGA MMIO base is `0x42000000`.
- The key pre-bring-up gate is:
  - FPGA loads safely,
  - MMIO reads and writes work,
  - `EXTCLK` is visible on the scope,
  - `/SYNC` pulses on command,
  - `SCLK` stays idle low with no `/DRDY`,
  - server/client control round-trips work.

If those pass, first wired bring-up is reasonable.

---

## Current Implementation Truth

Assume the following unless the repo changes:

- MMIO base: `0x42000000`
- MMIO aperture: `0x1000`
- key register offsets:
  - `STATUS` = `0x20`
  - `CTRL` = `0x24`
  - `EXTCLK_DIV` = `0x28`
- reset defaults:
  - `CTRL = 0`
  - `EXTCLK_DIV = 625`
  - `frame_cnt = 0`
  - `overflow = 0`
- `CTRL[1]` enables acquisition and `EXTCLK`
- `CTRL[0]` triggers one `/SYNC` pulse
- `EXTCLK` frequency is `125 MHz / (2 * EXTCLK_DIV)`
- `EXTCLK_DIV = 625` should give about `100 kHz`
- `SCLK` should not toggle until a falling edge on `/DRDY`
- `/SYNC` idles high and pulses low

Important drift note:

- older docs and handoffs may still mention `0x40000000`
- the live sources now use `0x42000000`

---

## How To Use `devmem`

Stock Red Pitaya images often omit BusyBox `devmem`. This checklist uses the name **`devmem`** for the **`ads1278-rpdevmem`** helper (same binary as deployed by `server-deploy.sh`). Install once on the board:

```bash
ln -sf /usr/local/bin/ads1278-rpdevmem /usr/local/bin/devmem
```

Or run **`/usr/local/bin/ads1278-rpdevmem`** everywhere this doc says **`devmem`**.

Mental model:

- all access is **32-bit** MMIO into the live FPGA register block (base `0x42000000`, aperture `0x1000`)
- commands use **register offsets** from that base, **not** full physical addresses (using `0x42000028` as an offset will fault)
- reads are safe for this checklist
- writes take effect immediately

Basic forms:

```bash
devmem read <offset>
devmem write <offset> <value>
devmem snapshot
```

Examples (offsets match `server/memory_map.h`):

```bash
devmem read 0x28
devmem write 0x28 625
devmem write 0x28 0x271
devmem write 0x24 0x00000002
```

What those mean:

- `devmem read 0x28`
  - read the 32-bit `EXTCLK_DIV` register (physical `0x42000028`)
- `devmem write 0x28 625`
  - write decimal `625`
- `devmem write 0x28 0x271`
  - write the same value in hex
- `devmem write 0x24 0x00000002`
  - set `CTRL[1] = 1`, which enables acquisition and `EXTCLK`

Typical **read** output:

```text
0x00000271
```

That means the 32-bit register currently contains hex `0x271`, which is decimal `625`.

Typical **write** output:

```text
wrote 0x000003e8 to 0x00000028
```

Offset cheat sheet (physical = `0x42000000` + offset):

| Register | Offset |
|----------|--------|
| `CH1`..`CH8` | `0x00`..`0x1c` (step `0x04`) |
| `STATUS` | `0x20` |
| `CTRL` | `0x24` |
| `EXTCLK_DIV` | `0x28` |

### Quick decoding guide

#### `CTRL`

- bit `1` = enable
- bit `0` = sync trigger

Useful values:

- `0x00000000` = disabled
- `0x00000002` = enabled
- `0x00000001` = one-shot sync trigger while otherwise disabled
- `0x00000003` = enabled plus sync trigger in the same write

#### `EXTCLK_DIV`

- raw value is the divider
- `0x00000271` = `625`
- `0x000003e8` = `1000`

#### `STATUS`

- bit `0` = `new_data`
- bit `1` = `overflow`
- bits `[31:16]` = `frame_cnt`

Examples:

- `0x00000000`
  - `frame_cnt = 0`
  - `overflow = no`
  - `new_data = no`
- `0x00030002`
  - `frame_cnt = 3`
  - `overflow = yes`
  - `new_data = no`
- `0x00030003`
  - `frame_cnt = 3`
  - `overflow = yes`
  - `new_data = yes`

Important note:

- `new_data` is pulse-like in the current RTL
- you may miss it in polling
- for this checklist, `frame_cnt` is the more useful signal

### Practical rule

If you write a register and then immediately read it back:

- if the value matches, the MMIO path is probably working
- if it snaps back to the old value, the write did not stick or you are not talking to the expected register block
- if `devmem` faults, segfaults, or hangs, stop and fix MMIO first (a segfault often means a bad offset, not a missing FPGA)

---

## Before You Start

- Keep the ADS1278EVM disconnected for the first half of this checklist.
- Have SSH access to the Red Pitaya as `root`.
- After deploying the server artifacts, install the MMIO helper symlink once (see [How To Use `devmem`](#how-to-use-devmem)) so commands in this doc paste as-is.
- Have a scope probe ground clip and at least one probe channel ready.
- Use Red Pitaya `GND` as the scope reference.

If you need fresh software artifacts first:

```bash
./server-build-cross.sh --rebuild
```

Or:

```bash
./server-build-docker.sh --rebuild
```

Client launch from repo root:

```bash
.venv/bin/python client/main.py
```

---

## Quick Go / No-Go Gate

Do not wire the ADS1278EVM yet unless all of these are true:

- FPGA bitstream loads and the board stays reachable
- FPGA manager reports `operating`
- `devmem read 0x20` (or `devmem snapshot`) does not bus-fault or segfault
- `EXTCLK_DIV` can be written and read back
- `CTRL` enable can be written and read back
- `EXTCLK` appears on the scope after enable
- `/SYNC` pulses on command
- `SCLK` stays idle low with no `/DRDY`
- server/client commands produce sensible `ACK` behavior

---

## Stage 1: Validate With No ADS1278 Connected

### 1. Host-side artifact sanity

From the repo root:

```bash
ls -l fpga/work125_14/rp_ads1278.runs/impl_1/ads1278.bit.bin
ls -l build-cross/server build-cross/rpdevmem
```

If you used the Docker build:

```bash
ls -l build-docker/server build-docker/rpdevmem
```

Expected:

- `ads1278.bit.bin` exists
- ARM `server` and `rpdevmem` binaries exist under `build-cross/` or `build-docker/`

---

### 2. Deploy FPGA and verify board stability

From the repo root:

```bash
./fpga-deploy.sh --target rp125_14 --ip <RP_IP>
```

Then verify SSH still works:

```bash
ssh root@<RP_IP> 'echo alive'
```

Then verify FPGA manager state:

```bash
ssh root@<RP_IP> 'cat /sys/class/fpga_manager/fpga0/state'
```

Expected:

- deploy completes successfully
- board does not reset
- SSH still works
- FPGA manager reports `operating`

Stop if:

- board becomes unreachable
- FPGA manager is not `operating`
- `fpgautil` reports failure

---

### 3. Raw MMIO sanity before enabling anything

SSH into the board:

```bash
ssh root@<RP_IP>
```

Read the key registers:

```bash
devmem read 0x20
devmem read 0x24
devmem read 0x28
```

Expected reset-state values:

- `CTRL` should read `0x00000000`
- `EXTCLK_DIV` should read `0x00000271`
- `STATUS` should indicate:
  - `frame_cnt = 0`
  - `overflow = 0`
  - `new_data` probably `0`

What this proves:

- the AXI register block is reachable
- the current address map is probably correct
- reset defaults match the RTL and docs

Stop if:

- any read bus-faults
- `devmem` hangs
- values are wildly inconsistent with reset state

---

### 4. MMIO write / readback validation

This is the most important early software-side check.

#### 4a. Test `EXTCLK_DIV`

Read current divider:

```bash
devmem read 0x28
```

Write `1000` and read it back:

```bash
devmem write 0x28 1000
devmem read 0x28
```

Expected:

- readback should be `0x000003e8`

Restore default:

```bash
devmem write 0x28 625
devmem read 0x28
```

Expected:

- readback should be `0x00000271`

#### 4b. Test enable bit

Enable:

```bash
devmem write 0x24 0x00000002
devmem read 0x24
```

Expected:

- readback should be `0x00000002`

Disable again:

```bash
devmem write 0x24 0x00000000
devmem read 0x24
devmem read 0x20
```

Expected:

- `CTRL` goes back to `0`
- `frame_cnt` remains or returns to `0`
- `overflow` is clear

What this proves:

- writes are sticking
- the server and client should later be able to control the FPGA through the same registers

Stop if:

- divider or enable does not read back correctly
- values immediately snap back without explanation

---

### 5. Scope validation on the unconnected Red Pitaya pins

Do this with the ADS1278EVM still disconnected.

Probe these Red Pitaya signals:

- `exp_p_io[4]` = `EXTCLK`
- `exp_p_io[3]` = `/SYNC`
- `exp_p_io[0]` = `SCLK`

Keep `docs/feats/board-io-wiring.md` open while probing.

---

#### 5a. Verify `EXTCLK` is off when disabled

On the Red Pitaya:

```bash
devmem write 0x24 0x00000000
```

Expected on the scope:

- `EXTCLK` held low
- `SCLK` low
- `/SYNC` high

---

#### 5b. Verify `EXTCLK` appears when enabled

On the Red Pitaya:

```bash
devmem write 0x28 625
devmem write 0x24 0x00000002
```

Expected on the scope:

- `EXTCLK` is a square wave near `100 kHz`
- duty cycle is near 50%
- `/SYNC` stays high unless triggered
- `SCLK` remains low because there is no `/DRDY`

Optional divider experiments:

- `1000` -> about `62.5 kHz`
- `63` -> about `992 kHz`

Commands:

```bash
devmem write 0x28 1000
devmem write 0x28 63
devmem write 0x28 625
```

Expected:

- the `EXTCLK` frequency changes accordingly

---

#### 5c. Verify `/SYNC` pulse

First, test while disabled:

```bash
devmem write 0x24 0x00000001
```

Expected on the scope:

- `/SYNC` pulses low once
- pulse width is about one `EXTCLK` period
- at divider `625`, pulse width should be about `10 us`

Then test while enabled:

```bash
devmem write 0x24 0x00000002
devmem write 0x24 0x00000003
```

Expected:

- `EXTCLK` keeps toggling
- `/SYNC` still pulses low once
- the sync-trigger bit auto-clears in hardware

---

#### 5d. Verify `SCLK` idle behavior

With no ADC and no `/DRDY` source:

- do not expect periodic `SCLK`

Expected on the scope:

- `SCLK` stays low and quiet

If `SCLK` free-runs with no `/DRDY`, stop and investigate before wiring the ADC.

---

### 6. Server / client validation with no ADS1278 connected

Deploy the server binary from the repo root:

```bash
./server-deploy.sh --ip <RP_IP>
```

Start the server:

```bash
ssh root@<RP_IP> '/usr/local/bin/ads1278-server'
```

Expected server output:

```text
Listening on port 5000 using /dev/mem
```

Do not expect a new log line when the client connects successfully.

Now start the client from the repo root:

```bash
.venv/bin/python client/main.py
```

In the client:

1. Enter the Red Pitaya IP.
2. Connect to port `5000`.

Expected immediately after connect:

- green connection indicator
- capability shown as `RP_CAP:ads1278_v1`
- `frame_cnt: 0`
- `enabled: no`
- `overflow: no`
- `divider: 625`
- blank or effectively empty plots
- status text similar to `SAMPLE seq=0 frame_cnt=0`

Interpretation:

- this quiet, static behavior is normal with no ADC frames arriving

---

#### 6a. Enable

Press `Enable` in the client.

Expected:

- client status changes to an `ACK`
- `enabled` changes to `yes`
- `divider` stays at the current value
- `EXTCLK` appears on the scope if you are still probing it

---

#### 6b. Disable

Press `Disable`.

Expected:

- `ACK`
- `enabled` changes to `no`
- `EXTCLK` stops

---

#### 6c. Set divider

Set the divider to `1000` and press `Set divider`.

Expected:

- client shows an `ACK`
- `divider` label changes to `1000`
- if enabled, the scope shows `EXTCLK` near `62.5 kHz`

Then set it back to `625`.

Important interpretation:

- if the GUI snaps back to `625`, the latest FPGA snapshot still reported `625`
- that is a real MMIO/readback problem, not just a cosmetic GUI issue

---

#### 6d. SYNC

Press `SYNC`.

Expected:

- client shows an `ACK`
- `/SYNC` pulse is visible on the scope

---

## Stage 2: Wire The ADS1278EVM

Do this only after Stage 1 passes.

Power down or at least avoid hot-plugging if you are not fully confident in the setup.

Before wiring, confirm the ADS1278EVM is configured for:

- high-resolution mode
- SPI output
- TDM on `DOUT1`
- external clock input
- fixed channel ordering on `DOUT1`

Also confirm:

- `DIN` is strapped low
- `CS` is unused and left unconnected
- the relevant digital IOs are compatible with `3.3V` CMOS levels

Current intended mapping:

- Red Pitaya `exp_p_io[0]` -> ADS1278EVM `SCLK`
- Red Pitaya `exp_p_io[1]` <- ADS1278EVM `DOUT1`
- Red Pitaya `exp_p_io[2]` <- ADS1278EVM `/DRDY_FSYNC`
- Red Pitaya `exp_p_io[3]` -> ADS1278EVM `/SYNC`
- Red Pitaya `exp_p_io[4]` -> ADS1278EVM `EXTCLK`
- Red Pitaya `GND` <-> ADS1278EVM `GND`

Recommended staged wiring order:

1. `GND`
2. `EXTCLK`
3. `/SYNC`
4. `SCLK`
5. `/DRDY_FSYNC`
6. `DOUT1`

Specific caution:

- `EXTCLK` is the awkward path because the EVM expects clock at an SMA input
- keep that path short and well grounded
- if possible, verify `EXTCLK` both at the Red Pitaya source and at the EVM destination

---

## Stage 3: First Powered Wired Bring-Up

### 1. Repeat the core MMIO checks

Do not assume the wiring changed nothing.

Repeat:

- FPGA load
- `STATUS` / `CTRL` / `EXTCLK_DIV` reads
- divider write/readback
- enable write/readback

---

### 2. Repeat the scope checks with the EVM attached

Probe:

- `EXTCLK` at the EVM side if possible
- `/DRDY_FSYNC`
- `SCLK`
- optionally `/SYNC`

Expected:

- after enable, `EXTCLK` is present at the EVM
- `/DRDY_FSYNC` should now show ADC-driven activity if the EVM is clocked and strapped correctly
- `SCLK` should now burst in response to `/DRDY` falling edges
- `/SYNC` should still pulse on command

---

### 3. Repeat the server / client functional check

Run the server:

```bash
ssh root@<RP_IP> '/usr/local/bin/ads1278-server'
```

Run the client:

```bash
.venv/bin/python client/main.py
```

Then:

1. Connect.
2. Press `Enable`.
3. Watch the scope and the client together.

Expected:

- `frame_cnt` starts advancing
- plots begin updating
- channel data is no longer static zero
- `SCLK` bursts line up with `/DRDY`
- changing `EXTCLK_DIV` changes acquisition behavior
- `overflow` remains `no` at conservative clocking

Recommended first divider values:

- start with `625` (`100 kHz EXTCLK`)
- if stable, optionally try `1000` and `250`
- do not jump straight to the minimum divider during first bring-up

---

## Failure Signatures

Use this as a quick diagnosis map.

- Board resets or SSH dies after `fpgautil`
  - the FPGA integration problem is not fully fixed

- `devmem read 0x20` (or `devmem snapshot`) bus-faults
  - wrong design loaded, wrong address, or broken AXI path

- `EXTCLK_DIV` always reads back `625`
  - MMIO writes are not sticking or readback is not from the intended register block

- Enable bit does not read back
  - same class of MMIO/control problem

- `EXTCLK` missing after enable
  - control write failed, wrong pin, or output path problem

- `/SYNC` missing on command
  - control path issue or wrong probe point

- `SCLK` free-runs without `/DRDY`
  - unexpected RTL behavior or wrong probe point

- `EXTCLK` exists on Red Pitaya but not at the EVM
  - board-level wiring or signal integrity issue

- `/DRDY` never toggles with the EVM attached
  - the EVM is not correctly strapped, not correctly clocked, or not receiving `EXTCLK`

- `frame_cnt` stays at `0` with the EVM attached
  - no completed captures; inspect `/DRDY`, `EXTCLK`, `SCLK`, and `DOUT1`

---

## Recommended Operator Sequence

Use this exact order:

1. Validate FPGA load stability.
2. Validate raw MMIO at `0x42000000`.
3. Validate `EXTCLK_DIV` read/write.
4. Validate enable read/write.
5. Validate `EXTCLK`, `/SYNC`, and idle `SCLK` on the scope with no ADC attached.
6. Validate server/client behavior with no ADC attached.
7. Wire the ADS1278EVM carefully.
8. Repeat the raw MMIO and scope checks with the EVM attached.
9. Only then attempt live acquisition and client plotting.

---

## Relevant Files

| Area | File |
|------|------|
| End-state architecture and wiring intent | `README.md` |
| Current board wiring contract | `docs/feats/board-io-wiring.md` |
| Current FPGA register map | `docs/feats/fpga-register-map.md` |
| Current server MMIO contract | `docs/feats/server-mmio-contract.md` |
| Current server behavior | `docs/feats/server.md` |
| FPGA deploy script | `fpga-deploy.sh` |
| Server deploy script | `server-deploy.sh` |
| Current MMIO base | `server/memory_map.h` |
| MMIO peek/poke helper (`ads1278-rpdevmem`) | `server/rpdevmem.c` |
| FPGA AXI slave reset defaults | `fpga/rtl/ads1278_axi_slave.sv` |
| EXTCLK generator behavior | `fpga/rtl/ads1278_extclk_gen.v` |
| SYNC pulse behavior | `fpga/rtl/ads1278_sync_pulse.v` |
| SPI TDM behavior | `fpga/rtl/ads1278_spi_tdm.v` |
| Prior recovery context | `docs/handoffs/20260407_stock-fpga-recovery.md` |

---

## References

- `README.md`
- `docs/feats/board-io-wiring.md`
- `docs/feats/fpga-register-map.md`
- `docs/feats/server-mmio-contract.md`
- `docs/feats/server.md`
- `docs/feats/fpga-build-and-deploy.md`
- `docs/handoffs/20260407_stock-fpga-recovery.md`
- `fpga/source/system_design_bd_rp125_14/system.tcl`
- `server/memory_map.h`
- `fpga/rtl/ads1278_axi_slave.sv`
- `fpga/rtl/ads1278_extclk_gen.v`
- `fpga/rtl/ads1278_sync_pulse.v`
- `fpga/rtl/ads1278_spi_tdm.v`
