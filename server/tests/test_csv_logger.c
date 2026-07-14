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

static uint32_t file_data_row_count(const char *path)
{
    FILE *file;
    int ch;
    uint32_t line_count;

    file = fopen(path, "r");
    assert(file != NULL);
    line_count = 0u;
    while ((ch = fgetc(file)) != EOF) {
        if (ch == '\n') {
            line_count += 1u;
        }
    }
    fclose(file);
    assert(line_count > 0u);
    return line_count - 1u;
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

static ads1278_bulk_frame sample_bulk_frame(uint32_t frame_count, int32_t ch1)
{
    ads1278_bulk_frame frame;
    unsigned int channel;

    memset(&frame, 0, sizeof(frame));
    frame.frame_count = frame_count;
    frame.status_raw = 0x00000001u;
    for (channel = 0u; channel < ADS1278_CHANNEL_COUNT; ++channel) {
        frame.channels[channel] = (int32_t)(channel + 1u);
    }
    frame.channels[0] = ch1;
    return frame;
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

    assert(ads1278_csv_logger_start(&logger, dir, 0x11u, 0u, "noise_run_01.csv") == 0);
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
    assert(ads1278_csv_logger_start(&logger, dir, 0xffu, 0u, "../bad.csv") != 0);
    assert(!logger.active);
    assert(rmdir(dir) == 0);
}

static void test_demod_rate_start_requires_demod_control(void)
{
    ads1278_csv_logger logger;
    char dir[128];

    make_temp_dir(dir, sizeof(dir));
    ads1278_csv_logger_init(&logger);
    assert(ads1278_csv_logger_start(
        &logger,
        dir,
        ADS1278_LOCAL_LOG_CH1_ONLY | ADS1278_LOCAL_LOG_DEMOD_RATE_FLAG,
        0x00000002u,
        "demod.csv"
    ) != 0);
    assert(!logger.active);
    assert(rmdir(dir) == 0);
}

static void test_demod_rate_skips_duplicate_ch1_frames(void)
{
    ads1278_csv_logger logger;
    ads1278_bulk_frame frame;
    char dir[128];
    char path[512];
    uint32_t frame_count;
    uint32_t rows;

    make_temp_dir(dir, sizeof(dir));
    ads1278_csv_logger_init(&logger);
    assert(ads1278_csv_logger_start(
        &logger,
        dir,
        ADS1278_LOCAL_LOG_CH1_ONLY | ADS1278_LOCAL_LOG_DEMOD_RATE_FLAG,
        0x00000006u,
        "demod_skip.csv"
    ) == 0);
    snprintf(path, sizeof(path), "%s/demod_skip.csv", dir);

    for (frame_count = 1u; frame_count <= 11u; ++frame_count) {
        frame = sample_bulk_frame(frame_count, 1234);
        assert(ads1278_csv_logger_write_bulk_frame(&logger, 100u + frame_count, 0x6u, 1u, 5120u, &frame) == 0);
    }
    rows = ads1278_csv_logger_close(&logger);

    assert(rows == 2u);
    assert(file_data_row_count(path) == 2u);
    assert(unlink(path) == 0);
    assert(rmdir(dir) == 0);
}

static void test_demod_rate_writes_changed_ch1(void)
{
    ads1278_csv_logger logger;
    ads1278_bulk_frame frame;
    char dir[128];
    char path[512];
    uint32_t rows;

    make_temp_dir(dir, sizeof(dir));
    ads1278_csv_logger_init(&logger);
    assert(ads1278_csv_logger_start(
        &logger,
        dir,
        ADS1278_LOCAL_LOG_CH1_ONLY | ADS1278_LOCAL_LOG_DEMOD_RATE_FLAG,
        0x00000006u,
        "demod_change.csv"
    ) == 0);
    snprintf(path, sizeof(path), "%s/demod_change.csv", dir);

    frame = sample_bulk_frame(1u, 1234);
    assert(ads1278_csv_logger_write_bulk_frame(&logger, 200u, 0x6u, 1u, 5120u, &frame) == 0);
    frame = sample_bulk_frame(2u, 1235);
    assert(ads1278_csv_logger_write_bulk_frame(&logger, 201u, 0x6u, 1u, 5120u, &frame) == 0);
    rows = ads1278_csv_logger_close(&logger);

    assert(rows == 2u);
    assert(file_data_row_count(path) == 2u);
    assert(unlink(path) == 0);
    assert(rmdir(dir) == 0);
}

static void test_demod_rate_skips_same_frame_even_when_ch1_changes(void)
{
    ads1278_csv_logger logger;
    ads1278_bulk_frame frame;
    char dir[128];
    char path[512];
    uint32_t rows;

    make_temp_dir(dir, sizeof(dir));
    ads1278_csv_logger_init(&logger);
    assert(ads1278_csv_logger_start(
        &logger,
        dir,
        ADS1278_LOCAL_LOG_CH1_ONLY | ADS1278_LOCAL_LOG_DEMOD_RATE_FLAG,
        0x00000006u,
        "demod_same_frame.csv"
    ) == 0);
    snprintf(path, sizeof(path), "%s/demod_same_frame.csv", dir);

    frame = sample_bulk_frame(1u, 1234);
    assert(ads1278_csv_logger_write_bulk_frame(&logger, 200u, 0x6u, 1u, 5120u, &frame) == 0);
    frame = sample_bulk_frame(1u, 1235);
    assert(ads1278_csv_logger_write_bulk_frame(&logger, 201u, 0x6u, 1u, 5120u, &frame) == 0);
    rows = ads1278_csv_logger_close(&logger);

    assert(rows == 1u);
    assert(file_data_row_count(path) == 1u);
    assert(unlink(path) == 0);
    assert(rmdir(dir) == 0);
}

static void test_demod_rate_falls_back_to_full_rate_without_demod_control(void)
{
    ads1278_csv_logger logger;
    ads1278_bulk_frame frame;
    char dir[128];
    char path[512];
    uint32_t frame_count;
    uint32_t rows;

    make_temp_dir(dir, sizeof(dir));
    ads1278_csv_logger_init(&logger);
    assert(ads1278_csv_logger_start(
        &logger,
        dir,
        ADS1278_LOCAL_LOG_CH1_ONLY | ADS1278_LOCAL_LOG_DEMOD_RATE_FLAG,
        0x00000006u,
        "demod_full_rate.csv"
    ) == 0);
    snprintf(path, sizeof(path), "%s/demod_full_rate.csv", dir);

    for (frame_count = 1u; frame_count <= 3u; ++frame_count) {
        frame = sample_bulk_frame(frame_count, 1234);
        assert(ads1278_csv_logger_write_bulk_frame(&logger, 300u + frame_count, 0x2u, 1u, 5120u, &frame) == 0);
    }
    rows = ads1278_csv_logger_close(&logger);

    assert(rows == 3u);
    assert(file_data_row_count(path) == 3u);
    assert(unlink(path) == 0);
    assert(rmdir(dir) == 0);
}

int main(void)
{
    test_start_writes_header_and_selected_channels();
    test_invalid_filename_rejected();
    test_demod_rate_start_requires_demod_control();
    test_demod_rate_skips_duplicate_ch1_frames();
    test_demod_rate_writes_changed_ch1();
    test_demod_rate_skips_same_frame_even_when_ch1_changes();
    test_demod_rate_falls_back_to_full_rate_without_demod_control();
    return 0;
}
