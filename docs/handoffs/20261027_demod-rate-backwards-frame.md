# Demod-rate replay gate handoff

**Date:** 2026-10-27  
**Status:** **Implemented in repo**; on-target confirmation still recommended.  
**Prior context:** [`20261013_demod-sample-rate-discrepancy.md`](20261013_demod-sample-rate-discrepancy.md)

---

## Summary

Demod-rate CSV logging was expected to write about **10 rows/s** at `MOD_DIV = 6250000`, but captured files showed about **40 rows/s**. The FPGA demodulator was not producing 40 Hz data. It was producing one new CH1 demod value per 10 Hz modulation cycle.

The extra rows came from both CSV loggers treating a backwards 16-bit `frame_cnt` as a huge forward interval:

```text
(frame_cnt - last_frame_cnt) & 0xffff
```

A step like `42659 -> 42658` becomes `65535`, which is larger than the demod interval (`~2441` frames at `extclk_div=5`, `mod_div=6250000`). The logger then wrote the stale/replayed row and replaced its saved CH1 value. The real demod value later looked like a fresh change, creating repeated rows.

---

## Evidence Pattern

The 2026-10-27 capture showed the same four-row pattern per demod cycle:

```text
msg_seq   frame_cnt  ch1
59088740  42380     -2572   real new demod value
59089018  42146     -2574   older frame; backwards delta should be ignored
59089019  42659     -2572   same real value replayed shortly after
59089530  42658     -2572   frame_cnt - 1; backwards/replayed row
59091181  44821     -2574   next real demod value, 2441 frames later
```

The real demod cadence is visible in the forward steps:

```text
42380 -> 44821 = 2441 frames
44821 -> 47263 = 2442 frames
47263 -> 49704 = 2441 frames
```

That matches one full 10 Hz MOD cycle because:

```text
frames_per_demod = round(6250000 / (5 * 512)) = 2441
```

---

## Implemented Fix

Both loggers now ignore out-of-order 16-bit frame deltas and too-soon forward replays before checking CH1 changes or the elapsed demod interval.

Rule:

```text
delta = (frame_cnt - last_frame_cnt) modulo 65536

delta == 0                         -> duplicate same frame; drop
delta > 32768                      -> backwards/out-of-order; drop and keep previous state
delta < 0.9 * frames_per_demod     -> too soon to be a real demod update; drop
otherwise                          -> normal forward progress; apply CH1-change / interval gate
```

The important part is that dropped backwards or too-soon replay rows **do not** update `last_demod_frame_cnt` or `last_demod_ch1`.

Files changed:

- `server/csv_logger.c`
- `client/ads1278_client/csv_logger.py`
- `server/tests/test_csv_logger.c`
- `client/tests/test_csv_logger.py`
- `docs/feats/client.md`
- `docs/feats/server.md`
- `docs/handoffs/20261013_demod-sample-rate-discrepancy.md`

---

## Test Coverage

Added matching regressions for server USB/local logging and Python host logging. The first tests replay the backwards 2026-10-27 bad burst:

```text
42380/-2572, 42146/-2574, 42659/-2572, 42658/-2572, 44821/-2574
```

Expected output is now two CSV rows:

```text
42380/-2572
44821/-2574
```

The second tests replay the forward-count stale-value burst observed after the backwards filter:

```text
19380/-2762, 19474/-2764, 19476/-2762, 21822/-2759
```

Expected output is:

```text
19380/-2762
21822/-2759
```

The third tests replay the half-period-ish rows observed after a half-period threshold was tried:

```text
724/-2761, 1944/-2757, 3166/-2758
```

Expected output is:

```text
724/-2761
3166/-2758
```

Commands run:

```bash
make -C server test_csv_logger && ./server/test_csv_logger
python -m pytest client/tests/test_csv_logger.py
```

Both passed.

---

## What This Fixes

- Host CSV with **Demod rate (~MOD Hz)** selected for CH1 should no longer turn one 10 Hz demod update into about four rows or log short forward replays.
- USB CSV demod-rate logging uses the C logger and gets the same behavior.
- Backwards/stale DMA frames and too-soon forward replays no longer poison the logger's saved state.

## What It Does Not Fix

The DMA stream can still present frames out of monotonic order inside or around a buffer. This fix prevents that from inflating demod-rate CSV row counts, but the DMA-order issue should still be investigated separately in the server DMA consume path:

- `server/server.c`
- `ads1278_dma_find_frame_start_word`
- ping-pong buffer parse/ack sequencing

---

## On-Target Verification

1. Deploy the updated client/server.
2. Enable acquisition + demod (`CTRL & 0x6 == 0x6`) with `MOD_DIV = 6250000`.
3. Log CH1 only with demod-rate logging enabled.
4. Confirm row cadence is about **10 rows/s**, not **40 rows/s**.
5. Confirm forward logged `frame_cnt` steps are near **2441/2442** at `extclk_div=5`.

