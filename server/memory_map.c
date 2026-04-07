#include "memory_map.h"

#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

static void ads1278_snapshot_read_once(
    const ads1278_mmio *mmio,
    ads1278_snapshot *snapshot,
    uint32_t *status_before,
    uint32_t *status_after
)
{
    static const uint32_t channel_offsets[ADS1278_CHANNEL_COUNT] = {
        ADS1278_REG_CH1,
        ADS1278_REG_CH2,
        ADS1278_REG_CH3,
        ADS1278_REG_CH4,
        ADS1278_REG_CH5,
        ADS1278_REG_CH6,
        ADS1278_REG_CH7,
        ADS1278_REG_CH8
    };
    unsigned int index;

    *status_before = ads1278_mmio_read32(mmio, ADS1278_REG_STATUS);
    for (index = 0; index < ADS1278_CHANNEL_COUNT; ++index) {
        snapshot->channels[index] = ads1278_sign_extend24(
            ads1278_mmio_read32(mmio, channel_offsets[index])
        );
    }
    snapshot->ctrl_raw = ads1278_mmio_read32(mmio, ADS1278_REG_CTRL);
    snapshot->extclk_div = ads1278_mmio_read32(mmio, ADS1278_REG_EXTCLK_DIV);
    *status_after = ads1278_mmio_read32(mmio, ADS1278_REG_STATUS);
    snapshot->status_raw = *status_after;
    snapshot->frame_cnt = ads1278_status_frame_count(*status_after);
}

int ads1278_mmio_open(ads1278_mmio *mmio, const char *path)
{
    const char *open_path = path;
    void *mapped;

    if (mmio == NULL) {
        errno = EINVAL;
        return -1;
    }

    if (open_path == NULL) {
        open_path = ADS1278_MMIO_DEFAULT_PATH;
    }

    memset(mmio, 0, sizeof(*mmio));
    mmio->fd = open(open_path, O_RDWR | O_SYNC);
    if (mmio->fd < 0) {
        return -1;
    }

    mmio->map_size = ADS1278_MMIO_SIZE;
    mapped = mmap(NULL, mmio->map_size, PROT_READ | PROT_WRITE, MAP_SHARED, mmio->fd, ADS1278_MMIO_BASE);
    if (mapped == MAP_FAILED) {
        int saved_errno = errno;
        close(mmio->fd);
        mmio->fd = -1;
        errno = saved_errno;
        return -1;
    }

    mmio->base = (volatile uint8_t *)mapped;
    return 0;
}

void ads1278_mmio_close(ads1278_mmio *mmio)
{
    if (mmio == NULL) {
        return;
    }

    if (mmio->base != NULL) {
        munmap((void *)mmio->base, mmio->map_size);
        mmio->base = NULL;
    }
    if (mmio->fd >= 0) {
        close(mmio->fd);
        mmio->fd = -1;
    }
    mmio->map_size = 0;
}

uint32_t ads1278_mmio_read32(const ads1278_mmio *mmio, uint32_t offset)
{
    volatile uint32_t *word_ptr;

    word_ptr = (volatile uint32_t *)(mmio->base + offset);
    return *word_ptr;
}

void ads1278_mmio_write32(const ads1278_mmio *mmio, uint32_t offset, uint32_t value)
{
    volatile uint32_t *word_ptr;

    word_ptr = (volatile uint32_t *)(mmio->base + offset);
    *word_ptr = value;
}

int32_t ads1278_sign_extend24(uint32_t raw_value)
{
    uint32_t masked;

    masked = raw_value & 0x00ffffffu;
    if ((masked & 0x00800000u) != 0u) {
        masked |= 0xff000000u;
    }
    return (int32_t)masked;
}

uint16_t ads1278_status_frame_count(uint32_t status_raw)
{
    return (uint16_t)(status_raw >> 16);
}

bool ads1278_status_new_data(uint32_t status_raw)
{
    return (status_raw & 0x1u) != 0u;
}

bool ads1278_status_overflow(uint32_t status_raw)
{
    return (status_raw & 0x2u) != 0u;
}

int ads1278_mmio_read_snapshot(
    const ads1278_mmio *mmio,
    ads1278_snapshot *snapshot,
    const ads1278_snapshot *fallback_snapshot,
    unsigned int retry_limit
)
{
    ads1278_snapshot last_attempt;
    uint32_t status_before;
    uint32_t status_after;
    unsigned int attempt;

    if (mmio == NULL || snapshot == NULL || mmio->base == NULL) {
        errno = EINVAL;
        return -1;
    }

    if (retry_limit == 0u) {
        retry_limit = 1u;
    }

    memset(&last_attempt, 0, sizeof(last_attempt));

    for (attempt = 0; attempt < retry_limit; ++attempt) {
        ads1278_snapshot_read_once(mmio, &last_attempt, &status_before, &status_after);
        if (ads1278_status_frame_count(status_before) == ads1278_status_frame_count(status_after)) {
            *snapshot = last_attempt;
            return ADS1278_SNAPSHOT_OK;
        }
    }

    if (fallback_snapshot != NULL) {
        *snapshot = *fallback_snapshot;
    } else {
        *snapshot = last_attempt;
    }
    return ADS1278_SNAPSHOT_FALLBACK_USED;
}
