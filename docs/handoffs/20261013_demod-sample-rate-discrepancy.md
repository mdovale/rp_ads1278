# Demod sample-rate discrepancy handoff

**Date:** 2026-10-13  
**Status:** **Superseded by fix plan / implementation handoff** — offline CSV analysis done. Demod itself is one update per 10 Hz MOD cycle. Demod-rate CSV logging writes that update four times. See [`20261027_demod-rate-backwards-frame.md`](20261027_demod-rate-backwards-frame.md) for the backwards-frame gate fix and remaining DMA-order follow-up.  
**Evidence:** `logged_files/test_ch1_09102026.csv` (server USB/local CSV, channel 1 only)  
**Prior context:** [`20260622_demodulation-plan.md`](20260622_demodulation-plan.md), [`20260612_usb-csv-logging.md`](20260612_usb-csv-logging.md), [`docs/feats/server-protocol.md`](../feats/server-protocol.md)

---

## Summary

| Finding | Implication |
|---------|-------------|
| Settings in every row: `ctrl_raw=6`, `extclk_div=5`, `mod_div=6250000` | Acquisition + demod on, MOD is the 10 Hz default |
| 615,936 data rows over 15,507.5 s | **39.7 rows/s**, not 10 |
| One new `ch1` value per ~100 ms | Demod result cadence is **10 Hz** |
| Four CSV rows per MOD cycle | Logger repeats each result **4×** |
| Gate uses `(frame_cnt - last) & 0xffff` | A 1-frame step **backwards** counts as 65,535 frames elapsed |
| Same gate in the Python host logger | Host “Demod rate” CSVs will do this too if `frame_cnt` goes backwards |

**Next owner:** Stop the demod-rate gate from treating a backwards `frame_cnt` as a full period, and do not let a stale older sample replace the last logged value. Then confirm a 10 Hz demod CSV stays near 10 rows/s. Separately, find why the DMA stream handed to the logger is not monotonic.

---

## Symptom

Demod-rate logging of CH1 was expected to follow MOD: one sample per full cycle, **10 samples/s** at `MOD_DIV = 6,250,000`.

The captured file is about **40 samples/s**. Timestamps use nanosecond UTC (`2026-10-09T19:23:41.859052431Z`), so this file was written by `server/csv_logger.c`, not the Python client.

Header:

```text
host_timestamp,msg_seq,frame_cnt,status_raw,ctrl_raw,extclk_div,mod_div,ch1
```

`status_raw` low bits are `new_data=1`, `overflow=0`. The logged `frame_cnt` matches `status_raw[31:16]` by construction in the bulk writer (`frame_count` is copied into the upper half before the row is written).

---

## What 10 Hz should be

| Quantity | Value |
|----------|-------|
| FPGA clock | 125 MHz |
| EXTCLK | `125 MHz / (2 × extclk_div)` = 12.5 MHz at divider 5 |
| ADC rate | `EXTCLK / 512` ≈ **24,414 Hz** |
| MOD | toggles every `mod_div` clocks of 125 MHz → half-period 50 ms, **full cycle 100 ms** |
| Frames per demod | `round(mod_div / (extclk_div × 512))` = **2441** |
| DMA buffer | `ADS1278_DMA_PHASE4_DDR_SIZE` = 64 KB, stride 128 B → **512 frames ≈ 21.0 ms** |

`ads1278_demod_bank` publishes `demod_out` only when the negative-half divide finishes (`batch_op_neg`). That is once per full MOD cycle. The held value is what DMA records on later ADC frames. A correct demod-rate log of one channel is therefore ~10 rows/s, plus a row when the value actually changes inside that cadence.

This is not a 4× clock-formula error. The 2441-frame interval already matches 100 ms at divider 5.

---

## What the file actually does

Rows alternate two gaps:

| Gap between row clusters | Count | Meaning |
|--------------------------|------:|---------|
| 15–30 ms | 152,220 | One DMA buffer (~21 ms) |
| 60–90 ms | 155,071 | Rest of the ~100 ms MOD cycle |

Together that is **two bursts per MOD cycle**. Each burst is two rows a fraction of a millisecond apart, so the file is **four rows per 10 Hz cycle**.

Repeating motif (times from the start of the file):

| t | `frame_cnt` | `ch1` | `msg_seq` step | What it is |
|---|------------:|------:|----------------|------------|
| 0 | 38485 | -100 | — | New demod value |
| +0.4 ms | 38484 | -100 | +511 | Same value, `frame_cnt - 1` |
| +41 ms | 39795 | -97 | +799 | Next demod value |
| +0.1 ms | 39508 | -100 | +225 | Older frame, **previous** value |
| +21 ms | 40021 | -97 | **+1** | Same new value again |
| +0.2 ms | 40020 | -97 | +511 | Same value, `frame_cnt - 1` |
| +84 ms | 42237 | -103 | +1705 | Next MOD cycle |

Dominant pair counts across the whole file:

| Pattern | Count |
|---------|------:|
| `msg_seq + 511`, `frame_cnt - 1`, **same** `ch1` | 149,865 |
| `msg_seq + 1`, frame step ~512, **different** `ch1` | 149,588 |
| `msg_seq` in 800–1999, frame step ~2441, different `ch1` | 126,303 |

`msg_seq + 511` is one 512-frame DMA buffer minus the row just written. `msg_seq + 1` means the two logged records were adjacent valid frames in the bulk stream, but their `frame_cnt` values differ by ~513 rather than 1. The stream the logger sees is not one-frame-monotonic.

Collapsing sub-millisecond duplicates leaves ~20 events/s. Those events are pairs of the **same** new `ch1` value, separated by ~21 ms, then a ~80 ms gap. One new demod number per 100 ms.

---

## Root cause

The demod-rate gate in `server/csv_logger.c` (`ads1278_csv_logger_should_write_row`) writes a row when either:

- any selected channel differs from the last logged value, or
- `(frame_cnt - last_demod_frame_cnt) & 0xffff` is at least `frames_per_demod` (2441 here)

A step of `-1` becomes **65535**, which passes the interval test. The stale row then **replaces** both `last_demod_frame_cnt` and the stored channel value.

One real 10 Hz update then becomes four rows:

1. Value changes. Log it. Remember the new value and its frame.
2. Later in the same DMA buffer, an older frame still holds the previous value and a smaller `frame_cnt`. The unsigned delta looks like a full period, so the gate logs it and **forgets the new value**.
3. The next buffer (~512 frames, ~21 ms later) still holds the new value. Compared with the stale row it looks like another change, so it is logged again.
4. That buffer also presents `frame_cnt - 1` with the same value (`msg_seq` + 511). Another unsigned wrap, another row.

Later buffers in the same 100 ms cycle keep the new value and move forward by only ~512 frames, so they stay under 2441 and are dropped. The next MOD edge starts the four-row sequence again.

The host logger has the same test in `client/ads1278_client/csv_logger.py` (`_should_write_sample`), using `% FRAME_COUNTER_MODULUS`.

`docs/feats/server-protocol.md` describes this gate as “first row, any selected-channel change, or one row per demod frame interval.” It does not mention backwards `frame_cnt`. The implementation treats every non-zero unsigned delta of 2441 or more as forward progress.

---

## What is not the cause

- MOD is not 40 Hz. `mod_div` stays `6250000` on every row.
- The ADC is not being logged at 40 Hz raw. Ungated logging at divider 5 would be ~24,414 rows/s. Bit 8 of `START_LOCAL_LOG` is on, or this file would be orders of magnitude larger.
- `ads1278_demod_bank` does not publish four results per cycle. `demod_out[ch]` updates on the negative-half batch only.

---

## Open question

The gate explains the 4× row count **given** a non-monotonic `frame_cnt`. It does not explain the DMA order itself:

- Inside one buffer, a logged frame is often followed 511 messages later by `frame_cnt - 1` with the same `ch1`.
- Adjacent logged messages (`msg_seq` + 1) often jump ~513 frames and, on the transition, from the new value back to the previous one.

That points at buffer fill/parse order (64 KB ping-pong, 128-byte stride, `ads1278_dma_find_frame_start_word` in `server/server.c`), not at the MOD divider. Fixing the gate will make the CSV 10 Hz even if a stale slot remains. The stale slot should still be tracked down so live plots and gap checks are not fed the same rewind.

---

## Fix direction

1. In both CSV gates, ignore a `frame_cnt` that is not strictly forward in the 16-bit counter (treat a backwards step as out of order; do not update last frame or last value). A practical rule is to ignore deltas greater than half the counter (`> 32768`), which covers the `-1` → `65535` case without treating a real forward wrap of a few thousand frames as backwards.
2. Add a regression: monotonic demod stream logs once per 2441 frames; a following `frame_cnt - 1` with the old value does not add rows; the next forward frame with the new value does not log a second time.
3. Re-check a short on-target demod CSV at divider 5 / 10 Hz MOD. Expect ~10 rows/s, one `ch1` step per ~100 ms, forward `frame_cnt` steps near 2441.
4. If rows are 10 Hz but `frame_cnt` still rewinds inside a buffer, follow that in the DMA consumer. Do not “fix” it by widening the logger interval.

---

## Key files

- `server/csv_logger.c` — `ads1278_frames_per_demod`, `ads1278_csv_logger_should_write_row`
- `client/ads1278_client/csv_logger.py` — `_should_write_sample`
- `client/ads1278_client/units.py` — `sample_rate_hz`, `frames_per_demod`
- `server/server.c` — bulk DMA consume, `ads1278_dma_find_frame_start_word`
- `server/memory_map.h` — `ADS1278_DMA_PHASE4_DDR_SIZE` (`0x10000`)
- `fpga/rtl/ads1278_demod_bank.v` — one `demod_out` update per full cycle
- `docs/feats/server-protocol.md` — demod-rate logging contract
- `logged_files/test_ch1_09102026.csv` — evidence file
