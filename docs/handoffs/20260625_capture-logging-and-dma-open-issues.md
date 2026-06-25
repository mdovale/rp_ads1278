# rp_ads1278 — Capture, logging UX, and DMA quality open issues

**Date:** 2026-06-25  
**Status:** **Open** — operator-reported; not yet triaged on hardware in this session  
**Prior context:** `20260612_usb-csv-logging.md`, `20260524_dma-frame-burst-alignment.md`, `20260527b_axi-read-snapshot-and-dma-rate-limits.md`

---

## Summary

| # | Issue | Area | Priority |
|---|--------|------|----------|
| 1 | Legacy mode frame loss — quantify gaps vs rate | Server + client + analysis | High |
| 2 | Host CSV save UX — file picker on Start, not pre-filled folder/name | Client GUI | Medium |
| 3 | Host timed CSV — show live countdown prominently | Client GUI | Medium |
| 4 | USB timed CSV — resync active log + remaining time after reconnect | Protocol + server + client | High |
| 5 | DMA route spikes (absent in legacy); need clean path to ~24 ksps | FPGA + server + client | High |

These are independent workstreams but share the theme: **trustworthy capture at useful rates with clear operator feedback**.

---

## Issue 1 — Legacy mode frame loss investigation

### Problem

In legacy (non-`--dma`) mode, logged CSV rows and live `frame_cnt` suggest **missing frames**. Need to measure **how many** frames are lost and **at which sample rates / dividers**.

### Current behavior (by design, but under-instrumented)

Legacy mode is explicitly a **latest-sample streamer**, not lossless transport:

- The server wakes at roughly `2 × f_data`, capped by `--poll-ms`, and emits `SAMPLE` **only when `frame_cnt` changes** (`ads1278_maybe_send_sample` in `server/server.c`).
- If multiple ADC frames occur between polls, intermediate frames are never sent.
- The client logs only received `SAMPLE` rows; `frame_cnt` is 16-bit and can wrap.

Relevant docs: `docs/feats/server.md`, `docs/feats/server-protocol.md`, `docs/feats/client.md` (explicitly out of scope: “guaranteed gap-free history capture”).

The client already keeps `frame_history` in the controller snapshot but **does not compute or display gap statistics**.

### Investigation plan

1. **Offline (CSV):** For a legacy capture, compute consecutive `frame_cnt` deltas (unwrap 16-bit). Report:
   - rows received vs expected (`duration × fs`)
   - gap histogram (`gap > 1`)
   - loss rate vs `extclk_div`
2. **Live (GUI or status):** Add counters such as `frames_received`, `frames_skipped` (sum of `gap - 1`), `max_gap`, optionally `loss_pct`.
3. **Sweep rates:** Test dividers where loss becomes unacceptable (e.g. 625, 271, 125, 62, 31, **5**).
4. **Separate FPGA loss from transport loss:**
   - `overflow: yes` in snapshot → SPI/FSM overlap (sticky until disable)
   - Transport loss → gaps in received `frame_cnt` with `overflow: no`

### Target rate reference

From `client/ads1278_client/units.py`:

```text
fs = 125 MHz / (2 × EXTCLK_DIV × 512)
```

| EXTCLK_DIV | ~fs |
|------------|-----|
| 625 | ~195 Hz |
| 125 | ~977 Hz |
| 5 | **~24.4 ksps** |

### Acceptance criteria

- [ ] Notebook or script reports frame loss vs divider for legacy CSV logs
- [ ] GUI or status line shows live skip stats during streaming
- [ ] Documented “safe” legacy divider for gap-free (or ≤X% loss) host CSV

### Key files

- `server/server.c` — legacy poll + `ads1278_maybe_send_sample`
- `client/ads1278_client/controller.py` — `_frame_history`, gap stats hook
- `client/ads1278_client/csv_logger.py` — logged `frame_cnt` column
- `client/ads1278_client/units.py` — rate helpers

---

## Issue 2 — Host CSV save dialog UX

### Problem

The operator must set **CSV folder** and **CSV filename** before clicking **Start CSV**. Preferred flow: click **Start CSV** → **Save As** dialog → begin logging to that path.

### Current behavior

`main_window.py` exposes persistent **CSV folder** and **CSV filename** fields in the command bar. `_start_logging()` reads those values and passes them to `controller.start_logging(..., local_directory=...)`.

USB mode still needs a **basename only** (server path under `/mnt/usb/ads1278/logs`); Save As applies to **“This computer”** only.

### Proposed change

1. **Local:** On **Start CSV**, if destination is “This computer”, open `QFileDialog.getSaveFileName` with default `ads1278_YYYYMMDD_HHMMSS.csv`; on OK, start logging. Remove or hide persistent folder/filename fields (optional: show chosen path read-only while logging).
2. **USB:** Keep basename entry or a simpler “filename” prompt; no host path picker.
3. Drop or repurpose `csv_folder` QSettings if unused.

### Acceptance criteria

- [ ] Local: Start CSV opens save dialog; no pre-pick of folder required
- [ ] USB: unchanged server-side basename flow
- [ ] Tests updated in `client/tests/test_controller_and_main_window.py`

### Key files

- `client/ads1278_client/main_window.py` — `_start_logging`, `_browse_csv_folder`
- `client/ads1278_client/controller.py` — `start_logging`
- `docs/feats/client.md`

---

## Issue 3 — Host timed CSV countdown on GUI

### Problem

When logging to **this computer** with a timed duration, the GUI should clearly show **time remaining** until logging stops.

### Current behavior (partial)

- The controller tracks `_logging_deadline_monotonic` and exposes `logging_remaining_s` in the snapshot.
- `logging_label` in the status bar can show `(X left)` when a path is set.
- **But** every `SAMPLE` overwrites `status_text` with `SAMPLE seq=... frame_cnt=...`, so the main status line does not stay on countdown.
- Countdown lives mainly in the small `logging_label`, which is easy to miss.

Local timed logging **does** use a client `threading.Timer` to stop at expiry (`controller.py`).

### Proposed change

1. Add a dedicated **CSV countdown** control near duration / Start/Stop (e.g. `CSV remaining: 1h 23m 45s`).
2. Do not let per-sample status overwrite logging status while `_logger` is active (or split “stream status” vs “logging status”).
3. Optionally disable or shorten folder/filename fields while logging.

### Acceptance criteria

- [ ] During host timed CSV, countdown updates at GUI refresh rate (~50 ms) and is visually obvious
- [ ] Countdown reaches zero and logging stops with clear confirmation
- [ ] Existing test `test_controller_reports_csv_countdown_when_timed_capture_starts` still passes; add GUI-level test if practical

### Key files

- `client/ads1278_client/main_window.py` — `_refresh`, CSV toolbar
- `client/ads1278_client/controller.py` — `_logging_remaining_seconds_unlocked`, `_handle_message` (SAMPLE status overwrite)

---

## Issue 4 — USB timed logging state after reconnect

### Problem

Example: arm **10 h** USB capture, disconnect GUI and SSH, later reconnect client. Operator wants to see:

- logging is **active** on USB
- **which file** is being written
- **how much time remains** on the server-side timer

### Current behavior (gap)

**Server** (`server/server.c`):

- Owns `local_logger`, `local_log_deadline`, `local_log_deadline_valid`
- Timed USB logging continues after client disconnect (when run under systemd)
- **No protocol field or opcode** exposes logging state to a new client

**Client** (`client/ads1278_client/controller.py`):

- On disconnect, `_close_logger_locked()` clears `_logging_path` and deadline — **all logging UI state is lost**
- USB timed capture intentionally **does not** use a client stop timer (server owns expiry) — see `test_controller_arms_server_timed_usb_csv_without_client_timer`
- On reconnect, client has **no way** to resync

Protocol opcodes today: `START/STOP/SET_LOCAL_LOG_DURATION/SET_LOCAL_LOG_FILENAME` only — no query/status.

### Proposed change (needs protocol bump or v4 extension)

**Option A — Query on connect (minimal):**

- New opcode e.g. `GET_LOCAL_LOG_STATUS` → ACK with bitfield + `remaining_s` + optional filename chunks
- Client sends query after connect; updates `logging_path`, `logging_remaining_s`, destination USB

**Option B — Snapshot extension:**

- Add fields to `ads1278_message` (logging active, remaining_s, rows_written) — breaks fixed 64-byte layout unless versioned

**Option C — Side channel (weak):**

- SSH: `ls -l /mnt/usb/ads1278/logs`, `journalctl -u ads1278-server` — not acceptable as primary UX

Recommend **Option A** to preserve message layout; document in `docs/feats/server-protocol.md`.

### Server-side data already available

- `state->local_logger.active`, `.path`, `.rows_written`
- `ads1278_time_until_deadline_ns(&state->local_log_deadline)` when `local_log_deadline_valid`

### Acceptance criteria

- [ ] Start 10 h USB timed log, disconnect GUI, reconnect → GUI shows USB logging active, path, remaining time (±1 s)
- [ ] After server deadline, reconnect shows logging off
- [ ] Manual USB log without duration: reconnect shows active or idle correctly
- [ ] Fake server + unit tests for new opcode

### Key files

- `server/server.c`, `server/csv_logger.c`, `server/protocol.h`
- `client/ads1278_client/protocol.py`, `controller.py`, `main_window.py`
- `docs/handoffs/20260612_usb-csv-logging.md` — update behavior matrix

---

## Issue 5 — DMA route spikes vs legacy; target 24 ksps

### Problem

**DMA mode** (`--dma` / `--dma-bulk`) shows **spikes** in data that **legacy mode does not** at comparable settings. Need root cause and a path to sustained **~24 ksps** capture.

### Current behavior

| Mode | Data path | Known risks |
|------|-----------|-------------|
| Legacy | MMIO snapshot when `frame_cnt` changes | Skips frames; no DDR stride issues |
| `--dma` | DDR ping-pong, 128-byte frames, `DMA_BUF_ACK` | Overwrite, FIFO drops, parse alignment, GP0 MMIO hang |
| `--dma-bulk` | Batched 40-byte records over TCP | Same PL path + bulk batch boundaries |

**~24 ksps ≈ `EXTCLK_DIV = 5`** (`MIN_EXTCLK_DIV = 3` in client).

Prior handoffs document **GP0 / AXI hangs at aggressive dividers** (e.g. div 5) and **`DMA_OVERWRITE_COUNT`** when consumer is slow — see `20260527b`, `20260528_axi-mmio-hang-handoff.md`.

Spikes in DMA but not legacy may be:

1. **Real samples** — overflow, `FIFO_DROPS`, buffer overwrite (check MMIO counters during capture)
2. **Parse / alignment** — wrong stride → `pad=BAD` / erratic `gap` (Phase 8 fixed 128-byte stride; re-verify bitstream)
3. **Batch artifacts** — partial buffer, canary phase, first-frame skip in server consumer
4. **Coherency** — stale DDR without cache invalidate (`server/server.c` DMA path)
5. **Not spikes in ADC** — legacy shows **latest** sample only (low-pass by omission); DMA shows **every frame in buffer** including real glitches

### Investigation plan

1. **Same divider, A/B:** Legacy CSV vs `--dma-bulk` CSV at div 625 → 125 → 62 → 31 → **5**; plot CH1 diff and `frame_cnt` gaps.
2. **On-target counters** during DMA soak at each divider: `FIFO_DROPS (0x30)`, `DMA_OVERWRITE_COUNT (0x68)`, `overflow`, `DMA_BUF_STATUS (0x60)`.
3. **`devmem dma-frames`** after short capture: require `pad=ok`, `gap=1` when `FIFO_DROPS Δ = 0`.
4. **Server flags:** `--dma-bulk --poll-ms 0` for sustained USB/host logging (per USB handoff).
5. **Bitstream:** Confirm deployed bitstream matches read-snapshot fix if hangs persist at div 5.

### Acceptance criteria

- [ ] Root cause identified (or ruled out: e.g. “legacy hides intermittent FIFO drops”)
- [ ] DMA capture at **≥ 24 ksps** without spikes above agreed threshold (define vs legacy or vs known-good reference)
- [ ] Document recommended server invocation for 24 ksps long captures
- [ ] Update `docs/feats/server.md` / DMA handoffs with findings

### Key files

- `server/server.c` — DMA consumer, bulk emit, CSV + socket path
- `server/dma_frame.h`, `server/rpdevmem.c` — frame parse / canary
- `fpga/rtl/ads1278_axi_slave.sv` — GP0 read snapshot
- `docs/handoffs/20260524_dma-frame-burst-alignment.md`

---

## Suggested work order

1. **Issue 1** — Frame-gap tooling (unblocks honest comparison for Issue 5)
2. **Issue 5** — DMA vs legacy A/B at stepped dividers up to div 5
3. **Issue 4** — Protocol + reconnect UX (high operator value for long USB runs)
4. **Issues 2 & 3** — GUI polish (independent, client-only)

---

## Related docs

- [Client features](../feats/client.md)
- [Server features](../feats/server.md)
- [Server protocol](../feats/server-protocol.md)
- [USB CSV logging handoff](20260612_usb-csv-logging.md)
- [DMA frame burst alignment](20260524_dma-frame-burst-alignment.md)
- [DMA rate limits / GP0 hang](20260527b_axi-read-snapshot-and-dma-rate-limits.md)

---

## Hardware QA checklist (when addressing above)

- [ ] Legacy: CSV gap analysis at dividers 625, 125, 62, 31, 5
- [ ] DMA: same dividers with `--dma-bulk --poll-ms 0`; log MMIO counters
- [ ] USB 10 h timed: disconnect GUI + SSH, reconnect, verify countdown (after Issue 4)
- [ ] Host timed CSV: countdown visible for full duration (after Issue 3)
- [ ] Save As on Start CSV for local logging (after Issue 2)
