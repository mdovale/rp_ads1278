# rp_ads1278 — Phase 8 handoff (capture FIFO → DDR)

Phase 8 connects the acquisition staged FIFO to the existing HP0 DMA writer. Pattern mode (`DMA_CTRL` mode `0`) is unchanged for bring-up.

## Summary

- **RTL:** `ads1278_dma_fifo_axis.v` pops 320-bit FIFO records and emits **32** stream words per capture (**128-byte DDR stride**, canary `0xAD127831` on word 31). See `docs/handoffs/20260524_dma-frame-burst-alignment.md`.
- **RTL:** `ads1278_dma_phase4.v` mode `1` = capture, mode `0` = synthetic pattern.
- **RTL:** `ads1278_acq_top` FIFO `pop` is driven by the DMA block (no longer tied off).
- **SW:** `ADS1278_DMA_MODE_CAPTURE` in `server/memory_map.h`; `rpdevmem dma-frames` parses DDR frame records.

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

sleep 1
devmem dma-status
devmem read 0x30               # FIFO_DROPS — should stay 0 if DDR keeps up

devmem write 0x38 0x0          # stop before readback
devmem dma-frames 16           # expect gap=1 between frame_count values

# Pattern mode regression
devmem write 0x38 0x1          # enable + mode 0
devmem write 0x38 0x0
devmem ddr-dump 8
```

## Key files

| Area | Path |
|------|------|
| FIFO → AXIS | `fpga/rtl/ads1278_dma_fifo_axis.v` |
| DMA mux | `fpga/rtl/ads1278_dma_phase4.v` |
| Acquisition FIFO | `fpga/rtl/ads1278_acq_top.v` |
| Top wiring | `fpga/rtl/red_pitaya_top.sv` |
| Frame layout | `docs/feats/dma-frame-record.md` |
| Bring-up tool | `server/rpdevmem.c` (`dma-frames`) |

## Caveats

- **Both enables required:** `CTRL[1]` (ADC) and `DMA_CTRL[0]` (DMA).
- **FIFO drops:** if `FIFO_DROPS` climbs, capture rate exceeds DDR drain — reduce rate or increase buffer/consumer speed (Phase 9 server).
- **Ping-pong + buf1 dump:** `ddr-dump` still maps `DMA_BASE_ADDR` only; use page-aligned mmap for buffer 1 (see Phase 6 notes).
- **DDR stride:** parsers must use **128-byte** records (`ADS1278_DMA_FRAME_SIZE`); expect `pad=ok` and canary `0xAD127831` — see `docs/feats/dma-frame-record.md`.
