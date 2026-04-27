#ifndef ADS1278_MEMORY_MAP_H
#define ADS1278_MEMORY_MAP_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "protocol.h"

#define ADS1278_MMIO_DEFAULT_PATH "/dev/mem"
#define ADS1278_MMIO_BASE 0x42000000u
#define ADS1278_MMIO_SIZE 0x1000u
#define ADS1278_SNAPSHOT_RETRY_LIMIT 3u
#define ADS1278_DMA_PHASE4_DDR_BASE 0x1E000000u
#define ADS1278_DMA_PHASE4_DDR_SIZE 0x00010000u
#define ADS1278_DMA_BURST_BYTES 128u

enum {
    ADS1278_REG_CH1 = 0x00,
    ADS1278_REG_CH2 = 0x04,
    ADS1278_REG_CH3 = 0x08,
    ADS1278_REG_CH4 = 0x0c,
    ADS1278_REG_CH5 = 0x10,
    ADS1278_REG_CH6 = 0x14,
    ADS1278_REG_CH7 = 0x18,
    ADS1278_REG_CH8 = 0x1c,
    ADS1278_REG_STATUS = 0x20,
    ADS1278_REG_CTRL = 0x24,
    ADS1278_REG_EXTCLK_DIV = 0x28,
    ADS1278_REG_FIFO_STATUS = 0x2c,
    ADS1278_REG_FIFO_DROPS = 0x30,
    ADS1278_REG_FIFO_CAPACITY = 0x34,
    ADS1278_REG_DMA_CTRL = 0x38,
    ADS1278_REG_DMA_BASE_ADDR = 0x3c,
    ADS1278_REG_DMA_BUF_SIZE = 0x40,
    ADS1278_REG_DMA_STATUS = 0x44,
    ADS1278_REG_DMA_WRITE_INDEX = 0x48,
    ADS1278_REG_DMA_WRAP_COUNT = 0x4c,
    ADS1278_REG_DMA_ERROR_COUNT = 0x50,
    ADS1278_REG_DMA_IRQ_STATUS = 0x54,
    ADS1278_REG_DMA_IRQ_ACK = 0x58
};

enum {
    ADS1278_CTRL_SYNC_TRIGGER = 1u << 0,
    ADS1278_CTRL_ENABLE = 1u << 1
};

enum {
    ADS1278_DMA_CTRL_ENABLE = 1u << 0,
    ADS1278_DMA_CTRL_MODE_SHIFT = 1,
    ADS1278_DMA_CTRL_MODE_MASK = 0x3u << ADS1278_DMA_CTRL_MODE_SHIFT,
    ADS1278_DMA_CTRL_IRQ_ENABLE = 1u << 8
};

enum {
    ADS1278_DMA_MODE_PATTERN = 0u
};

enum {
    ADS1278_DMA_STATUS_ENABLED = 1u << 0,
    ADS1278_DMA_STATUS_RUNNING = 1u << 1,
    ADS1278_DMA_STATUS_CONFIG_ERROR = 1u << 2,
    ADS1278_DMA_STATUS_WRAP_PENDING = 1u << 3,
    ADS1278_DMA_STATUS_ERROR_PENDING = 1u << 4,
    ADS1278_DMA_STATUS_LAST_BRESP_SHIFT = 8,
    ADS1278_DMA_STATUS_LAST_BRESP_MASK = 0x3u << ADS1278_DMA_STATUS_LAST_BRESP_SHIFT,
    ADS1278_DMA_STATUS_WRITE_INDEX_SHIFT = 16,
    ADS1278_DMA_STATUS_WRITE_INDEX_MASK = 0xffffu << ADS1278_DMA_STATUS_WRITE_INDEX_SHIFT
};

enum {
    ADS1278_DMA_IRQ_WRAP = 1u << 0,
    ADS1278_DMA_IRQ_ERROR = 1u << 1,
    ADS1278_DMA_IRQ_CONFIG = 1u << 2
};

typedef struct {
    int fd;
    size_t map_size;
    volatile uint8_t *base;
} ads1278_mmio;

typedef struct {
    uint32_t status_raw;
    uint32_t ctrl_raw;
    uint32_t extclk_div;
    int32_t channels[ADS1278_CHANNEL_COUNT];
    uint16_t frame_cnt;
} ads1278_snapshot;

enum {
    ADS1278_SNAPSHOT_OK = 0,
    ADS1278_SNAPSHOT_FALLBACK_USED = 1
};

int ads1278_mmio_open(ads1278_mmio *mmio, const char *path);
void ads1278_mmio_close(ads1278_mmio *mmio);
uint32_t ads1278_mmio_read32(const ads1278_mmio *mmio, uint32_t offset);
void ads1278_mmio_write32(const ads1278_mmio *mmio, uint32_t offset, uint32_t value);
int32_t ads1278_sign_extend24(uint32_t raw_value);
uint16_t ads1278_status_frame_count(uint32_t status_raw);
bool ads1278_status_new_data(uint32_t status_raw);
bool ads1278_status_overflow(uint32_t status_raw);
int ads1278_mmio_read_snapshot(
    const ads1278_mmio *mmio,
    ads1278_snapshot *snapshot,
    const ads1278_snapshot *fallback_snapshot,
    unsigned int retry_limit
);

#endif
