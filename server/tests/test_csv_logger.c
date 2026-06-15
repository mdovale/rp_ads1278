#include "csv_logger.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

static int file_contains(const char *path, const char *needle)
{
    char buffer[1024];
    FILE *file;
    size_t read_count;

    file = fopen(path, "r");
    assert(file != NULL);
    read_count = fread(buffer, 1u, sizeof(buffer) - 1u, file);
    fclose(file);
    buffer[read_count] = '\0';
    return strstr(buffer, needle) != NULL;
}

static ads1278_message sample_message(void)
{
    ads1278_message message;
    unsigned int channel;

    memset(&message, 0, sizeof(message));
    message.msg_type = ADS1278_MSG_SAMPLE;
    message.msg_seq = 42u;
    message.status_raw = 0x00070001u;
    message.ctrl_raw = 0x00000002u;
    message.extclk_div = 625u;
    message.mod_div = 6250000u;
    for (channel = 0u; channel < ADS1278_CHANNEL_COUNT; ++channel) {
        message.channels[channel] = (int32_t)(channel + 1u);
    }
    return message;
}

static void make_temp_dir(char *dir, size_t dir_size)
{
    int written;

    written = snprintf(dir, dir_size, "/tmp/ads1278_csv_test_%ld", (long)getpid());
    assert(written > 0 && (size_t)written < dir_size);
    assert(mkdir(dir, 0775) == 0);
}

static void test_start_writes_header_and_selected_channels(void)
{
    ads1278_csv_logger logger;
    ads1278_message message;
    char dir[128];
    char path[512];
    uint32_t rows;

    make_temp_dir(dir, sizeof(dir));
    ads1278_csv_logger_init(&logger);

    assert(ads1278_csv_logger_start(&logger, dir, 0x11u, "noise_run_01.csv") == 0);
    assert(logger.active);
    snprintf(path, sizeof(path), "%s/noise_run_01.csv", dir);
    assert(strcmp(logger.path, path) == 0);
    assert(file_contains(path, "host_timestamp,msg_seq,frame_cnt,status_raw,ctrl_raw,extclk_div,mod_div,ch1,ch5\n"));

    message = sample_message();
    assert(ads1278_csv_logger_write_message(&logger, &message) == 0);
    rows = ads1278_csv_logger_close(&logger);

    assert(rows == 1u);
    assert(file_contains(path, ",42,7,458753,2,625,6250000,1,5\n"));
    assert(unlink(path) == 0);
    assert(rmdir(dir) == 0);
}

static void test_invalid_filename_rejected(void)
{
    ads1278_csv_logger logger;
    char dir[128];

    make_temp_dir(dir, sizeof(dir));
    ads1278_csv_logger_init(&logger);
    assert(ads1278_csv_logger_start(&logger, dir, 0xffu, "../bad.csv") != 0);
    assert(!logger.active);
    assert(rmdir(dir) == 0);
}

int main(void)
{
    test_start_writes_header_and_selected_channels();
    test_invalid_filename_rejected();
    return 0;
}
