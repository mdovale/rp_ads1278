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
| **SPI clock** | E2 `SPI SCK` (Pin 5) | `SCLK` |  |
| **SPI data in** | E2 `SPI MISO` (Pin 4) | `DOUT1` | TDM stream CH1..CH8 |
| **ADC Clock** | RP GPIO output (line `TBD`) | `EXTCLK` | Clock ADC conversion |
| **Ground** | RP `GND` | EVM `GND` | Common reference |
| **DRDY event** | RP GPIO input (line `TBD`) | /`DRDY_FSYNC` | Falling-edge trigger when data is ready |
| **SYNC control** | RP GPIO output (line `TBD`) | /`SYNC` | Active-low pulse for resetting ADS1278 filters |

## DIN and CS handling

- **DIN**: DIN strapped to GND on EVM (we are not daisy-chaining 1+ devices).
- **CS**: ADS1278 TDM readout does not require chip select. RP CS can be left unconnected.

## ADS1278EVM strap/jumper intent

- High-resolution mode
- SPI output
- TDM on DOUT1
- Fixed-position channel ordering (CH1..CH8 each frame)
- External clock (CMOS clock signal provided by the RedPitaya)

## RP GPIO assignment record (fill on target system)

Fill these with the exact GPIO mapping from your RP OS image.

| Role | sysfs GPIO number | Connection |
| --- | --- | --- |
| DRDY | `TBD` | EVM /`DRDY_FSYNC` -> RP input |
| SYNC | `TBD` | RP output -> EVM /`SYNC` |
| CLK | `TBD` | RP output -> EVM /`EXTCLK` |

## Clocking and data rate

The data rate of the ADS1278EVM in high-resolution mode is `EXTCLK`/512, where `EXTCLK` is anywhere between 100 and 27000 kSa/s.

Some examples:

| `EXTCLK` | Data rate |
| --- | --- |
| 100 kHz | 195.31 Hz |
| 500 kHz | 976.6 Hz |
| 1 MHz | 1,953.1 Hz |
| 10 MHz | 19,531.3 Hz |
| 27 MHz | 52,734.4 Hz |

The `EXTCLK` in the ADS1278EVM boards is an SMA connector. It is ackward to connect an RP GPIO pin to an SMA connector, but we will try it.
