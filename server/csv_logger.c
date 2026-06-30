#include "csv_logger.h"

#include "memory_map.h"

#include <errno.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <time.h>

static uint32_t ads1278_normalize_channel_mask(uint32_t channel_mask)
{
    if ((channel_mask & ADS1278_LOCAL_LOG_CHANNEL_MASK) == 0u) {
        return ADS1278_LOCAL_LOG_CHANNEL_MASK;
    }
    return channel_mask & ADS1278_LOCAL_LOG_CHANNEL_MASK;
}

static bool ads1278_logger_channel_enabled(uint32_t channel_mask, unsigned int channel)
{
    return (channel_mask & (1u << channel)) != 0u;
}

static bool ads1278_ctrl_has_demod_acquisition(uint32_t ctrl_raw)
{
    const uint32_t required = ADS1278_CTRL_ENABLE | ADS1278_CTRL_DEMOD_ENABLE;

    return (ctrl_raw & required) == required;
}

static uint32_t ads1278_frames_per_demod(uint32_t extclk_div, uint32_t mod_div)
{
    uint64_t denominator;
    uint64_t frames;

    if (extclk_div == 0u || mod_div < 2u) {
        return 1u;
    }

    denominator = (uint64_t)extclk_div * 512ull;
    if (denominator == 0u) {
        return 1u;
    }

    frames = ((uint64_t)mod_div + (denominator / 2u)) / denominator;
    if (frames == 0u) {
        return 1u;
    }
    if (frames > UINT32_MAX) {
        return UINT32_MAX;
    }
    return (uint32_t)frames;
}

static bool ads1278_csv_logger_demod_gate_active(
    const ads1278_csv_logger *logger,
    uint32_t ctrl_raw,
    uint32_t mod_div
)
{
    return logger != NULL
        && logger->demod_rate_requested
        && logger->channel_mask == ADS1278_LOCAL_LOG_CH8_ONLY
        && ads1278_ctrl_has_demod_acquisition(ctrl_raw)
        && mod_div >= 2u;
}

static bool ads1278_csv_logger_should_write_row(
    ads1278_csv_logger *logger,
    uint32_t frame_cnt,
    uint32_t ctrl_raw,
    uint32_t extclk_div,
    uint32_t mod_div,
    const int32_t channels[ADS1278_CHANNEL_COUNT]
)
{
    uint32_t frames_per_demod;
    uint32_t frames_since_last_row;
    int32_t ch8;

    if (!ads1278_csv_logger_demod_gate_active(logger, ctrl_raw, mod_div)) {
        logger->have_last_demod_row = false;
        return true;
    }

    ch8 = channels[ADS1278_CHANNEL_COUNT - 1u];
    if (!logger->have_last_demod_row) {
        logger->last_demod_frame_cnt = frame_cnt;
        logger->last_demod_ch8 = ch8;
        logger->have_last_demod_row = true;
        return true;
    }

    frames_per_demod = ads1278_frames_per_demod(extclk_div, mod_div);
    frames_since_last_row = (frame_cnt - logger->last_demod_frame_cnt) & 0xffffu;
    if (frames_since_last_row == 0u) {
        return false;
    }
    if (ch8 != logger->last_demod_ch8 || frames_since_last_row >= frames_per_demod) {
        logger->last_demod_frame_cnt = frame_cnt;
        logger->last_demod_ch8 = ch8;
        return true;
    }

    return false;
}

static int ads1278_mkdir_if_needed(const char *path)
{
    if (mkdir(path, 0775) == 0 || errno == EEXIST) {
        return 0;
    }
    return -1;
}

static int ads1278_make_log_directory(const char *directory)
{
    char buffer[512];
    size_t len;
    size_t index;

    if (directory == NULL || directory[0] == '\0') {
        errno = EINVAL;
        return -1;
    }

    len = strlen(directory);
    if (len >= sizeof(buffer)) {
        errno = ENAMETOOLONG;
        return -1;
    }

    memcpy(buffer, directory, len + 1u);
    for (index = 1u; index < len; ++index) {
        if (buffer[index] == '/') {
            buffer[index] = '\0';
            if (buffer[0] != '\0' && ads1278_mkdir_if_needed(buffer) != 0) {
                return -1;
            }
            buffer[index] = '/';
        }
    }
    return ads1278_mkdir_if_needed(buffer);
}

static bool ads1278_path_uses_usb_mount(const char *directory)
{
    size_t mount_len;

    if (directory == NULL) {
        return false;
    }
    mount_len = strlen(ADS1278_USB_MOUNT_POINT);
    return strncmp(directory, ADS1278_USB_MOUNT_POINT, mount_len) == 0
        && (directory[mount_len] == '\0' || directory[mount_len] == '/');
}

static int ads1278_verify_usb_mount(const char *directory)
{
    struct stat mount_stat;
    struct stat parent_stat;

    if (!ads1278_path_uses_usb_mount(directory)) {
        return 0;
    }
    if (stat(ADS1278_USB_MOUNT_POINT, &mount_stat) != 0) {
        return -1;
    }
    if (stat("/mnt", &parent_stat) != 0) {
        return -1;
    }
    if (mount_stat.st_dev == parent_stat.st_dev) {
        errno = ENODEV;
        return -1;
    }
    return 0;
}

static int ads1278_verify_writable_space(const char *directory)
{
    struct statvfs fs;

    if (statvfs(directory, &fs) != 0) {
        return -1;
    }
    if (fs.f_bavail == 0u) {
        errno = ENOSPC;
        return -1;
    }
    return 0;
}

static int ads1278_format_utc_timestamp(char *buffer, size_t buffer_size)
{
    struct timespec now;
    struct tm utc_tm;
    size_t written;

    if (buffer == NULL || buffer_size == 0u) {
        errno = EINVAL;
        return -1;
    }
    if (clock_gettime(CLOCK_REALTIME, &now) != 0) {
        return -1;
    }
    if (gmtime_r(&now.tv_sec, &utc_tm) == NULL) {
        return -1;
    }

    written = strftime(buffer, buffer_size, "%Y-%m-%dT%H:%M:%S", &utc_tm);
    if (written == 0u) {
        errno = ENOSPC;
        return -1;
    }
    if (snprintf(buffer + written, buffer_size - written, ".%09ldZ", now.tv_nsec) >= (int)(buffer_size - written)) {
        errno = ENOSPC;
        return -1;
    }
    return 0;
}

static bool ads1278_is_safe_log_filename_char(char ch)
{
    return (ch >= 'A' && ch <= 'Z')
        || (ch >= 'a' && ch <= 'z')
        || (ch >= '0' && ch <= '9')
        || ch == '.'
        || ch == '_'
        || ch == '-';
}

static int ads1278_validate_log_filename(const char *filename)
{
    size_t len;
    size_t index;

    if (filename == NULL || filename[0] == '\0') {
        return 0;
    }

    len = strlen(filename);
    if (len == 0u || len > ADS1278_LOCAL_LOG_FILENAME_MAX) {
        errno = EINVAL;
        return -1;
    }
    for (index = 0u; index < len; ++index) {
        if (filename[index] == '/' || filename[index] == '\\') {
            errno = EINVAL;
            return -1;
        }
        if (!ads1278_is_safe_log_filename_char(filename[index])) {
            errno = EINVAL;
            return -1;
        }
    }
    if (len < 4u
        || filename[len - 4u] != '.'
        || filename[len - 3u] != 'c'
        || filename[len - 2u] != 's'
        || filename[len - 1u] != 'v') {
        errno = EINVAL;
        return -1;
    }
    return 0;
}

static int ads1278_format_filename_timestamp(char *buffer, size_t buffer_size)
{
    time_t now;
    struct tm utc_tm;
    size_t written;

    if (buffer == NULL || buffer_size == 0u) {
        errno = EINVAL;
        return -1;
    }

    now = time(NULL);
    if (now == (time_t)-1 || gmtime_r(&now, &utc_tm) == NULL) {
        return -1;
    }
    written = strftime(buffer, buffer_size, "ads1278_%Y%m%d_%H%M%S.csv", &utc_tm);
    if (written == 0u) {
        errno = ENOSPC;
        return -1;
    }
    return 0;
}

static int ads1278_csv_write_escaped(FILE *file, const char *value)
{
    const char *cursor;

    if (file == NULL || value == NULL) {
        errno = EINVAL;
        return -1;
    }

    if (fputc('"', file) == EOF) {
        return -1;
    }
    for (cursor = value; *cursor != '\0'; ++cursor) {
        if (*cursor == '"' && fputc('"', file) == EOF) {
            return -1;
        }
        if (fputc(*cursor, file) == EOF) {
            return -1;
        }
    }
    if (fputc('"', file) == EOF) {
        return -1;
    }
    return 0;
}

#if defined(__GNUC__) || defined(__clang__)
static int ads1278_csv_printf(FILE *file, const char *format, ...) __attribute__((format(printf, 2, 3)));
#endif
static int ads1278_csv_printf(FILE *file, const char *format, ...)
{
    va_list args;
    int result;

    va_start(args, format);
    result = vfprintf(file, format, args);
    va_end(args);
    return (result < 0) ? -1 : 0;
}

static int ads1278_csv_logger_write_header(ads1278_csv_logger *logger)
{
    unsigned int channel;

    if (ads1278_csv_printf(
            logger->file,
            "host_timestamp,msg_seq,frame_cnt,status_raw,ctrl_raw,extclk_div,mod_div"
        ) != 0) {
        return -1;
    }
    for (channel = 0u; channel < ADS1278_CHANNEL_COUNT; ++channel) {
        if (ads1278_logger_channel_enabled(logger->channel_mask, channel)
            && ads1278_csv_printf(logger->file, ",ch%u", channel + 1u) != 0) {
            return -1;
        }
    }
    if (fputc('\n', logger->file) == EOF || fflush(logger->file) != 0) {
        return -1;
    }
    return 0;
}

static int ads1278_csv_logger_write_row(
    ads1278_csv_logger *logger,
    uint32_t msg_seq,
    uint32_t frame_cnt,
    uint32_t status_raw,
    uint32_t ctrl_raw,
    uint32_t extclk_div,
    uint32_t mod_div,
    const int32_t channels[ADS1278_CHANNEL_COUNT]
)
{
    char timestamp[64];
    unsigned int channel;

    if (logger == NULL || !logger->active || logger->file == NULL || channels == NULL) {
        return 0;
    }
    if (!ads1278_csv_logger_should_write_row(logger, frame_cnt, ctrl_raw, extclk_div, mod_div, channels)) {
        return 0;
    }
    if (ads1278_format_utc_timestamp(timestamp, sizeof(timestamp)) != 0) {
        return -1;
    }

    if (ads1278_csv_write_escaped(logger->file, timestamp) != 0
        || ads1278_csv_printf(
            logger->file,
            ",%u,%u,%u,%u,%u,%u",
            msg_seq,
            frame_cnt,
            status_raw,
            ctrl_raw,
            extclk_div,
            mod_div
        ) != 0) {
        return -1;
    }

    for (channel = 0u; channel < ADS1278_CHANNEL_COUNT; ++channel) {
        if (ads1278_logger_channel_enabled(logger->channel_mask, channel)
            && ads1278_csv_printf(logger->file, ",%d", channels[channel]) != 0) {
            return -1;
        }
    }
    if (fputc('\n', logger->file) == EOF) {
        return -1;
    }
    logger->rows_written += 1u;
    if ((logger->rows_written % 256u) == 0u && fflush(logger->file) != 0) {
        return -1;
    }
    return 0;
}

void ads1278_csv_logger_init(ads1278_csv_logger *logger)
{
    if (logger == NULL) {
        return;
    }
    memset(logger, 0, sizeof(*logger));
}

int ads1278_csv_logger_start(
    ads1278_csv_logger *logger,
    const char *directory,
    uint32_t channel_mask,
    uint32_t ctrl_raw,
    const char *filename
)
{
    char resolved_filename[64];
    bool demod_rate_requested;

    if (logger == NULL) {
        errno = EINVAL;
        return -1;
    }

    ads1278_csv_logger_close(logger);
    demod_rate_requested = (channel_mask & ADS1278_LOCAL_LOG_DEMOD_RATE_FLAG) != 0u;
    if (demod_rate_requested && !ads1278_ctrl_has_demod_acquisition(ctrl_raw)) {
        errno = EINVAL;
        return -1;
    }
    if (directory == NULL || directory[0] == '\0') {
        directory = ADS1278_LOCAL_LOG_DIR;
    }
    if (ads1278_verify_usb_mount(directory) != 0) {
        return -1;
    }
    if (ads1278_make_log_directory(directory) != 0) {
        return -1;
    }
    if (ads1278_verify_writable_space(directory) != 0) {
        return -1;
    }
    if (filename != NULL && filename[0] != '\0') {
        if (ads1278_validate_log_filename(filename) != 0) {
            return -1;
        }
        if (snprintf(resolved_filename, sizeof(resolved_filename), "%s", filename)
            >= (int)sizeof(resolved_filename)) {
            errno = ENAMETOOLONG;
            return -1;
        }
    } else if (ads1278_format_filename_timestamp(resolved_filename, sizeof(resolved_filename)) != 0) {
        return -1;
    }
    if (snprintf(logger->path, sizeof(logger->path), "%s/%s", directory, resolved_filename) >= (int)sizeof(logger->path)) {
        logger->path[0] = '\0';
        errno = ENAMETOOLONG;
        return -1;
    }

    logger->file = fopen(logger->path, "w");
    if (logger->file == NULL) {
        logger->path[0] = '\0';
        return -1;
    }
    logger->channel_mask = ads1278_normalize_channel_mask(channel_mask);
    logger->rows_written = 0u;
    logger->last_demod_frame_cnt = 0u;
    logger->last_demod_ch8 = 0;
    logger->demod_rate_requested = demod_rate_requested;
    logger->have_last_demod_row = false;
    logger->active = true;
    if (ads1278_csv_logger_write_header(logger) != 0) {
        int saved_errno = errno;
        ads1278_csv_logger_close(logger);
        errno = saved_errno;
        return -1;
    }
    return 0;
}

uint32_t ads1278_csv_logger_close(ads1278_csv_logger *logger)
{
    uint32_t rows_written;

    if (logger == NULL) {
        return 0u;
    }

    rows_written = logger->rows_written;
    if (logger->file != NULL) {
        fflush(logger->file);
        fclose(logger->file);
    }
    logger->file = NULL;
    logger->active = false;
    logger->rows_written = 0u;
    logger->channel_mask = ADS1278_LOCAL_LOG_ALL_CHANNELS;
    logger->last_demod_frame_cnt = 0u;
    logger->last_demod_ch8 = 0;
    logger->demod_rate_requested = false;
    logger->have_last_demod_row = false;
    logger->path[0] = '\0';
    return rows_written;
}

int ads1278_csv_logger_write_message(
    ads1278_csv_logger *logger,
    const ads1278_message *message
)
{
    if (message == NULL || message->msg_type != ADS1278_MSG_SAMPLE) {
        return 0;
    }
    return ads1278_csv_logger_write_row(
        logger,
        message->msg_seq,
        (message->status_raw >> 16) & 0xffffu,
        message->status_raw,
        message->ctrl_raw,
        message->extclk_div,
        message->mod_div,
        message->channels
    );
}

int ads1278_csv_logger_write_bulk_frame(
    ads1278_csv_logger *logger,
    uint32_t msg_seq,
    uint32_t ctrl_raw,
    uint32_t extclk_div,
    uint32_t mod_div,
    const ads1278_bulk_frame *frame
)
{
    uint32_t status_raw;

    if (frame == NULL) {
        return 0;
    }
    status_raw = (frame->status_raw & 0x0000ffffu) | ((frame->frame_count & 0xffffu) << 16);
    return ads1278_csv_logger_write_row(
        logger,
        msg_seq,
        frame->frame_count & 0xffffu,
        status_raw,
        ctrl_raw,
        extclk_div,
        mod_div,
        frame->channels
    );
}
