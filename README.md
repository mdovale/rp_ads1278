# rp_ads1278

This document describes the intended **end-state** of `rp_ads1278`: a Red Pitaya–hosted SPI acquisition server streaming ADC samples from a ADS1278EVM board to a host-side Python client for live visualization and optional logging.

## Goals

- **Acquire** samples from the 8-channel **ADS1278EVM** board over the SPI interface.
- **Stream** samples off-board over the network with **low latency** and predictable throughput.
- **Visualize** the stream in real time from a cross-platform Python client.
- **Log/export** sample data for offline analysis.

## The three layers

| Directory     | Role |
|---------------|------|
| **fpga** | RTL + Vivado TCL; builds bitstreams for RedPitaya, handles acquisition over SPI and clocking of the ADS1278 |
| **server** | C program on the RedPitaya ARM (Zynq PS): maps FPGA memory, streams binary frames over TCP, runs the command protocol |
| **client** | Python GUI: decodes frames, sends commands, displays plots |


## Required signal mapping

| Function | Red Pitaya side | ADS1278EVM side | Notes |
| --- | --- | --- | --- |
| **SPI clock** | E1 `exp_p_io[0]` (G17) | `SCLK` | Output |
| **SPI data in** | E1 `exp_p_io[1]` (H16) | `DOUT1` | Input, TDM stream CH1..CH8 |
| **ADC Clock** | E1 `exp_p_io[4]` (L14) | `EXTCLK` | Output, clock ADC conversion |
| **Ground** | RP `GND` | EVM `GND` | Common reference |
| **DRDY event** | E1 `exp_p_io[2]` (J18) | /`DRDY_FSYNC` | Input, falling-edge trigger |
| **SYNC control** | E1 `exp_p_io[3]` (K17) | /`SYNC` | Output, active-low reset pulse |

## DIN and CS handling

- **DIN**: DIN strapped to GND on EVM (we are not daisy-chaining 1+ devices).
- **CS**: ADS1278 TDM readout does not require chip select. RP CS can be left unconnected.

## ADS1278EVM strap/jumper intent

- High-resolution mode
- SPI output
- TDM on DOUT1
- Fixed-position channel ordering (CH1..CH8 each frame)
- External clock (CMOS clock signal provided by the RedPitaya)

## RP FPGA expansion pin assignment

All signals are driven/sampled by FPGA PL logic via the E1 expansion connector.
No Linux sysfs GPIOs are used for high-speed acquisition.

| Role | E1 Pin | Package Pin | Direction |
| --- | --- | --- | --- |
| SCLK | `exp_p_io[0]` | G17 | Output |
| MISO | `exp_p_io[1]` | H16 | Input |
| DRDY | `exp_p_io[2]` | J18 | Input |
| SYNC | `exp_p_io[3]` | K17 | Output |
| EXTCLK | `exp_p_io[4]` | L14 | Output |

## Clocking and data rate

The data rate of the ADS1278EVM in high-resolution mode is `EXTCLK`/512, where `EXTCLK` is anywhere between `100 kHz` and `27 MHz`.

Some examples:

| `EXTCLK` | Data rate |
| --- | --- |
| 100 kHz | 195.31 Hz |
| 500 kHz | 976.6 Hz |
| 1 MHz | 1,953.1 Hz |
| 10 MHz | 19,531.3 Hz |
| 27 MHz | 52,734.4 Hz |

The `EXTCLK` input on the ADS1278EVM is an SMA connector. It is awkward to connect an RP GPIO pin to an SMA connector, but we will try it.
