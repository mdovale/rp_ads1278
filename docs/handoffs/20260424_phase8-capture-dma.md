# rp_ads1278 — Phase 8 handoff (capture FIFO → DDR)

Phase 8 connects the acquisition staged FIFO to the existing HP0 DMA writer. Pattern mode (`DMA_CTRL` mode `0`) is unchanged for bring-up.

## Status (2026-05-27)

**Passed on-target** (`rp-f0ef77`): 128-byte DDR stride, `devmem dma-frames` with `pad=ok` and `gap=1`, `FIFO_DROPS` delta 0 on 2 s and 300 s soaks at `EXTCLK_DIV=0x271`. Details and scripts: `docs/handoffs/20260524_dma-frame-burst-alignment.md`.

**Next:** Validate `ads1278-server --dma` on target — initial Phase 9 server consumer is implemented and drives `DMA_BUF_ACK`.

## Summary

- **RTL:** `ads1278_dma_fifo_axis.v` pops 320-bit FIFO records and emits **32** stream words per capture (**128-byte DDR stride**, canary `0xAD127831` on word 31 of each record). See `docs/handoffs/20260524_dma-frame-burst-alignment.md`.
- **RTL:** `ads1278_dma_phase4.v` mode `1` = capture, mode `0` = synthetic pattern.
- **RTL:** `ads1278_acq_top` FIFO `pop` is driven by the DMA block (no longer tied off).
- **SW:** `ADS1278_DMA_MODE_CAPTURE` in `server/memory_map.h`; `devmem dma-frames` parses DDR frame records (use `devmem` → `ads1278-rpdevmem`).

## On-target capture test

```sh
# Acquisition on (adjust divider as needed)
devmem write 0x24 0x2          # CTRL enable
devmem write 0x28 0x271        # EXTCLK_DIV example (100 kHz EXTCLK)

# DMA capture mode: enable + mode 1
devmem write 0x38 0x0
devmem write 0x58 0xf
devmem write 0x3c 0x1e000000
devmem write 0x40 0x00010000
devmem write 0x38 0x3          # bit0 enable, bits[2:1]=1 capture

sleep 2
devmem dma-status
devmem read 0x30               # FIFO_DROPS — should stay 0 if DDR keeps up

devmem write 0x38 0x0          # stop before readback
devmem dma-frames 16           # expect gap=1, pad=ok

# Automated drop + parse check (board-local scripts; see 20260524 handoff)
./dma-drop-test.sh
CAPTURE_SEC=300 ./dma-drop-test-long.sh
```

## Drop / soak tests

| Script (board-local) | Purpose |
|----------------------|---------|
| `dma-drop-test.sh` | ~2 s capture; `FIFO_DROPS` delta + `dma-frames` parse |
| `dma-drop-test-long.sh` | Default 300 s; samples `FIFO_DROPS` / `DMA_OVERWRITE_COUNT` / `DMA_WRAP_COUNT` every 30 s |

Long runs without `DMA_BUF_ACK` will increment **`DMA_OVERWRITE_COUNT`** even when **`FIFO_DROPS`** stays 0.

## Key files

| Area | Path |
|------|------|
| FIFO → AXIS | `fpga/rtl/ads1278_dma_fifo_axis.v` |
| DMA mux | `fpga/rtl/ads1278_dma_phase4.v` |
| Acquisition FIFO | `fpga/rtl/ads1278_acq_top.v` |
| Top wiring | `fpga/rtl/red_pitaya_top.sv` |
| Frame layout | `docs/feats/dma-frame-record.md` |
| Bring-up tool | `server/rpdevmem.c` (`dma-frames`; invoke as `devmem`) |
| Board soak scripts | `dma-drop-test.sh`, `dma-drop-test-long.sh` (on-target; see `20260524` handoff) |

## Caveats

- **Both enables required:** `CTRL[1]` (ADC) and `DMA_CTRL[0]` (DMA).
- **FIFO drops:** if `FIFO_DROPS` climbs, capture rate exceeds DDR drain — reduce `EXTCLK_DIV` or speed up consumer (Phase 9).
- **Ping-pong + buf1 dump:** `ddr-dump` still maps `DMA_BASE_ADDR` only; buffer 1 needs mmap at `base + DMA_BUF_SIZE`.
- **DDR stride:** parsers use **128-byte** records; canary may start at word **29** with **`frame_start_phase=30`** — use `dma-scan-canary`, not a fixed `ddr-read 31` alone.
