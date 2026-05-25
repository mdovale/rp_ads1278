#include "memory_map.h"

#include <assert.h>

int main(void)
{
    assert(ADS1278_REG_DMA_BUF_STATUS == 0x60u);
    assert(ADS1278_REG_DMA_BUF_ACK == 0x64u);
    assert(ADS1278_REG_DMA_OVERWRITE_COUNT == 0x68u);

    assert(ADS1278_DMA_STATUS_CONFIG_PENDING == (1u << 5));
    assert(ADS1278_DMA_STATUS_OVERWRITE_PENDING == (1u << 6));
    assert(ADS1278_DMA_IRQ_OVERWRITE == (1u << 3));

    assert(ADS1278_DMA_BUF_STATUS_BUF0_FULL == (1u << 0));
    assert(ADS1278_DMA_BUF_STATUS_BUF1_FULL == (1u << 1));
    assert(ADS1278_DMA_BUF_STATUS_ACTIVE_BUF == (1u << 2));
    assert(ADS1278_DMA_BUF_STATUS_OVERWRITE_PENDING == (1u << 3));
    assert(ADS1278_DMA_BUF_ACK_BUF0 == (1u << 0));
    assert(ADS1278_DMA_BUF_ACK_BUF1 == (1u << 1));
    assert(ADS1278_DMA_MODE_PATTERN == 0u);
    assert(ADS1278_DMA_MODE_CAPTURE == 1u);

    return 0;
}
