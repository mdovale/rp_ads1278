# ADS1278 SPI configuration and timing

This note summarizes how to interface to the **TI ADS1278** using its **SPI-compatible, read-only serial interface**, focusing on pin configuration, clocking edges, and setup/hold timing. 

---

## 1) Selecting SPI mode (FORMAT[2:0])

The ADS1278 uses **FORMAT[2:0]** pins to select the serial protocol and data-output format:

- **SPI + TDM (dynamic position):** `FORMAT[2:0] = 000`
- **SPI + TDM (fixed position):** `FORMAT[2:0] = 001`
- **SPI + Discrete outputs (parallel DOUT[8:1]):** `FORMAT[2:0] = 010`

In **SPI**, the shared pin **DRDY/FSYNC** functions as **DRDY** (data-ready output). SCLK is an input. 

> Note: **SPI mode is limited to fCLK ≤ 27 MHz**. For operation above 27 MHz (High-Speed mode only), use Frame-Sync format instead. 

---

## 2) SPI transaction overview

### DRDY behavior
- **DRDY goes low** when a new conversion result is ready to be read out.
- DRDY **returns high on the falling edge of the first SCLK** after a read begins.
- If you do not read (SCLK held low), DRDY can pulse high just before the next data are ready; the new data are loaded within one CLK cycle before DRDY goes low again. 

### Data shifting direction and bit order
- Data are **shifted out MSB-first**.
- DOUT updates on **falling edges of SCLK** (the converter shifts data out on the falling edge). 

**Practical implication for the MCU/FPGA:**
- **Sample DOUT on SCLK rising edges** (since the ADC changes DOUT on falling edges). This corresponds to the common SPI convention “data changes on falling, captured on rising”.

---

## 3) Clock-edge timing: what to sample and when

### DOUT timing relative to SCLK (SPI)
- **DOUT changes after the falling edge of SCLK**.
- The *previous* DOUT bit remains valid for at least the DOUT hold time after the falling edge:
  - `tDOHD`: SCLK falling edge → old DOUT invalid (hold time)
- The *new* DOUT bit becomes valid after the falling edge propagation delay:
  - `tDOPD`: SCLK falling edge → new DOUT valid (prop delay) 

**Therefore:** sampling on the **rising edge** gives you (roughly) half a clock period for propagation + margin, provided you meet the minimum SCLK high/low pulse widths.

### DIN timing (for daisy-chain only)
DIN is only used when daisy-chaining multiple devices; otherwise tie DIN low. Data are shifted into DIN on the **falling edge of SCLK**. 

To meet input timing at the ADS1278:
- `tDIST`: **DIN setup** — new DIN valid → falling edge of SCLK
- `tDIHD`: **DIN hold** — old DIN valid after → falling edge of SCLK 

---

## 4) SCLK frequency and pulse-width constraints

From the SPI timing spec (IOVDD-dependent):
- `tSCLK` (SCLK period) must be ≥ 1·tCLK (so fSCLK ≤ fCLK).
- `tSPW` (SCLK high/low pulse width) must be ≥ 0.4·tCLK.
- For best performance, use fSCLK/fCLK ratios of **1, 1/2, 1/4, 1/8, …**. 

SCLK may be **free-running** or **stopped between conversions** in SPI mode. 

---

## 5) Relationship between DRDY and the first SCLK

After DRDY falls (data ready):
- Wait at least `tDS`: **DRDY falling edge → first SCLK rising edge** (minimum is 1·tCLK).
- When a read begins, DRDY returns high after `tSD`: **SCLK falling edge → DRDY rising edge**. 

**Rule of thumb:** start clocking **no earlier than one fCLK period** after DRDY falls.

---

## 6) Synchronization using SYNC (optional but recommended for multi-device)

To synchronize conversion timing across channels/devices, pulse **SYNC low** then return it high:
- `tSYN`: SYNC low pulse width ≥ **1 CLK period**
- SYNC must meet setup/hold relative to CLK:
  - `tSCSU`: SYNC to CLK setup time
  - `tCSHD`: CLK to SYNC hold time 

In **SPI mode**, when SYNC is taken low:
- DRDY goes **high immediately**.
- After SYNC returns high, DRDY stays high while the digital filter settles.
- New valid data become ready after `tNDR` ≈ **129 conversions (1/fDATA)**, then DRDY falls again. 

---

## 7) Minimal “known-good” SPI settings

- Configure device for SPI (`FORMAT[2:0] = 000/001/010` as needed).
- MCU SPI mode:
  - **CPOL = 0**
  - **CPHA = 0** (capture on rising edge, change on falling edge)
- Start reading on **DRDY falling edge**.
- Clock exactly:
  - **24 SCLKs** per channel in **Discrete** mode (`FORMAT=010`), reading DOUT[8:1] in parallel, or
  - **24·N SCLKs** in **TDM** mode (`N = number of active channels`) on DOUT1. 
