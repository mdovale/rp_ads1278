# rp_ads1278 - pre-bring-up manual QA checklist

This handoff captures the current state of the `rp_ads1278` stack just before first physical bring-up of the ADS1278EVM on real hardware. It is intended to be a tight, operator-facing checklist for validating the FPGA, MMIO, server, client, and board-side signals before wiring the ADC board and then for performing a first controlled wired bring-up.

## Summary

- The major blocker from the previous handoff is cleared: programming the FPGA with `fpgautil -b` no longer crashes or resets the Red Pitaya Linux side.
- The current no-ADS1278 behavior appears mostly defined by the implementation:
  - the server prints only its startup line,
  - the client connects and turns green,
  - the capability line is `RP_CAP:ads1278_v1`,
  - one initial `SAMPLE` is sent,
  - `frame_cnt` stays at `0` if no acquisition frames are arriving,
  - plots stay blank or effectively static because no further `SAMPLE` messages are emitted.
- The current implementation truth is that the FPGA MMIO base is `0x42000000`, not `0x40000000`.
- The final pre-bring-up gate should be:
  - FPGA load is stable,
  - MMIO reads and writes at `0x42000000` work,
  - `EXTCLK` is visible on a scope after enable,
  - `/SYNC` pulses on command,
  - `SCLK` stays idle low when no `/DRDY` is present,
  - server/client control round-trips are correct.
- If all of the above pass, first wired bring-up is reasonable.

## Why this handoff exists

The next work step is not more software implementation. It is controlled hardware validation. Before connecting the ADS1278EVM, we want one explicit checklist that:

- confirms the current FPGA image is safe to load,
- confirms the AXI/MMIO path is alive,
- confirms the Red Pitaya output signals behave sensibly on the bench with no ADC attached,
- confirms the current server/client behavior is explained by the code,
- reduces the chance of wasting time debugging wiring when the actual issue is still board-side MMIO or clock generation.

## Current implementation truth to rely on

These are the current checked-in truths that this checklist assumes:

- FPGA register base: `0x42000000`
- Register aperture: `0x1000`
- Register offsets:
  - `STATUS` = `0x20`
  - `CTRL` = `0x24`
  - `EXTCLK_DIV` = `0x28`
- Reset defaults:
  - `CTRL = 0`
  - `EXTCLK_DIV = 625`
  - `frame_cnt = 0`
  - `overflow = 0`
- `CTRL[1]` enables acquisition and the current `EXTCLK` generator.
- `CTRL[0]` triggers a one-shot `/SYNC` pulse and auto-clears in hardware.
- `EXTCLK` frequency is `125 MHz / (2 * EXTCLK_DIV)`.
- With `EXTCLK_DIV = 625`, expected `EXTCLK` is `100 kHz`.
- `SCLK` only toggles after a falling edge on `/DRDY`; with no ADC connected, it should stay idle low.
- `/SYNC` idles high and pulses low for one `EXTCLK` period when triggered.

Important drift note:

- Some older handoffs and logs still mention `0x40000000`.
- The current live sources and current feature docs use `0x42000000`:
  - `fpga/source/system_design_bd_rp125_14/system.tcl`
  - `server/memory_map.h`
  - `docs/feats/fpga-register-map.md`
  - `docs/feats/server-mmio-contract.md`
  - `fpga-deploy.sh`

## Relevant files

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
| FPGA AXI slave reset defaults | `fpga/rtl/ads1278_axi_slave.sv` |
| EXTCLK generator behavior | `fpga/rtl/ads1278_extclk_gen.v` |
| SYNC pulse behavior | `fpga/rtl/ads1278_sync_pulse.v` |
| SPI TDM behavior | `fpga/rtl/ads1278_spi_tdm.v` |
| MMIO debug helper source | `server/rpdevmem.c` |
| Prior recovery context | `docs/handoffs/20260407_stock-fpga-recovery.md` |

## Problem and reproduction

Observed without the ADS1278 board connected:

1. Deploy the FPGA bitstream.
2. Start the ARM server on the Red Pitaya:

```bash
/usr/local/bin/ads1278-server
```

3. Start the Python client and connect to the board on port `5000`.

Observed behavior:

- server prints only:

```text
Listening on port 5000 using /dev/mem
```

- client connects successfully,
- capability line is `RP_CAP:ads1278_v1`,
- status is green,
- `SAMPLE seq` and `frame_cnt` are green and static,
- `frame_cnt` is `0`,
- `enabled` is `no`,
- `overflow` is `no`,
- `divider` reports `625`,
- plots are blank,
- attempts to change the divider appear to snap back to `625`.

Interpretation:

- The quiet server on connect is expected.
- The initial green client state is expected.
- Static zero counters and blank plots are expected if there is no advancing acquisition frame source.
- Divider snapping back to `625` is not something to assume away; it means the latest FPGA snapshot still reported `625`, so explicit read/write validation is still required before board bring-up.

## Success criteria

Do not proceed to full ADC wiring until all of the following are true:

- FPGA bitstream loads and the board remains reachable over SSH.
- FPGA manager reports `operating`.
- `devmem` reads at `0x42000000`-based offsets do not bus-fault.
- `EXTCLK_DIV` can be written and read back at least once.
- `CTRL` enable can be written and read back.
- `EXTCLK` is visible on a scope on the Red Pitaya output pin after enable.
- `/SYNC` is visible as an active-low pulse on command.
- `SCLK` remains idle low with no `/DRDY` source attached.
- The server starts and the client connects.
- Client commands produce sensible `ACK` behavior and updated fields.

## Manual QA checklist

### 0. Preconditions

- Use the current bitstream and server from this repo.
- Use the current MMIO base `0x42000000`.
- Have SSH access to the Red Pitaya as `root`.
- Have a scope probe ground lead and at least one probe channel available.
- Keep the ADS1278EVM disconnected during sections 1 through 6.

If you need to rebuild first:

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

### 1. Host-side artifact sanity

From the repo root, verify the expected artifacts exist:

```bash
ls -l fpga/work125_14/rp_ads1278.runs/impl_1/ads1278.bit.bin
ls -l build-cross/server
```

If you used the Docker build:

```bash
ls -l build-docker/server
```

Expected:

- `ads1278.bit.bin` exists.
- An ARM server binary exists under `build-cross/server` or `build-docker/server`.

### 2. Deploy FPGA and verify board stability

From the repo root:

```bash
./fpga-deploy.sh --target rp125_14 --ip <RP_IP>
```

Then verify basic SSH reachability:

```bash
ssh root@<RP_IP> 'echo alive'
```

Then verify FPGA manager state:

```bash
ssh root@<RP_IP> 'cat /sys/class/fpga_manager/fpga0/state'
```

Expected:

- deploy completes successfully,
- board does not reset,
- SSH still works,
- FPGA manager reports `operating`.

Stop here if any of these happen:

- board becomes unreachable,
- FPGA manager is not `operating`,
- `fpgautil` reports failure.

### 3. Raw MMIO sanity before enabling anything

On the Red Pitaya:

```bash
ssh root@<RP_IP>
```

Read the key registers:

```bash
devmem 0x42000020 32
devmem 0x42000024 32
devmem 0x42000028 32
```

Expected reset-state values:

- `CTRL` should be `0x00000000`
- `EXTCLK_DIV` should be `0x00000271`
- `STATUS` should have:
  - `frame_cnt = 0`
  - `overflow = 0`
  - `new_data` likely `0`

Useful decoding:

- `CTRL` bit `1` = enable
- `CTRL` bit `0` = sync trigger
- `STATUS` bit `1` = overflow
- `STATUS` bit `0` = new_data
- `STATUS[31:16]` = frame counter

If `devmem` faults or hangs here, do not continue to wiring.

### 4. MMIO write/readback validation

Still on the Red Pitaya, test `EXTCLK_DIV` readback explicitly.

Read current divider:

```bash
devmem 0x42000028 32
```

Write a new divider value that is easy to distinguish from `625`. Example: `1000`:

```bash
devmem 0x42000028 32 1000
devmem 0x42000028 32
```

Then restore default:

```bash
devmem 0x42000028 32 625
devmem 0x42000028 32
```

Expected:

- write to `1000` reads back as `0x000003e8`,
- write back to `625` reads back as `0x00000271`.

Then test enable bit readback:

```bash
devmem 0x42000024 32 0x00000002
devmem 0x42000024 32
```

Expected:

- readback is `0x00000002`.

Then disable again:

```bash
devmem 0x42000024 32 0x00000000
devmem 0x42000024 32
devmem 0x42000020 32
```

Expected:

- `CTRL` goes back to `0`,
- `frame_cnt` remains or returns to `0`,
- `overflow` is clear.

If divider or enable does not read back correctly, do not proceed to wiring. Resolve MMIO first.

### 5. Scope validation on the unconnected Red Pitaya pins

Do this with the ADS1278EVM still disconnected.

Use Red Pitaya `GND` as scope ground reference.

Probe targets from the implemented mapping:

- `exp_p_io[4]` = `EXTCLK`
- `exp_p_io[3]` = `/SYNC`
- `exp_p_io[0]` = `SCLK`

Also keep the board wiring doc open:

- `docs/feats/board-io-wiring.md`

#### 5a. Verify `EXTCLK` is off when disabled

On the board:

```bash
devmem 0x42000024 32 0x00000000
```

Expected on scope:

- `EXTCLK` held low,
- `SCLK` low,
- `/SYNC` high.

#### 5b. Verify `EXTCLK` appears when enabled

On the board:

```bash
devmem 0x42000028 32 625
devmem 0x42000024 32 0x00000002
```

Expected on scope:

- `EXTCLK` is a square wave at about `100 kHz`,
- duty cycle near 50%,
- `/SYNC` remains high unless triggered,
- `SCLK` remains low because no `/DRDY` is present.

Optional alternate divider values:

- `1000` -> about `62.5 kHz`
- `63` -> about `992 kHz`

Commands:

```bash
devmem 0x42000028 32 1000
devmem 0x42000028 32 63
devmem 0x42000028 32 625
```

Expected:

- `EXTCLK` frequency changes accordingly.

#### 5c. Verify `/SYNC` pulse

Keep acquisition disabled first:

```bash
devmem 0x42000024 32 0x00000001
```

Expected on scope:

- `/SYNC` pulses low once,
- pulse width is about one `EXTCLK` period,
- at divider `625`, pulse width should be about `10 us`.

Then test while enable is set:

```bash
devmem 0x42000024 32 0x00000002
devmem 0x42000024 32 0x00000003
```

Expected:

- `EXTCLK` continues toggling,
- `/SYNC` still pulses low once,
- `CTRL[0]` auto-clears in hardware after the write.

#### 5d. Verify `SCLK` idle behavior

With no ADC and no `/DRDY` source attached, do not expect periodic `SCLK`.

Expected on scope:

- `SCLK` stays low and quiet.

If `SCLK` is free-running with no `/DRDY`, that is unexpected and should be investigated before wiring the ADC.

### 6. Server/client validation with no ADS1278 connected

Deploy the server binary from the repo root:

```bash
./server-deploy.sh --ip <RP_IP>
```

Start the server on the Red Pitaya:

```bash
ssh root@<RP_IP> '/usr/local/bin/ads1278-server'
```

Expected server output:

```text
Listening on port 5000 using /dev/mem
```

Do not expect a new log line when the client connects successfully.

Start the client from the repo root:

```bash
.venv/bin/python client/main.py
```

In the client:

1. Enter the Red Pitaya IP.
2. Connect to port `5000`.

Expected immediately after connect:

- green connection indicator,
- capability shown as `RP_CAP:ads1278_v1`,
- `frame_cnt: 0`,
- `enabled: no`,
- `overflow: no`,
- `divider: 625`,
- blank or effectively empty plots,
- status text similar to `SAMPLE seq=0 frame_cnt=0`.

Now test GUI command round-trips.

#### 6a. Enable

In the client, press `Enable`.

Expected:

- client status changes to an `ACK`,
- `enabled` changes to `yes`,
- `divider` stays at the current value,
- `EXTCLK` appears on the scope if you are still probing it.

#### 6b. Disable

Press `Disable`.

Expected:

- `ACK`,
- `enabled` changes to `no`,
- `EXTCLK` stops.

#### 6c. Set divider

Set the divider to `1000` in the GUI and press `Set divider`.

Expected:

- client shows an `ACK`,
- `divider` label changes to `1000`,
- scope shows `EXTCLK` near `62.5 kHz` if enabled.

Then set it back to `625`.

Important interpretation:

- If the GUI snaps back to `625` immediately after setting `1000`, the FPGA snapshot still reported `625`.
- That is a real MMIO/write-readback problem, not just a cosmetic issue, because the GUI refreshes from the latest server message.

#### 6d. SYNC

Press `SYNC`.

Expected:

- client shows an `ACK`,
- `/SYNC` pulse is visible on the scope.

### 7. Go/no-go gate before wiring the ADS1278EVM

You may proceed to physical wiring only if all items below are true:

- board survives FPGA programming,
- raw `devmem` reads and writes work at `0x42000000`,
- `EXTCLK_DIV` readback works,
- enable readback works,
- `EXTCLK` is visible and follows divider changes,
- `/SYNC` pulse is visible,
- `SCLK` is not doing anything surprising without `/DRDY`,
- server/client control path works,
- there is no unexplained divider snap-back.

If any of the above fail, stop and fix that layer first.

### 8. Wiring checklist for first physical bring-up

Power down or at least avoid hot-plugging if you are not fully confident in the ground and signal integrity setup.

Before wiring:

- confirm the ADS1278EVM is configured for:
  - high-resolution mode,
  - SPI output,
  - TDM on `DOUT1`,
  - external clock input,
  - fixed channel order on `DOUT1`,
- confirm `DIN` is strapped low,
- confirm `CS` is unused and left unconnected,
- confirm all relevant digital IOs are compatible with `3.3V` CMOS levels before first power-up.

Current intended signal mapping:

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

- `EXTCLK` is the mechanically awkward connection because the ADS1278EVM expects clock at an SMA input.
- Keep that path short and well-grounded.
- If possible, verify `EXTCLK` both at the Red Pitaya source pin and at the ADS1278EVM destination before expecting real acquisition.

### 9. First powered wired bring-up

After wiring, repeat the minimal safe sequence.

#### 9a. FPGA load and raw MMIO

Repeat sections 2 through 4 first. Do not assume they still pass after wiring.

#### 9b. Scope checks with the EVM attached

Probe:

- `EXTCLK` at the EVM side if possible,
- `/DRDY_FSYNC`,
- `SCLK`,
- optionally `/SYNC`.

Expected:

- after enable, `EXTCLK` is present at the EVM,
- `/DRDY_FSYNC` should now show ADC-driven activity if the EVM is clocked and configured correctly,
- `SCLK` should now burst in response to `/DRDY` falling edges,
- `/SYNC` should still pulse on command.

#### 9c. Server/client functional check

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
3. Watch the scope and the client.

Expected:

- `frame_cnt` starts advancing,
- plots begin updating,
- channel data is no longer static zero,
- `SCLK` bursts line up with `/DRDY`,
- changing `EXTCLK_DIV` changes data rate behavior,
- `overflow` remains `no` at conservative clocking.

Recommended first divider values:

- start with `625` (`100 kHz EXTCLK`),
- if behavior is stable, optionally try `1000` and `250`,
- do not jump straight to the minimum divider during first bring-up.

### 10. Failure signatures and what they likely mean

- Board resets or SSH dies after `fpgautil`:
  - FPGA integration problem is still present.
- `devmem` at `0x42000000` bus-faults:
  - wrong design loaded, wrong MMIO base, or broken AXI path.
- `EXTCLK_DIV` always reads back `625` after writes:
  - MMIO writes are not sticking or readback is not from the intended register block.
- Enable bit does not read back:
  - same class of MMIO/control problem.
- `EXTCLK` missing after enable:
  - control write failed, wrong pin, or output path issue.
- `/SYNC` missing on command:
  - control path issue or wrong pin probe.
- `SCLK` free-runs without `/DRDY`:
  - unexpected RTL behavior or wrong probe point.
- `EXTCLK` exists on Red Pitaya but not at the EVM:
  - board-level wiring or signal integrity issue.
- `/DRDY` never toggles with the EVM attached:
  - EVM not correctly strapped, not clocked, not powered as expected, or `EXTCLK` not reaching the ADC.
- `frame_cnt` still stays at `0` with EVM attached:
  - no real completed captures; inspect `/DRDY`, `EXTCLK`, `SCLK`, and `DOUT1`.

## Recommended operator sequence

Use this order and do not skip ahead:

1. Validate FPGA load stability.
2. Validate raw MMIO at `0x42000000`.
3. Validate `EXTCLK_DIV` read/write.
4. Validate enable read/write.
5. Validate `EXTCLK`, `/SYNC`, and idle `SCLK` on the scope with no ADC attached.
6. Validate server/client behavior with no ADC attached.
7. Wire the ADS1278EVM carefully.
8. Repeat the raw MMIO and scope checks with the EVM attached.
9. Only then attempt actual acquisition and client plotting.

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
