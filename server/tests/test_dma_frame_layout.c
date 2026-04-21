#include "dma_frame.h"

#include <assert.h>
#include <stddef.h>

int main(void)
{
    assert(sizeof(ads1278_dma_frame) == ADS1278_DMA_FRAME_SIZE);
    assert(offsetof(ads1278_dma_frame, frame_count) == ADS1278_DMA_FRAME_FRAME_COUNT_OFFSET);
    assert(offsetof(ads1278_dma_frame, status_raw) == ADS1278_DMA_FRAME_STATUS_RAW_OFFSET);
    assert(offsetof(ads1278_dma_frame, channels[0]) == ADS1278_DMA_FRAME_CHANNELS_OFFSET);
    assert(offsetof(ads1278_dma_frame, channels[7]) == 36u);
    return 0;
}
