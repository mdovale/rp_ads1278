#ifndef ADS1278_DMA_FRAME_H
#define ADS1278_DMA_FRAME_H

#include <stdint.h>

#if defined(__BYTE_ORDER__) && (__BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__)
#error "rp_ads1278 DMA frame layout requires a little-endian host"
#endif

enum {
    ADS1278_DMA_FRAME_CHANNEL_COUNT = 8,
    ADS1278_DMA_FRAME_WORDS = 10,
    ADS1278_DMA_FRAME_SIZE = 40,
    ADS1278_DMA_FRAME_FRAME_COUNT_OFFSET = 0,
    ADS1278_DMA_FRAME_STATUS_RAW_OFFSET = 4,
    ADS1278_DMA_FRAME_CHANNELS_OFFSET = 8
};

#if defined(__GNUC__) || defined(__clang__)
#define ADS1278_DMA_PACKED __attribute__((packed))
#else
#define ADS1278_DMA_PACKED
#endif

typedef struct ADS1278_DMA_PACKED {
    uint32_t frame_count;
    uint32_t status_raw;
    int32_t channels[ADS1278_DMA_FRAME_CHANNEL_COUNT];
} ads1278_dma_frame;

typedef char ads1278_dma_frame_size_must_be_40_bytes[
    (sizeof(ads1278_dma_frame) == ADS1278_DMA_FRAME_SIZE) ? 1 : -1
];

#endif
