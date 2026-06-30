#ifndef ADS1278_CSV_LOGGER_H
#define ADS1278_CSV_LOGGER_H

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "protocol.h"

#define ADS1278_USB_MOUNT_POINT "/mnt/usb"
#define ADS1278_LOCAL_LOG_DIR ADS1278_USB_MOUNT_POINT "/ads1278/logs"
#define ADS1278_LOCAL_LOG_FILENAME_MAX 63u
#define ADS1278_LOCAL_LOG_PATH_HINT ADS1278_LOCAL_LOG_DIR "/<filename>.csv"
#define ADS1278_LOCAL_LOG_ALL_CHANNELS 0u
#define ADS1278_LOCAL_LOG_CHANNEL_MASK 0xffu
#define ADS1278_LOCAL_LOG_DEMOD_RATE_FLAG 0x100u
#define ADS1278_LOCAL_LOG_VALUE_MASK (ADS1278_LOCAL_LOG_CHANNEL_MASK | ADS1278_LOCAL_LOG_DEMOD_RATE_FLAG)
#define ADS1278_LOCAL_LOG_CH8_ONLY (1u << 7)

typedef struct {
    FILE *file;
    char path[512];
    uint32_t rows_written;
    uint32_t channel_mask;
    uint32_t last_demod_frame_cnt;
    int32_t last_demod_ch8;
    bool active;
    bool demod_rate_requested;
    bool have_last_demod_row;
} ads1278_csv_logger;

void ads1278_csv_logger_init(ads1278_csv_logger *logger);
int ads1278_csv_logger_start(
    ads1278_csv_logger *logger,
    const char *directory,
    uint32_t channel_mask,
    uint32_t ctrl_raw,
    const char *filename
);
uint32_t ads1278_csv_logger_close(ads1278_csv_logger *logger);
int ads1278_csv_logger_write_message(
    ads1278_csv_logger *logger,
    const ads1278_message *message
);
int ads1278_csv_logger_write_bulk_frame(
    ads1278_csv_logger *logger,
    uint32_t msg_seq,
    uint32_t ctrl_raw,
    uint32_t extclk_div,
    uint32_t mod_div,
    const ads1278_bulk_frame *frame
);

#endif
