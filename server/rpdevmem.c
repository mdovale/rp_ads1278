#include "memory_map.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

typedef struct {
    int fd;
    size_t map_size;
    volatile uint32_t *words;
} ads1278_ddr_map;

static void print_usage(const char *argv0)
{
    fprintf(stderr,
        "Usage: %s [--mem-path PATH] [snapshot | dma-status | read OFFSET | write OFFSET VALUE | ddr-read WORD_INDEX | ddr-dump [WORD_COUNT]]\n",
        argv0);
}

static int parse_u32(const char *text, uint32_t *value)
{
    unsigned long parsed;
    char *end_ptr;

    errno = 0;
    parsed = strtoul(text, &end_ptr, 0);
    if (errno != 0 || end_ptr == text || *end_ptr != '\0' || parsed > 0xfffffffful) {
        return -1;
    }

    *value = (uint32_t)parsed;
    return 0;
}

static void print_snapshot(const ads1278_snapshot *snapshot)
{
    unsigned int index;

    printf("status_raw  : 0x%08x\n", snapshot->status_raw);
    printf("ctrl_raw    : 0x%08x\n", snapshot->ctrl_raw);
    printf("extclk_div  : %u\n", snapshot->extclk_div);
    printf("frame_cnt   : %u\n", (unsigned int)snapshot->frame_cnt);
    printf("new_data    : %u\n", ads1278_status_new_data(snapshot->status_raw) ? 1u : 0u);
    printf("overflow    : %u\n", ads1278_status_overflow(snapshot->status_raw) ? 1u : 0u);
    for (index = 0; index < ADS1278_CHANNEL_COUNT; ++index) {
        printf("ch%u         : %d\n", index + 1u, snapshot->channels[index]);
    }
}

static int ads1278_dma_get_buffer_config(
    const ads1278_mmio *mmio,
    uint32_t *base_addr,
    uint32_t *buffer_size
)
{
    if (mmio == NULL || base_addr == NULL || buffer_size == NULL) {
        errno = EINVAL;
        return -1;
    }

    *base_addr = ads1278_mmio_read32(mmio, ADS1278_REG_DMA_BASE_ADDR);
    *buffer_size = ads1278_mmio_read32(mmio, ADS1278_REG_DMA_BUF_SIZE);
    return 0;
}

static void print_dma_status(const ads1278_mmio *mmio)
{
    uint32_t dma_ctrl;
    uint32_t dma_base_addr;
    uint32_t dma_buf_size;
    uint32_t dma_status;
    uint32_t dma_write_index;
    uint32_t dma_wrap_count;
    uint32_t dma_error_count;
    uint32_t dma_irq_status;

    dma_ctrl = ads1278_mmio_read32(mmio, ADS1278_REG_DMA_CTRL);
    dma_base_addr = ads1278_mmio_read32(mmio, ADS1278_REG_DMA_BASE_ADDR);
    dma_buf_size = ads1278_mmio_read32(mmio, ADS1278_REG_DMA_BUF_SIZE);
    dma_status = ads1278_mmio_read32(mmio, ADS1278_REG_DMA_STATUS);
    dma_write_index = ads1278_mmio_read32(mmio, ADS1278_REG_DMA_WRITE_INDEX);
    dma_wrap_count = ads1278_mmio_read32(mmio, ADS1278_REG_DMA_WRAP_COUNT);
    dma_error_count = ads1278_mmio_read32(mmio, ADS1278_REG_DMA_ERROR_COUNT);
    dma_irq_status = ads1278_mmio_read32(mmio, ADS1278_REG_DMA_IRQ_STATUS);

    printf("dma_ctrl       : 0x%08x\n", dma_ctrl);
    printf("dma_enable     : %u\n", (dma_ctrl & ADS1278_DMA_CTRL_ENABLE) != 0u ? 1u : 0u);
    printf(
        "dma_mode       : %u\n",
        (unsigned int)((dma_ctrl & ADS1278_DMA_CTRL_MODE_MASK) >> ADS1278_DMA_CTRL_MODE_SHIFT)
    );
    printf("dma_irq_enable : %u\n", (dma_ctrl & ADS1278_DMA_CTRL_IRQ_ENABLE) != 0u ? 1u : 0u);
    printf("dma_base_addr  : 0x%08x\n", dma_base_addr);
    printf("dma_buf_size   : 0x%08x (%u bytes)\n", dma_buf_size, dma_buf_size);
    printf("dma_status     : 0x%08x\n", dma_status);
    printf("dma_running    : %u\n", (dma_status & ADS1278_DMA_STATUS_RUNNING) != 0u ? 1u : 0u);
    printf(
        "dma_cfg_error  : %u\n",
        (dma_status & ADS1278_DMA_STATUS_CONFIG_ERROR) != 0u ? 1u : 0u
    );
    printf(
        "dma_wrap_pend  : %u\n",
        (dma_status & ADS1278_DMA_STATUS_WRAP_PENDING) != 0u ? 1u : 0u
    );
    printf(
        "dma_err_pend   : %u\n",
        (dma_status & ADS1278_DMA_STATUS_ERROR_PENDING) != 0u ? 1u : 0u
    );
    printf(
        "dma_last_bresp : %u\n",
        (unsigned int)((dma_status & ADS1278_DMA_STATUS_LAST_BRESP_MASK)
            >> ADS1278_DMA_STATUS_LAST_BRESP_SHIFT)
    );
    printf("dma_write_index: %u\n", dma_write_index & 0xffffu);
    printf("dma_wrap_count : %u\n", dma_wrap_count);
    printf("dma_error_count: %u\n", dma_error_count);
    printf("dma_irq_status : 0x%08x\n", dma_irq_status);
}

static int ads1278_ddr_open(
    ads1278_ddr_map *ddr,
    const char *path,
    uint32_t base_addr,
    uint32_t buffer_size
)
{
    const char *open_path = path;
    void *mapped;

    if (ddr == NULL) {
        errno = EINVAL;
        return -1;
    }

    if (open_path == NULL) {
        open_path = ADS1278_MMIO_DEFAULT_PATH;
    }
    if (buffer_size == 0u) {
        errno = EINVAL;
        return -1;
    }

    memset(ddr, 0, sizeof(*ddr));
    ddr->fd = open(open_path, O_RDWR | O_SYNC);
    if (ddr->fd < 0) {
        return -1;
    }

    ddr->map_size = buffer_size;
    mapped = mmap(
        NULL,
        ddr->map_size,
        PROT_READ | PROT_WRITE,
        MAP_SHARED,
        ddr->fd,
        base_addr
    );
    if (mapped == MAP_FAILED) {
        int saved_errno = errno;
        close(ddr->fd);
        ddr->fd = -1;
        errno = saved_errno;
        return -1;
    }

    ddr->words = (volatile uint32_t *)mapped;
    return 0;
}

static void ads1278_ddr_close(ads1278_ddr_map *ddr)
{
    if (ddr == NULL) {
        return;
    }

    if (ddr->words != NULL) {
        munmap((void *)ddr->words, ddr->map_size);
        ddr->words = NULL;
    }
    if (ddr->fd >= 0) {
        close(ddr->fd);
        ddr->fd = -1;
    }
    ddr->map_size = 0;
}

int main(int argc, char **argv)
{
    const char *mem_path;
    const char *command;
    ads1278_mmio mmio;
    ads1278_snapshot snapshot;
    int argi;

    mem_path = ADS1278_MMIO_DEFAULT_PATH;
    command = "snapshot";
    memset(&mmio, 0, sizeof(mmio));
    mmio.fd = -1;

    argi = 1;
    if (argi < argc && strcmp(argv[argi], "--mem-path") == 0) {
        if ((argi + 1) >= argc) {
            print_usage(argv[0]);
            return EXIT_FAILURE;
        }
        mem_path = argv[argi + 1];
        argi += 2;
    }

    if (argi < argc) {
        command = argv[argi++];
    }

    if (ads1278_mmio_open(&mmio, mem_path) != 0) {
        perror("open mmio");
        return EXIT_FAILURE;
    }

    if (strcmp(command, "snapshot") == 0) {
        if (ads1278_mmio_read_snapshot(&mmio, &snapshot, NULL, ADS1278_SNAPSHOT_RETRY_LIMIT) < 0) {
            perror("read snapshot");
            ads1278_mmio_close(&mmio);
            return EXIT_FAILURE;
        }
        print_snapshot(&snapshot);
        ads1278_mmio_close(&mmio);
        return EXIT_SUCCESS;
    }

    if (strcmp(command, "dma-status") == 0) {
        print_dma_status(&mmio);
        ads1278_mmio_close(&mmio);
        return EXIT_SUCCESS;
    }

    if (strcmp(command, "read") == 0) {
        uint32_t offset;

        if (argi >= argc || parse_u32(argv[argi], &offset) != 0) {
            print_usage(argv[0]);
            ads1278_mmio_close(&mmio);
            return EXIT_FAILURE;
        }
        printf("0x%08x\n", ads1278_mmio_read32(&mmio, offset));
        ads1278_mmio_close(&mmio);
        return EXIT_SUCCESS;
    }

    if (strcmp(command, "write") == 0) {
        uint32_t offset;
        uint32_t value;

        if ((argi + 1) >= argc
            || parse_u32(argv[argi], &offset) != 0
            || parse_u32(argv[argi + 1], &value) != 0) {
            print_usage(argv[0]);
            ads1278_mmio_close(&mmio);
            return EXIT_FAILURE;
        }
        ads1278_mmio_write32(&mmio, offset, value);
        printf("wrote 0x%08x to 0x%08x\n", value, offset);
        ads1278_mmio_close(&mmio);
        return EXIT_SUCCESS;
    }

    if (strcmp(command, "ddr-read") == 0) {
        uint32_t word_index;
        uint32_t ddr_base_addr;
        uint32_t ddr_buf_size;
        ads1278_ddr_map ddr;
        size_t word_count;

        if (argi >= argc || parse_u32(argv[argi], &word_index) != 0) {
            print_usage(argv[0]);
            ads1278_mmio_close(&mmio);
            return EXIT_FAILURE;
        }

        if (ads1278_dma_get_buffer_config(&mmio, &ddr_base_addr, &ddr_buf_size) != 0) {
            perror("read dma buffer config");
            ads1278_mmio_close(&mmio);
            return EXIT_FAILURE;
        }
        ads1278_mmio_close(&mmio);

        ddr.fd = -1;
        if (ads1278_ddr_open(&ddr, mem_path, ddr_base_addr, ddr_buf_size) != 0) {
            perror("open ddr");
            return EXIT_FAILURE;
        }

        word_count = ddr.map_size / sizeof(uint32_t);
        if ((size_t)word_index >= word_count) {
            fprintf(stderr, "word index out of range (max %zu)\n", word_count - 1u);
            ads1278_ddr_close(&ddr);
            return EXIT_FAILURE;
        }

        printf("[%u] 0x%08x\n", word_index, ddr.words[word_index]);
        ads1278_ddr_close(&ddr);
        return EXIT_SUCCESS;
    }

    if (strcmp(command, "ddr-dump") == 0) {
        uint32_t requested_words;
        uint32_t ddr_base_addr;
        uint32_t ddr_buf_size;
        ads1278_ddr_map ddr;
        size_t word_count;
        size_t dump_count;
        size_t index;

        requested_words = 16u;
        if (argi < argc && parse_u32(argv[argi], &requested_words) != 0) {
            print_usage(argv[0]);
            ads1278_mmio_close(&mmio);
            return EXIT_FAILURE;
        }

        if (ads1278_dma_get_buffer_config(&mmio, &ddr_base_addr, &ddr_buf_size) != 0) {
            perror("read dma buffer config");
            ads1278_mmio_close(&mmio);
            return EXIT_FAILURE;
        }
        ads1278_mmio_close(&mmio);

        ddr.fd = -1;
        if (ads1278_ddr_open(&ddr, mem_path, ddr_base_addr, ddr_buf_size) != 0) {
            perror("open ddr");
            return EXIT_FAILURE;
        }

        word_count = ddr.map_size / sizeof(uint32_t);
        dump_count = requested_words;
        if (dump_count > word_count) {
            dump_count = word_count;
        }

        for (index = 0; index < dump_count; ++index) {
            printf("[%04zu] 0x%08x\n", index, ddr.words[index]);
        }

        ads1278_ddr_close(&ddr);
        return EXIT_SUCCESS;
    }

    print_usage(argv[0]);
    ads1278_mmio_close(&mmio);
    return EXIT_FAILURE;
}
