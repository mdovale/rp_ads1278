#ifndef ADS1278_DMA_FRAME_H
#define ADS1278_DMA_FRAME_H

#include <stddef.h>
#include <stdint.h>

#if defined(__BYTE_ORDER__) && (__BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__)
#error "rp_ads1278 DMA frame layout requires a little-endian host"
#endif

enum {
    ADS1278_DMA_FRAME_CHANNEL_COUNT = 8,
    /* Sample payload (FIFO / protocol fields). */
    ADS1278_DMA_FRAME_PAYLOAD_WORDS = 10,
    ADS1278_DMA_FRAME_PAYLOAD_SIZE = 40,
    /*
     * DDR stride: padded to 128 bytes so one capture record matches one
     * axis_ram_writer burst (32 stream words). Word 31 is a fixed canary.
     */
    ADS1278_DMA_FRAME_WORDS = 32,
    ADS1278_DMA_FRAME_SIZE = 128,
    ADS1278_DMA_FRAME_FRAME_COUNT_OFFSET = 0,
    ADS1278_DMA_FRAME_STATUS_RAW_OFFSET = 4,
    ADS1278_DMA_FRAME_CHANNELS_OFFSET = 8,
    ADS1278_DMA_FRAME_PADDING_OFFSET = 40,
    ADS1278_DMA_FRAME_STRIDE_CANARY_OFFSET = 124,
    ADS1278_DMA_FRAME_STRIDE_CANARY = 0xad127831u
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
    uint32_t padding[22];
} ads1278_dma_frame;

typedef char ads1278_dma_frame_size_must_be_128_bytes[
    (sizeof(ads1278_dma_frame) == ADS1278_DMA_FRAME_SIZE) ? 1 : -1
];
typedef char ads1278_dma_frame_payload_must_be_40_bytes[
    (ADS1278_DMA_FRAME_PADDING_OFFSET == ADS1278_DMA_FRAME_PAYLOAD_SIZE) ? 1 : -1
];
typedef char ads1278_dma_frame_canary_must_be_last_word[
    (offsetof(ads1278_dma_frame, padding[21]) == ADS1278_DMA_FRAME_STRIDE_CANARY_OFFSET)
        ? 1
        : -1
];

#endif
