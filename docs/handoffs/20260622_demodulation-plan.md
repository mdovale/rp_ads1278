# rp_ads1278 — FPGA half-cycle demod handoff

**Status:** Not implemented.

Implement half-cycle demod in the FPGA for the chopped Wheatstone bridge. MOD is the 10 Hz square wave on io5 (`exp_p_io[5]`). See [`20260519_modulation-output-and-protocol-v2.md`](20260519_modulation-output-and-protocol-v2.md) for MOD details.

## Setup

- Sensor arm → **IN+** → **CH1** (raw bridge, always streamed)
- Reference arm → **IN−**
- **CH8** carries demod when enabled (last value held until next update, ~10 Hz)
- Other channels unchanged
- No protocol change — CH8 is already in the stream

## Algorithm (step by step)

Run this on each new ADC sample (`spi_new_data`), using CH1 and `mod_o`:

**Step 1 — Bin the sample**

```text
if mod_o == 1:
    sum_pos += sample
    count_pos++
else:
    sum_neg += sample
    count_neg++
```

**Step 2 — End of positive half** (`mod_o` goes 1→0)

```text
avg_pos = sum_pos / count_pos
reset sum_pos and count_pos
```

**Step 3 — End of negative half** (`mod_o` goes 0→1)

```text
avg_neg = sum_neg / count_neg
demod   = (avg_pos - avg_neg) / 2
reset sum_neg and count_neg
```

**Step 4 — Hold the result**

Keep `demod_out` until the next full cycle (~10 Hz at default MOD). Stream that value on CH8.

Notes:
- Sign-extend CH1 to 32 bits before summing
- Divide by 2 with signed `>>> 1`
- Use ~48-bit sums and 16-bit counts
- Clear all state when demod is disabled

## Enable

Add **`CTRL[2]`** = demod enable at `0x24`.

```c
// server/memory_map.h
ADS1278_CTRL_DEMOD_ENABLE = 1u << 2
```

`CTRL[2] = 0` → CH8 is normal raw ADC8.

## Implementation (step by step)

### Step 1 — New module `fpga/rtl/ads1278_demod.v`

Ports: `clk`, `rstn`, `enable`, `new_data`, `mod_i`, `sample[23:0]`, `demod_out[31:0]`

Implement the algorithm above. Keep `mod_prev` to detect edges on `new_data`.

### Step 2 — Integrate in `fpga/rtl/ads1278_acq_top.v`

1. Add inputs `mod_i` and `demod_enable`.
2. Instantiate `ads1278_demod` on `spi_new_data`, `mod_i`, and `spi_ch0` (CH1).
3. Mux CH8:

   ```text
   spi_ch7_effective = demod_enable ? demod_out[23:0] : spi_ch7
   ```

4. Use `spi_ch7_effective` in the FIFO pack and in `ch_data_7` MMIO read.
5. Leave CH1 and channels 2–7 unchanged.

### Step 3 — Wire control in `fpga/rtl/ads1278_axi_slave.sv`

1. Set `demod_enable = ctrl_reg[2]`.
2. Pass `mod_o` and `demod_enable` into `ads1278_acq_top`.
3. Update the `CTRL` comment in the register map header.

### Step 4 — Add to Vivado

Add `ads1278_demod.v` to `fpga/source/cfg_rp125_14/ads1278.tcl`.

### Step 5 — Server constant

Add `ADS1278_CTRL_DEMOD_ENABLE` to `server/memory_map.h`. No protocol changes.

### Step 6 — Docs

Update `docs/feats/fpga-register-map.md`, `ads1278-acquisition-pipeline.md`, and `server-mmio-contract.md`.

## Bring-up

```sh
devmem write 0x24 0x6    # enable + demod (bits 1 and 2)
devmem write 0x28 0x271  # EXTCLK_DIV example
```

Plot **CH1** (raw) and **CH8** (demod) in the client.

## Tests

1. Bitstream builds
2. CH1 shows chopped bridge at ADC rate
3. CH8 is slow/smooth (~10 updates/s) with demod on
4. CH8 is raw again with demod off

## Post-edge sample skip

The demod path now has an MMIO-only settling-time knob:

```sh
ads1278-rpdevmem write 0x6c <N_SKIP>
ads1278-rpdevmem read 0x6c
ads1278-rpdevmem write 0x24 0x6    # enable acquisition + demod
```

`DEMOD_SKIP` is at `0x6C`, resets to `0`, and uses bits `[15:0]`. A value of `0` keeps the original behavior. A non-zero value skips the first `N_SKIP` ADC samples after every MOD edge before adding CH1 into the positive or negative half-cycle sum.

Bring-up check: capture CH8 demod data with `N_SKIP=0`, then with the calibrated skip count from the notebook edge-settling analysis, and compare ASD/noise around the demod output. CH1 raw data should be unchanged; only the CH8 demod replacement path is affected when `CTRL[2]` is enabled.

Keep `N_SKIP` below the available samples in a MOD half-cycle. If the skip window consumes an entire half-cycle, the empty-count guard preserves the previous half-cycle average and CH8 can appear held.

## Not in v1

- Client GUI toggle for demod
- Other source/dest channels (hardcode CH1 → CH8)
- I/Q or auto phase correction
