# rp_ads1278 — Detailed Implementation Plan

This document provides a systematic, agent-friendly plan to implement `rp_ads1278` by leveraging `.reference` (the rpll project) and filling in ADS1278-specific gaps. The plan is structured so that multiple agents can work in parallel or sequentially, with clear copy/adapt instructions and explicit gaps to fill.

**Source of truth**: `README.md` describes the end-state. `.reference` is read-only; copy and adapt into `fpga/`, `server/`, and `client/`.

---

## Architecture Overview

| Layer   | Role | Reference Source | rp_ads1278 Target |
|---------|------|------------------|------------------|
| **fpga**   | RTL + Vivado TCL; SPI acquisition, clocking, AXI memory map | `.reference/rpll_fpga/` | `fpga/` |
| **server** | C program on RedPitaya ARM; maps FPGA memory, streams TCP frames | `.reference/rpll_server/esw/` | `server/` |
| **client** | Python GUI; decodes frames, sends commands, plots | `.reference/rpll_client/` | `client/` |

---

## Phase 1: Project Scaffolding & Build Scripts

**Objective**: Establish top-level structure and build/deploy scripts that reference `fpga/`, `server/`, and `client/`.

### 1.1 Directories

- Ensure `fpga/`, `server/`, and `client/` exist (they already have `.gitkeep`).

### 1.2 Copy and Adapt Build Scripts

| Script | Source | Adaptations |
|--------|--------|-------------|
| `fpga-build.sh` | `.reference/fpga-build.sh` | Set `FPGA_DIR="${FPGA_DIR:-$SCRIPT_DIR/fpga}"`. Remove `--variant` handling; use single bitstream name `ads1278`. Update `preflight_check` paths: `fpga/source/cfg_rp125_14/ads1278.tcl`, `fpga/source/system_design_bd_rp125_14/system.tcl`. Update `find_bitstream_path` to look for `ads1278.bit` / `ads1278.bit.bin`. |
| `fpga-deploy.sh` | `.reference/fpga-deploy.sh` | Set `FPGA_DIR="${FPGA_DIR:-$SCRIPT_DIR/fpga}"`. Update `detect_default_bitstream` to look in `fpga/work125_14/rp_ads1278.runs/impl_1/` for `ads1278.bit.bin`. |
| `server-build-cross.sh` | `.reference/server-build-cross.sh` | Set `SERVER_DIR="${SERVER_DIR:-$SCRIPT_DIR/server}"`. Remove `--variant` handling. |
| `server-build-docker.sh` | `.reference/server-build-docker.sh` | Same `SERVER_DIR` and remove `--variant`. |
| `server-deploy.sh` | `.reference/server-deploy.sh` | Update `auto_detect_binary` to check `$SCRIPT_DIR/build-cross/server`, `$SCRIPT_DIR/build-docker/server`, `$SCRIPT_DIR/server/server`. |
| `systemd-service-deploy.sh` | `.reference/systemd-service-deploy.sh` | Adapt binary path and service name to `ads1278-server`. |

### 1.3 Board Support

- **Target**: rp125_14 only (Zynq-7010, Vivado 2017.2).
- Remove rp250_12 from `get_board_work_dir`.

---

## Phase 2: FPGA Layer (`fpga/`)

**Objective**: Create synthesizable logic for ADS1278 SPI acquisition, EXTCLK generation, DRDY/SYNC GPIO, and AXI memory map.

### 2.1 Copy Build Infrastructure

| Item | Source | Destination | Adaptations |
|------|--------|-------------|-------------|
| `regenerate_project_and_bd.tcl` | `.reference/rpll_fpga/` | `fpga/` | Change `rpll.tcl` → `ads1278.tcl` in `board_cfg_script`. Change project/work dir names from `rpll` to `rp_ads1278` where applicable. |
| `tcl/board_config_rp125_14.tcl` | `.reference/rpll_fpga/tcl/` | `fpga/tcl/` | Set `board_cfg_script` to `source/cfg_rp125_14/ads1278.tcl`, `board_bd_script` to `source/system_design_bd_rp125_14/system.tcl`. |
| `tcl/create_project_common.tcl` | `.reference/rpll_fpga/tcl/` | `fpga/tcl/` | Copy as-is; minimal or no changes. |
| `source/cfg_rp125_14/` | `.reference/rpll_fpga/source/cfg_rp125_14/` | `fpga/source/cfg_rp125_14/` | Create `ads1278.tcl` (adapted from `rpll.tcl`). |
| `source/cons_rp125_14/` | `.reference/rpll_fpga/source/cons_rp125_14/` | `fpga/source/cons_rp125_14/` | Copy `clocks.xdc`, then adapt `ports.xdc` (see 2.5). |
| `library/` | `.reference/rpll_fpga/library/` | `fpga/library/` | Copy `lib_src/my_cores_build_src/` (axi_cfg_register, axis_red_pitaya_adc, axis_constant). For ads1278, we may not need ADC/DAC; keep only what is used. |

### 2.2 Minimal Block Design (Gap to Fill)

The rpll block design is complex (PLLs, servos, scope, DAC, PWM). For rp_ads1278 we need a **minimal** design:

1. **Retain**:
   - Zynq Processing System 7 (PS7)
   - AXI interconnect(s)
   - Clock and reset (FCLK_CLK0, proc_sys_reset)
   - Expansion connector pins for SPI, GPIO

2. **Remove**:
   - axis_red_pitaya_adc, axis_red_pitaya_dac (unless needed for something else)
   - PLLs, Servos, scope_MHz, PWM_IF, DAC_IF
   - laser_lock, all_pipes, cfg_regs_distributor (rpll-specific)

3. **Add** (new RTL + BD integration):
   - **ads1278_acq** (or similar) hierarchical block containing:
     - SPI TDM receiver (reads 8×24-bit from DOUT1 on SCLK edges, triggered by DRDY)
     - EXTCLK generator (configurable divider from 125 MHz, output 100 kHz–27 MHz)
     - SYNC pulse generator (AXI-triggerable one-shot)
     - AXI-lite registers for: 8×24-bit channel data, status, control

**Strategy**: Start from a minimal RedPitaya block design (e.g. PS7 + GPIO + one AXI peripheral). Reference `.reference/rpll_fpga/source/system_design_bd_rp125_14/system.tcl` for PS7 setup and address segments, but build a new `system.tcl` from scratch or by stripping rpll down to PS7 + interconnect + new ads1278 block.

### 2.3 RTL Modules to Create (Gaps)

| Module | Purpose | Reference / Notes |
|--------|---------|--------------------|
| `ads1278_spi_tdm.v` | SPI slave-style receiver: on falling edge of DRDY, clock in 8×24 bits from MISO (DOUT1) using SCLK. Output 8×24-bit register bank. | ADS1278 datasheet: TDM order CH1..CH8, MSB first. Can adapt `.reference/rpll_fpga/source/rtl/spi_master.v` concepts but ADS1278 is **slave**; we generate SCLK and read MISO. |
| `ads1278_extclk_gen.v` | Divides 125 MHz to produce EXTCLK (100 kHz–27 MHz). AXI register sets divider. | Use counter or Xilinx Clocking Wizard. |
| `ads1278_sync_pulse.v` | One-shot: write 1 to AXI register → drive SYNC low for N cycles, then high. | Simple FSM. |
| `ads1278_acq_top.v` | Top-level: instantiates spi_tdm, extclk_gen, sync_pulse; AXI-lite interface for registers. | Wraps all; connects to block design. |

**ADS1278 SPI timing** (high-res, TDM, DOUT1):

- Data rate = EXTCLK/512.
- After DRDY falls, data is output on DOUT1, MSB first, 24 bits per channel, CH1..CH8.
- SCLK must be provided by FPGA; sample MISO on appropriate edge (datasheet specifies setup/hold).
- Total bits per frame: 8×24 = 192 bits.

### 2.4 AXI Memory Map (Gap)

Define addresses for rp125_14 (0x4xxxxxxx range typical for PL peripherals):

| Register | Offset | Width | R/W | Description |
|----------|--------|-------|-----|-------------|
| CH1..CH8 | 0x00–0x1C | 32 each | R | 24-bit channel data (upper bits reserved) |
| STATUS   | 0x20    | 32     | R | DRDY seen, overflow, etc. |
| CTRL     | 0x24    | 32     | R/W | SYNC trigger (write 1), EXTCLK divider |
| EXTCLK_DIV | 0x28  | 32     | R/W | Divider for 125 MHz → EXTCLK |

Exact addresses must match `server/memory_map.h`.

### 2.5 Pin Constraints (`ports.xdc`)

Per README signal mapping:

| Function | Red Pitaya | ADS1278EVM | XDC Notes |
|----------|------------|------------|-----------|
| SPI SCK  | E2 Pin 5   | SCLK       | Use expansion connector. RedPitaya E2: check pinout for Pin 5. |
| SPI MISO | E2 Pin 4  | DOUT1      | Input from ADC. |
| EXTCLK   | GPIO out   | EXTCLK     | RP GPIO (TBD sysfs number) → physical pin. |
| DRDY     | GPIO in    | /DRDY_FSYNC| Falling edge = data ready. |
| SYNC     | GPIO out   | /SYNC      | Active-low pulse. |

**Reference**: `.reference/rpll_fpga/source/cons_rp125_14/ports.xdc` uses `exp_p_tri_*`, `exp_n_tri_*` for expansion. RedPitaya E1 pinout must be consulted for exact package pins. The README specifies E1 expansion connector for all.

**Action**: Create `fpga/sdc/red_pitaya.xdc` with:
- SPI SCK, MISO, DRDY, SYNC, EXTCLK on correct expansion pins

### 2.6 Project Config (`ads1278.tcl`)

Create `fpga/source/cfg_rp125_14/ads1278.tcl` from `rpll.tcl`:

- Replace all `rpll` references with `rp_ads1278`.
- Replace source file list: remove rpll RTL (laser_lock, all_pipes, etc.); add `ads1278_acq_top.v`, `ads1278_spi_tdm.v`, `ads1278_extclk_gen.v`, `ads1278_sync_pulse.v`.
- Set top to `system_wrapper` (from block design).
- Keep constraints: `clocks.xdc`, `ports.xdc`.

---

## Phase 3: Server Layer (`server/`)

**Objective**: C program that maps FPGA memory, reads 8-channel data, streams frames over TCP, handles commands.

### 3.1 Copy Base Server

| File | Source | Action |
|------|--------|--------|
| `server.c` | `.reference/rpll_server/esw/` | Copy; heavily modify (see 3.3). |
| `server.h` | `.reference/rpll_server/esw/` | Copy; strip rpll-specific declarations. |
| `memory_map.c` | `.reference/rpll_server/esw/` | Copy; rewrite for ads1278 map. |
| `memory_map.h` | `.reference/rpll_server/esw/` | Copy; rewrite for ads1278 map. |
| `rpdevmem.c` | `.reference/rpll_server/esw/` | Copy as-is (generic /dev/mem mapping). |
| `cmd_parse.c`, `cmd_parse.h` | `.reference/rpll_server/esw/` | Copy; simplify for ads1278 commands. |
| `red_pitaya_identify.c`, `red_pitaya_identify.h` | `.reference/rpll_server/esw/` | Copy as-is. |
| `Makefile` | `.reference/rpll_server/esw/` | Copy; remove fft_peak, real_fft_1024, rand; add only needed objects. |

**Remove**: `fft_peak.c`, `fft_peak.h`, `real_fft_1024.c`, `real_fft_1024.h`, `rand.c`, `rand.h`.

### 3.2 Protocol (`rp_protocol.h`)

Create `server/rp_protocol.h` (or copy and modify):

```c
#define RP_DEFAULT_PORT 1001
#define RP_FRAME_SIZE_DOUBLES 9   /* counter + 8 channels */
#define RP_FRAME_SIZE_BYTES (RP_FRAME_SIZE_DOUBLES * 8)
#define RP_CAP_PREFIX "RP_CAP:"
#define RP_CAP_ADS1278 "ads1278"
#define RP_CMD_ADDR_MAX 8
```

Frame layout: `[counter, ch1, ch2, ch3, ch4, ch5, ch6, ch7, ch8]` (9 doubles minimum).

### 3.3 Memory Map (`memory_map.h` / `memory_map.c`)

Define the AXI peripheral base in the `memory_map` enum (so it gets mapped to `/dev/mem`):

```c
enum memory_map {
    ADS1278_ACQ_BASE,  /* Single AXI peripheral base for ads1278 */
    MEMORY_MAP_COUNT
};
```

Then define the register byte offsets within that mapped peripheral:

```c
#define ADS1278_CH1_OFFSET       0x00
#define ADS1278_STATUS_OFFSET    0x20
#define ADS1278_CTRL_OFFSET      0x24
#define ADS1278_EXTCLK_DIV_OFFSET 0x28
```

Addresses in `MEMORY_MAP_ADDRESS` must match FPGA AXI base addresses. Use `red_pitaya_identify` to select RP_125_14 addresses.

### 3.4 Acquisition Loop (`server.c`)

Replace rpll loop with:

1. **Poll or interrupt**: Poll `ADS1278_STATUS_OFFSET` for data-ready flag, or use GPIO UIO/irq for DRDY (optional).
2. **Read channels**: Read 8×32-bit starting at `ADS1278_CH1_OFFSET`.
3. **Convert to doubles**: 24-bit signed → double (scale as needed, e.g. ±FS/2^23).
4. **Build frame**: `[counter, ch1, ..., ch8]`.
5. **Send**: `send(sock_client, frame, RP_FRAME_SIZE_BYTES, MSG_NOSIGNAL)`.
6. **Commands**: `start_measuring` (addr 0), `SYNC` trigger (addr 1), `EXTCLK_DIV` (addr 2), etc.

Remove: `add_fft_to_frame`, `add_pll_to_frame`, `add_servo_to_frame`, `add_white_noise`, `pll_logger_*`, `trigger_scope_read`.

### 3.5 Command Parsing

Simplify `process_command` to handle:

- Addr 0: start/stop measuring
- Addr 1: SYNC pulse (write 1)
- Addr 2: EXTCLK divider value

---

## Phase 4: Client Layer (`client/`)

**Objective**: Python GUI to connect, visualize 8 channels, send commands, log data.

### 4.1 Copy Base Client

| Item | Source | Action |
|------|--------|--------|
| `main.py` | `.reference/rpll_client/` | Copy; adapt imports and entry. |
| `rp_protocol.py` | `.reference/rpll_client/` | Copy; update constants to match server. |
| `acquire.py` | `.reference/rpll_client/` | Copy; adapt frame schema and corruption check. |
| `frame_schema.py` | `.reference/rpll_client/` | **Rewrite** for 8-channel + counter. |
| `data_models.py` | `.reference/rpll_client/` | Adapt for time-series channels. |
| `setup.py` | `.reference/rpll_client/` | Copy; change package name to `rp_ads1278_client` or similar. |
| `global_params.py` | `.reference/rpll_client/` | Copy; simplify. |
| `layout.py`, `gui.py`, `widgets.py` | `.reference/rpll_client/` | Copy; heavily modify (see 4.3). |
| `config.json` | `.reference/rpll_client/` | Copy; adapt. |
| `tests/` | `.reference/rpll_client/tests/` | Copy; update tests for new schema. |

### 4.2 Frame Schema (`frame_schema.py`)

```python
FRAME_SIZE_DOUBLES = 9  # counter + 8 channels
FRAME_SIZE_BYTES = FRAME_SIZE_DOUBLES * 8
FRAME_COUNTER = 0
CH1, CH2, CH3, CH4, CH5, CH6, CH7, CH8 = 1, 2, 3, 4, 5, 6, 7, 8
```

Remove FFT-related constants. Update `check_frame_corruption` or replace with a simple sanity check (e.g. counter monotonic, channels in expected range).

### 4.3 GUI Redesign

**Remove**: FFT spectrum plots, PLL I/Q, servo sliders, laser lock controls.

**Add**:

- **8-channel strip chart**: One plot with 8 traces. Use `pyqtgraph.PlotWidget` / `PlotDataItem`.
- **Controls**: Connect/Disconnect, Start/Stop, EXTCLK frequency (or divider), SYNC button.
- **Status**: Connection state, frame rate, last counter.

Reference `gui.py` and `layout.py` structure.

### 4.4 Data Logging (`acquire.py`)

- Ensure `RPConnection` and `read_frame` work with new `FRAME_SIZE_BYTES`.
- Logging: write 8-channel + timestamp to CSV. Column headers: `cnt, ch1, ch2, ..., ch8`.
- Header should contain the sampling frequency (to generate a timebase from `cnt`) and "t0" timestamp using client OS time.

### 4.5 Connect Sequence

- Read capability line `RP_CAP:ads1278`.
- Send `start_measuring` (addr 0, value 1) instead of rpll-specific commands.
- Remove or adapt rpll init commands (0x01000001, 0x00000001) to ads1278 equivalents.

---

## Phase 5: Integration & Verification

### 5.1 Build Order

1. **FPGA**: `./fpga-build.sh --target rp125_14` (after Phase 2 complete).
2. **Server**: `./server-build-cross.sh`.
3. **Client**: `cd client && pip install -e .`

### 5.2 Deploy

- `./fpga-deploy.sh --target rp125_14 --ip <RP_IP>`
- `./server-deploy.sh --ip <RP_IP>`

### 5.3 Hardware Setup

- Wire ADS1278EVM per README table.
- Fill GPIO table in README with actual sysfs numbers once known.
- EVM straps: high-res, SPI, TDM DOUT1, external clock.

### 5.4 Test

- Run server on RedPitaya.
- Run client: `python main.py`, connect, start.
- Verify 8 channels update in real time.
- Test SYNC, EXTCLK change.
- Test logging to file.

---

## Reference File Map (Quick Lookup)

| Need | Location in .reference |
|------|-------------------------|
| FPGA build script | `fpga-build.sh` |
| FPGA block design (PS7, interconnects) | `rpll_fpga/source/system_design_bd_rp125_14/system.tcl` |
| Board config | `rpll_fpga/tcl/board_config_rp125_14.tcl` |
| Project TCL | `rpll_fpga/source/cfg_rp125_14/rpll.tcl` |
| Port constraints | `rpll_fpga/source/cons_rp125_14/ports.xdc` |
| SPI master (adapt for ADS1278) | `rpll_fpga/source/rtl/spi_master.v` |
| Server main loop | `rpll_server/esw/server.c` |
| Memory map | `rpll_server/esw/memory_map.h` |
| Protocol | `rpll_server/rp_protocol.h` |
| Client frame schema | `rpll_client/frame_schema.py` |
| Client acquire | `rpll_client/acquire.py` |
| Client GUI | `rpll_client/gui.py`, `layout.py` |

---

## GPIO Assignment (TBD)

README specifies:

| Role | E1 Pin / Package Pin | Connection |
|------|------------|------------|
| DRDY | TBD | EVM /DRDY_FSYNC → RP input |
| SYNC | TBD | RP output → EVM /SYNC |
| CLK  | TBD | RP output → EVM EXTCLK |
| SCLK | TBD | RP output -> EVM SCLK |
| MISO | TBD | EVM DOUT1 -> RP input |

**Note**: All signals are generated in FPGA and routed to the E1 expansion connector. No Linux GPIOs are used for high-speed acquisition.

---

## Checklist for Agents

- [x] Phase 1: Build scripts copied and adapted
- [x] Phase 2.1: FPGA build infra copied
- [x] Phase 2.2: Minimal block design created
- [x] Phase 2.3: ads1278 RTL modules implemented
- [x] Phase 2.4: AXI memory map defined
- [x] Phase 2.5: ports.xdc with SPI and GPIO pins
- [x] Phase 2.6: ads1278.tcl project config
- [ ] Phase 3.1–3.5: Server adapted
- [ ] Phase 4.1–4.5: Client adapted
- [ ] Phase 5: Integration tested
