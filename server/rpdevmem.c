#include "memory_map.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void print_usage(const char *argv0)
{
    fprintf(stderr,
        "Usage: %s [--mem-path PATH] [snapshot | read OFFSET | write OFFSET VALUE]\n",
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

    print_usage(argv[0]);
    ads1278_mmio_close(&mmio);
    return EXIT_FAILURE;
}
