#include "server.h"

#include "cmd_parse.h"
#include "csv_logger.h"
#include "dma_frame.h"
#include "protocol.h"

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif

typedef struct {
    int fd;
    size_t map_size;
    volatile uint32_t *words;
} ads1278_ddr_map;

typedef struct {
    ads1278_ddr_map buffers[2];
    bool maps_open;
} ads1278_dma_state;

typedef struct {
    ads1278_mmio mmio;
    ads1278_dma_state dma;
    ads1278_snapshot snapshot;
    ads1278_cmd_parser parser;
    ads1278_server_stats stats;
    ads1278_csv_logger local_logger;
    struct timespec local_log_deadline;
    uint32_t pending_local_log_duration_s;
    char pending_local_log_filename[ADS1278_LOCAL_LOG_FILENAME_MAX + 1u];
    uint16_t last_streamed_frame_cnt;
    bool have_snapshot;
    bool local_log_deadline_valid;
    bool pending_local_log_filename_valid;
} ads1278_server_state;

static volatile sig_atomic_t g_stop_requested = 0;

#define ADS1278_LOCAL_LOG_FILENAME_CHUNK_SHIFT 24u
#define ADS1278_LOCAL_LOG_FILENAME_CHUNK_BYTES 3u
#define ADS1278_NS_PER_SEC 1000000000ull
#define ADS1278_NS_PER_MS 1000000ull
#define ADS1278_NS_PER_US 1000ull
#define ADS1278_DOUBLE_FDATA_INTERVAL_NS_PER_DIV 4096ull

static void ads1278_handle_stop_signal(int signo)
{
    (void)signo;
    g_stop_requested = 1;
}

static int ads1278_install_signal_handlers(void)
{
    struct sigaction action;

    memset(&action, 0, sizeof(action));
    action.sa_handler = ads1278_handle_stop_signal;
    sigemptyset(&action.sa_mask);
    action.sa_flags = 0;

    if (sigaction(SIGINT, &action, NULL) != 0) {
        return -1;
    }
    if (sigaction(SIGTERM, &action, NULL) != 0) {
        return -1;
    }
    return 0;
}

void ads1278_server_options_init(ads1278_server_options *options)
{
    if (options == NULL) {
        return;
    }

    options->mem_path = ADS1278_MMIO_DEFAULT_PATH;
    options->port = (uint16_t)ADS1278_SERVER_PORT;
    options->poll_timeout_ms = ADS1278_SERVER_POLL_TIMEOUT_MS;
    options->snapshot_retries = ADS1278_SNAPSHOT_RETRY_LIMIT;
    options->dma_mode = false;
    options->dma_bulk_mode = false;
    options->dma_base_addr = ADS1278_DMA_PHASE4_DDR_BASE;
    options->dma_buf_size = ADS1278_DMA_PHASE4_DDR_SIZE;
    options->local_log_dir = ADS1278_LOCAL_LOG_DIR;
}

void ads1278_server_print_usage(FILE *stream, const char *argv0)
{
    fprintf(
        stream,
        "Usage: %s [--port N] [--mem-path PATH] [--poll-ms N] [--snapshot-retries N] [--dma] [--dma-bulk] [--dma-base ADDR] [--dma-size BYTES] [--log-dir PATH]\n",
        argv0
    );
}

static int ads1278_parse_u16(const char *text, uint16_t *out_value)
{
    unsigned long value;
    char *end_ptr;

    if (text == NULL || out_value == NULL) {
        return -1;
    }

    errno = 0;
    value = strtoul(text, &end_ptr, 0);
    if (errno != 0 || end_ptr == text || *end_ptr != '\0' || value > 65535ul) {
        return -1;
    }

    *out_value = (uint16_t)value;
    return 0;
}

static int ads1278_parse_uint(const char *text, unsigned int *out_value)
{
    unsigned long value;
    char *end_ptr;

    if (text == NULL || out_value == NULL) {
        return -1;
    }

    errno = 0;
    value = strtoul(text, &end_ptr, 0);
    if (errno != 0 || end_ptr == text || *end_ptr != '\0') {
        return -1;
    }

    *out_value = (unsigned int)value;
    return 0;
}

static int ads1278_parse_u32(const char *text, uint32_t *out_value)
{
    unsigned long value;
    char *end_ptr;

    if (text == NULL || out_value == NULL) {
        return -1;
    }

    errno = 0;
    value = strtoul(text, &end_ptr, 0);
    if (errno != 0 || end_ptr == text || *end_ptr != '\0' || value > 0xfffffffful) {
        return -1;
    }

    *out_value = (uint32_t)value;
    return 0;
}

static int ads1278_set_nonblocking(int fd)
{
    int flags;

    flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0) {
        return -1;
    }
    if (fcntl(fd, F_SETFL, flags | O_NONBLOCK) != 0) {
        return -1;
    }

    return 0;
}

static void ads1278_dma_state_init(ads1278_dma_state *dma)
{
    if (dma == NULL) {
        return;
    }

    memset(dma, 0, sizeof(*dma));
    dma->buffers[0].fd = -1;
    dma->buffers[1].fd = -1;
}

/*
 * PL HP0 writes are not L1-coherent on Zynq. Match the devmem helper and
 * invalidate the CPU view before parsing DDR frames.
 */
static void ads1278_ddr_sync_for_cpu(void *addr, size_t len)
{
#if defined(__aarch64__) || defined(__arm__)
    __builtin___clear_cache((char *)addr, (char *)addr + len);
#endif
    __sync_synchronize();
}

static int ads1278_validate_dma_options(const ads1278_server_options *options)
{
    long page_size;

    if (options == NULL || options->dma_buf_size == 0u) {
        errno = EINVAL;
        return -1;
    }
    if ((options->dma_buf_size % ADS1278_DMA_FRAME_SIZE) != 0u) {
        errno = EINVAL;
        return -1;
    }

    page_size = sysconf(_SC_PAGESIZE);
    if (page_size <= 0) {
        page_size = 4096;
    }
    if ((options->dma_base_addr % (uint32_t)page_size) != 0u
        || (options->dma_buf_size % (uint32_t)page_size) != 0u) {
        errno = EINVAL;
        return -1;
    }

    return 0;
}

static int ads1278_ddr_open_map(
    ads1278_ddr_map *ddr,
    const char *path,
    uint32_t base_addr,
    uint32_t buffer_size
)
{
    const char *open_path;
    void *mapped;

    if (ddr == NULL || buffer_size == 0u) {
        errno = EINVAL;
        return -1;
    }

    open_path = (path != NULL) ? path : ADS1278_MMIO_DEFAULT_PATH;
    memset(ddr, 0, sizeof(*ddr));
    ddr->fd = open(open_path, O_RDWR | O_SYNC);
    if (ddr->fd < 0) {
        return -1;
    }

    ddr->map_size = buffer_size;
    mapped = mmap(NULL, ddr->map_size, PROT_READ | PROT_WRITE, MAP_SHARED, ddr->fd, base_addr);
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

static void ads1278_ddr_close_map(ads1278_ddr_map *ddr)
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
    ddr->map_size = 0u;
}

static int ads1278_dma_open_buffers(
    ads1278_dma_state *dma,
    const ads1278_server_options *options
)
{
    uint32_t buffer1_addr;

    if (dma == NULL || options == NULL) {
        errno = EINVAL;
        return -1;
    }
    if (ads1278_validate_dma_options(options) != 0) {
        return -1;
    }

    buffer1_addr = options->dma_base_addr + options->dma_buf_size;
    if (buffer1_addr < options->dma_base_addr) {
        errno = EINVAL;
        return -1;
    }

    if (ads1278_ddr_open_map(&dma->buffers[0], options->mem_path, options->dma_base_addr, options->dma_buf_size) != 0) {
        return -1;
    }
    if (ads1278_ddr_open_map(&dma->buffers[1], options->mem_path, buffer1_addr, options->dma_buf_size) != 0) {
        int saved_errno = errno;
        ads1278_ddr_close_map(&dma->buffers[0]);
        errno = saved_errno;
        return -1;
    }

    dma->maps_open = true;
    return 0;
}

static void ads1278_dma_close_buffers(ads1278_dma_state *dma)
{
    if (dma == NULL) {
        return;
    }
    ads1278_ddr_close_map(&dma->buffers[0]);
    ads1278_ddr_close_map(&dma->buffers[1]);
    dma->maps_open = false;
}

static int ads1278_get_monotonic_time(struct timespec *now)
{
    if (now == NULL) {
        errno = EINVAL;
        return -1;
    }

    return clock_gettime(CLOCK_MONOTONIC, now);
}

static uint64_t ads1278_timespec_to_ns(const struct timespec *value)
{
    return ((uint64_t)value->tv_sec * ADS1278_NS_PER_SEC) + (uint64_t)value->tv_nsec;
}

static void ads1278_ns_to_timespec(uint64_t total_ns, struct timespec *value)
{
    value->tv_sec = (time_t)(total_ns / ADS1278_NS_PER_SEC);
    value->tv_nsec = (long)(total_ns % ADS1278_NS_PER_SEC);
}

static void ads1278_ns_to_timeval(uint64_t total_ns, struct timeval *value)
{
    value->tv_sec = (time_t)(total_ns / ADS1278_NS_PER_SEC);
    value->tv_usec = (suseconds_t)((total_ns % ADS1278_NS_PER_SEC) / ADS1278_NS_PER_US);
}

static uint64_t ads1278_compute_sample_interval_ns(
    const ads1278_server_state *state,
    const ads1278_server_options *options
)
{
    uint32_t extclk_div;
    uint64_t interval_ns;

    extclk_div = state->snapshot.extclk_div;
    if (extclk_div == 0u) {
        extclk_div = 1u;
    }

    interval_ns = (uint64_t)extclk_div * ADS1278_DOUBLE_FDATA_INTERVAL_NS_PER_DIV;
    if (options->poll_timeout_ms > 0) {
        uint64_t max_interval_ns;

        max_interval_ns = (uint64_t)options->poll_timeout_ms * ADS1278_NS_PER_MS;
        if (max_interval_ns < interval_ns) {
            interval_ns = max_interval_ns;
        }
    }

    return interval_ns;
}

static int ads1278_set_next_sample_deadline(
    struct timespec *deadline,
    const ads1278_server_state *state,
    const ads1278_server_options *options
)
{
    uint64_t now_ns;
    struct timespec now;

    if (deadline == NULL || state == NULL || options == NULL) {
        errno = EINVAL;
        return -1;
    }

    if (ads1278_get_monotonic_time(&now) != 0) {
        return -1;
    }

    now_ns = ads1278_timespec_to_ns(&now);
    ads1278_ns_to_timespec(now_ns + ads1278_compute_sample_interval_ns(state, options), deadline);
    return 0;
}

static uint64_t ads1278_time_until_deadline_ns(const struct timespec *deadline)
{
    uint64_t now_ns;
    uint64_t deadline_ns;
    struct timespec now;

    if (deadline == NULL) {
        return 0u;
    }

    if (ads1278_get_monotonic_time(&now) != 0) {
        return 0u;
    }

    now_ns = ads1278_timespec_to_ns(&now);
    deadline_ns = ads1278_timespec_to_ns(deadline);
    if (deadline_ns <= now_ns) {
        return 0u;
    }

    return deadline_ns - now_ns;
}

static void ads1278_clear_local_log_deadline(ads1278_server_state *state)
{
    if (state == NULL) {
        return;
    }
    state->pending_local_log_duration_s = 0u;
    state->local_log_deadline_valid = false;
}

static int ads1278_set_local_log_deadline(
    ads1278_server_state *state,
    uint32_t duration_s
)
{
    uint64_t now_ns;
    struct timespec now;

    if (state == NULL) {
        errno = EINVAL;
        return -1;
    }

    state->pending_local_log_duration_s = duration_s;
    state->local_log_deadline_valid = false;
    if (duration_s == 0u) {
        return 0;
    }

    if (ads1278_get_monotonic_time(&now) != 0) {
        return -1;
    }
    now_ns = ads1278_timespec_to_ns(&now);
    ads1278_ns_to_timespec(now_ns + ((uint64_t)duration_s * ADS1278_NS_PER_SEC), &state->local_log_deadline);
    state->local_log_deadline_valid = true;
    return 0;
}

static bool ads1278_local_log_should_continue_unattended(const ads1278_server_state *state)
{
    return state != NULL
        && state->local_logger.active
        && state->local_log_deadline_valid;
}

static bool ads1278_local_log_deadline_expired(const ads1278_server_state *state)
{
    return state != NULL
        && state->local_logger.active
        && state->local_log_deadline_valid
        && ads1278_time_until_deadline_ns(&state->local_log_deadline) == 0u;
}

static uint32_t ads1278_stop_local_log(ads1278_server_state *state)
{
    uint32_t rows_written;

    if (state == NULL) {
        return 0u;
    }

    rows_written = ads1278_csv_logger_close(&state->local_logger);
    ads1278_clear_local_log_deadline(state);
    return rows_written;
}

int ads1278_server_parse_args(int argc, char **argv, ads1278_server_options *options)
{
    int index;

    if (options == NULL) {
        return -1;
    }

    for (index = 1; index < argc; ++index) {
        if (strcmp(argv[index], "--help") == 0) {
            ads1278_server_print_usage(stdout, argv[0]);
            return 1;
        }
        if (strcmp(argv[index], "--mem-path") == 0) {
            if ((index + 1) >= argc) {
                return -1;
            }
            options->mem_path = argv[++index];
            continue;
        }
        if (strcmp(argv[index], "--port") == 0) {
            if ((index + 1) >= argc || ads1278_parse_u16(argv[++index], &options->port) != 0) {
                return -1;
            }
            continue;
        }
        if (strcmp(argv[index], "--poll-ms") == 0) {
            unsigned int poll_timeout_ms;

            if ((index + 1) >= argc || ads1278_parse_uint(argv[++index], &poll_timeout_ms) != 0) {
                return -1;
            }
            options->poll_timeout_ms = (int)poll_timeout_ms;
            continue;
        }
        if (strcmp(argv[index], "--snapshot-retries") == 0) {
            if ((index + 1) >= argc || ads1278_parse_uint(argv[++index], &options->snapshot_retries) != 0) {
                return -1;
            }
            continue;
        }
        if (strcmp(argv[index], "--dma") == 0) {
            options->dma_mode = true;
            continue;
        }
        if (strcmp(argv[index], "--dma-bulk") == 0) {
            options->dma_mode = true;
            options->dma_bulk_mode = true;
            continue;
        }
        if (strcmp(argv[index], "--dma-base") == 0) {
            if ((index + 1) >= argc || ads1278_parse_u32(argv[++index], &options->dma_base_addr) != 0) {
                return -1;
            }
            continue;
        }
        if (strcmp(argv[index], "--dma-size") == 0) {
            if ((index + 1) >= argc || ads1278_parse_u32(argv[++index], &options->dma_buf_size) != 0) {
                return -1;
            }
            continue;
        }
        if (strcmp(argv[index], "--log-dir") == 0) {
            if ((index + 1) >= argc) {
                return -1;
            }
            options->local_log_dir = argv[++index];
            continue;
        }
        return -1;
    }

    return 0;
}

static int ads1278_send_all(int fd, const void *buffer, size_t size_bytes)
{
    const uint8_t *cursor;
    size_t remaining;

    cursor = (const uint8_t *)buffer;
    remaining = size_bytes;
    while (remaining > 0u) {
        ssize_t sent;

        sent = send(fd, cursor, remaining, MSG_NOSIGNAL);
        if (sent < 0) {
            if (errno == EINTR) {
                continue;
            }
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                fd_set write_fds;

                FD_ZERO(&write_fds);
                FD_SET(fd, &write_fds);
                if (select(fd + 1, NULL, &write_fds, NULL, NULL) < 0) {
                    if (errno == EINTR && g_stop_requested == 0) {
                        continue;
                    }
                    return -1;
                }
                continue;
            }
            return -1;
        }
        if (sent == 0) {
            errno = EPIPE;
            return -1;
        }

        cursor += (size_t)sent;
        remaining -= (size_t)sent;
    }

    return 0;
}

static int ads1278_make_listener(uint16_t port)
{
    int listener_fd;
    int yes;
    struct sockaddr_in addr;

    listener_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (listener_fd < 0) {
        return -1;
    }

    yes = 1;
    if (setsockopt(listener_fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes)) != 0) {
        close(listener_fd);
        return -1;
    }

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(port);

    if (bind(listener_fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        close(listener_fd);
        return -1;
    }
    if (listen(listener_fd, ADS1278_SERVER_LISTEN_BACKLOG) != 0) {
        close(listener_fd);
        return -1;
    }

    return listener_fd;
}

static int ads1278_refresh_snapshot(
    ads1278_server_state *state,
    unsigned int snapshot_retries
)
{
    ads1278_snapshot snapshot;
    const ads1278_snapshot *fallback;
    int read_result;

    fallback = state->have_snapshot ? &state->snapshot : NULL;
    read_result = ads1278_mmio_read_snapshot(&state->mmio, &snapshot, fallback, snapshot_retries);
    if (read_result < 0) {
        return -1;
    }
    if (read_result == ADS1278_SNAPSHOT_FALLBACK_USED) {
        state->stats.unstable_snapshot_reads += 1u;
    }

    state->snapshot = snapshot;
    state->have_snapshot = true;
    return 0;
}

static void ads1278_refresh_control_fields(ads1278_server_state *state)
{
    state->snapshot.ctrl_raw = ads1278_mmio_read32(&state->mmio, ADS1278_REG_CTRL);
    state->snapshot.extclk_div = ads1278_mmio_read32(&state->mmio, ADS1278_REG_EXTCLK_DIV);
    state->snapshot.mod_div = ads1278_mmio_read32(&state->mmio, ADS1278_REG_MOD_DIV);
}

static int ads1278_refresh_state_for_response(
    ads1278_server_state *state,
    bool dma_mode,
    unsigned int snapshot_retries
)
{
    if (!dma_mode) {
        return ads1278_refresh_snapshot(state, snapshot_retries);
    }

    /*
     * In DMA mode, avoid turning command ACKs into latest-sample MMIO reads.
     * Channel fields remain the last DMA frame; control fields come from MMIO.
     */
    state->snapshot.status_raw = ads1278_mmio_read32(&state->mmio, ADS1278_REG_STATUS);
    state->snapshot.frame_cnt = ads1278_status_frame_count(state->snapshot.status_raw);
    ads1278_refresh_control_fields(state);
    state->have_snapshot = true;
    return 0;
}

static void ads1278_fill_message(
    ads1278_server_state *state,
    ads1278_message *message,
    uint32_t msg_type,
    uint32_t opcode,
    uint32_t value
)
{
    unsigned int channel;

    memset(message, 0, sizeof(*message));
    message->msg_type = msg_type;
    message->msg_seq = state->stats.next_msg_seq++;
    message->opcode = opcode;
    message->value = value;
    message->status_raw = state->snapshot.status_raw;
    message->ctrl_raw = state->snapshot.ctrl_raw;
    message->extclk_div = state->snapshot.extclk_div;
    message->mod_div = state->snapshot.mod_div;
    for (channel = 0; channel < ADS1278_CHANNEL_COUNT; ++channel) {
        message->channels[channel] = state->snapshot.channels[channel];
    }
}

static int ads1278_send_snapshot_message(
    int client_fd,
    ads1278_server_state *state,
    uint32_t msg_type,
    uint32_t opcode,
    uint32_t value
)
{
    ads1278_message message;

    ads1278_fill_message(state, &message, msg_type, opcode, value);
    if (msg_type == ADS1278_MSG_SAMPLE
        && ads1278_csv_logger_write_message(&state->local_logger, &message) != 0) {
        return -1;
    }
    if (client_fd < 0) {
        return 0;
    }
    return ads1278_send_all(client_fd, &message, sizeof(message));
}

static int ads1278_dma_arm(
    ads1278_server_state *state,
    const ads1278_server_options *options
);

static uint32_t ads1278_build_enable_ctrl(uint32_t ctrl_raw, uint32_t enable_value)
{
    uint32_t next_ctrl;

    next_ctrl = ctrl_raw & ~ADS1278_CTRL_ENABLE;
    next_ctrl |= (enable_value << 1);
    return next_ctrl;
}

static uint32_t ads1278_build_demod_ctrl(uint32_t ctrl_raw, uint32_t demod_value)
{
    uint32_t next_ctrl;

    next_ctrl = ctrl_raw & ~ADS1278_CTRL_DEMOD_ENABLE;
    next_ctrl |= (demod_value << 2);
    return next_ctrl;
}

static uint32_t ads1278_build_sync_ctrl(uint32_t ctrl_raw)
{
    return ctrl_raw | ADS1278_CTRL_SYNC_TRIGGER;
}

static void ads1278_clear_pending_local_log_filename(ads1278_server_state *state)
{
    if (state == NULL) {
        return;
    }
    state->pending_local_log_filename[0] = '\0';
    state->pending_local_log_filename_valid = false;
}

static int ads1278_apply_pending_local_log_filename_chunk(
    ads1278_server_state *state,
    uint32_t value
)
{
    unsigned int chunk_index;
    unsigned int byte_index;
    size_t offset;

    if (state == NULL) {
        errno = EINVAL;
        return -1;
    }

    chunk_index = value >> ADS1278_LOCAL_LOG_FILENAME_CHUNK_SHIFT;
    if (chunk_index >= 32u) {
        errno = EINVAL;
        return -1;
    }

    if (chunk_index == 0u) {
        ads1278_clear_pending_local_log_filename(state);
    }

    offset = (size_t)chunk_index * ADS1278_LOCAL_LOG_FILENAME_CHUNK_BYTES;
    if (offset >= sizeof(state->pending_local_log_filename)) {
        errno = EINVAL;
        return -1;
    }

    for (byte_index = 0u; byte_index < ADS1278_LOCAL_LOG_FILENAME_CHUNK_BYTES; ++byte_index) {
        char ch = (char)((value >> (8u * byte_index)) & 0xffu);

        if (ch == '\0') {
            state->pending_local_log_filename_valid =
                state->pending_local_log_filename[0] != '\0';
            return 0;
        }
        if (offset + (size_t)byte_index >= ADS1278_LOCAL_LOG_FILENAME_MAX) {
            errno = EINVAL;
            return -1;
        }
        state->pending_local_log_filename[offset + (size_t)byte_index] = ch;
    }

    state->pending_local_log_filename[ADS1278_LOCAL_LOG_FILENAME_MAX] = '\0';
    state->pending_local_log_filename_valid =
        state->pending_local_log_filename[0] != '\0';
    return 0;
}

static int ads1278_apply_command(
    ads1278_server_state *state,
    const ads1278_server_options *options,
    const ads1278_command *command
)
{
    switch (command->opcode) {
    case ADS1278_OPCODE_SET_ENABLE:
        ads1278_refresh_control_fields(state);
        ads1278_mmio_write32(
            &state->mmio,
            ADS1278_REG_CTRL,
            ads1278_build_enable_ctrl(state->snapshot.ctrl_raw, command->value)
        );
        break;
    case ADS1278_OPCODE_SET_DEMOD_ENABLE:
        ads1278_refresh_control_fields(state);
        ads1278_mmio_write32(
            &state->mmio,
            ADS1278_REG_CTRL,
            ads1278_build_demod_ctrl(state->snapshot.ctrl_raw, command->value)
        );
        break;
    case ADS1278_OPCODE_TRIGGER_SYNC:
        ads1278_refresh_control_fields(state);
        ads1278_mmio_write32(
            &state->mmio,
            ADS1278_REG_CTRL,
            ads1278_build_sync_ctrl(state->snapshot.ctrl_raw)
        );
        break;
    case ADS1278_OPCODE_SET_EXTCLK_DIV:
        ads1278_mmio_write32(&state->mmio, ADS1278_REG_EXTCLK_DIV, command->value);
        break;
    case ADS1278_OPCODE_SET_MOD_DIV:
        ads1278_mmio_write32(&state->mmio, ADS1278_REG_MOD_DIV, command->value);
        break;
    case ADS1278_OPCODE_MARK_CAPTURE:
        /* ACK establishes an ordered capture boundary on the TCP stream. */
        break;
    case ADS1278_OPCODE_SET_LOCAL_LOG_DURATION:
        state->pending_local_log_duration_s = command->value;
        state->local_log_deadline_valid = false;
        break;
    case ADS1278_OPCODE_SET_LOCAL_LOG_FILENAME:
        if (ads1278_apply_pending_local_log_filename_chunk(state, command->value) != 0) {
            return -1;
        }
        break;
    case ADS1278_OPCODE_START_LOCAL_LOG:
        ads1278_refresh_control_fields(state);
        if (ads1278_csv_logger_start(
                &state->local_logger,
                options != NULL ? options->local_log_dir : ADS1278_LOCAL_LOG_DIR,
                command->value,
                state->snapshot.ctrl_raw,
                state->pending_local_log_filename_valid
                    ? state->pending_local_log_filename
                    : NULL
            ) != 0) {
            ads1278_clear_pending_local_log_filename(state);
            return -1;
        }
        ads1278_clear_pending_local_log_filename(state);
        if (ads1278_set_local_log_deadline(state, state->pending_local_log_duration_s) != 0) {
            ads1278_stop_local_log(state);
            return -1;
        }
        fprintf(stderr, "Started local CSV log: %s\n", state->local_logger.path);
        break;
    case ADS1278_OPCODE_STOP_LOCAL_LOG:
        ads1278_stop_local_log(state);
        fprintf(stderr, "Stopped local CSV log\n");
        break;
    default:
        break;
    }
    return 0;
}

static void ads1278_reset_client_state(ads1278_server_state *state)
{
    ads1278_cmd_parser_init(&state->parser);
    if (state->have_snapshot) {
        state->last_streamed_frame_cnt = state->snapshot.frame_cnt;
    } else {
        state->last_streamed_frame_cnt = 0u;
    }
}

static int ads1278_handle_new_client(
    int client_fd,
    ads1278_server_state *state,
    const ads1278_server_options *options,
    unsigned int snapshot_retries
)
{
    if (ads1278_refresh_snapshot(state, snapshot_retries) != 0) {
        return -1;
    }

    ads1278_reset_client_state(state);
    if (ads1278_send_all(client_fd, ADS1278_CAPABILITY_LINE, strlen(ADS1278_CAPABILITY_LINE)) != 0) {
        return -1;
    }
    if (ads1278_send_snapshot_message(client_fd, state, ADS1278_MSG_SAMPLE, 0u, 0u) != 0) {
        return -1;
    }

    state->last_streamed_frame_cnt = state->snapshot.frame_cnt;
    if (options->dma_mode) {
        if (ads1278_dma_arm(state, options) != 0) {
            return -1;
        }
    }
    return 0;
}

static int ads1278_handle_command(
    int client_fd,
    ads1278_server_state *state,
    const ads1278_server_options *options,
    const ads1278_command *command,
    bool dma_mode,
    unsigned int snapshot_retries
)
{
    ads1278_cmd_validation_result validation_result;
    uint32_t response_value;

    validation_result = ads1278_command_validate(command);
    if (validation_result == ADS1278_CMD_VALID) {
        response_value = command->value;
        if (command->opcode == ADS1278_OPCODE_STOP_LOCAL_LOG) {
            response_value = state->local_logger.rows_written;
        }
        if (ads1278_apply_command(state, options, command) != 0) {
            if (ads1278_refresh_state_for_response(state, dma_mode, snapshot_retries) != 0) {
                return -1;
            }
            state->stats.rejected_commands += 1u;
            if (ads1278_send_snapshot_message(
                    client_fd,
                    state,
                    ADS1278_MSG_ERROR,
                    command->opcode,
                    command->value
                ) != 0) {
                return -1;
            }
            perror("local command failed");
            state->last_streamed_frame_cnt = state->snapshot.frame_cnt;
            return 0;
        }
        if (ads1278_refresh_state_for_response(state, dma_mode, snapshot_retries) != 0) {
            return -1;
        }
        state->stats.accepted_commands += 1u;
        if (ads1278_send_snapshot_message(
                client_fd,
                state,
                ADS1278_MSG_ACK,
                command->opcode,
                response_value
            ) != 0) {
            return -1;
        }
    } else {
        if (ads1278_refresh_state_for_response(state, dma_mode, snapshot_retries) != 0) {
            return -1;
        }
        state->stats.rejected_commands += 1u;
        if (ads1278_send_snapshot_message(
                client_fd,
                state,
                ADS1278_MSG_ERROR,
                command->opcode,
                command->value
            ) != 0) {
            return -1;
        }
        fprintf(stderr, "Rejected command opcode=%u value=%u: %s\n",
            command->opcode,
            command->value,
            ads1278_cmd_validation_result_string(validation_result));
    }

    state->last_streamed_frame_cnt = state->snapshot.frame_cnt;
    return 0;
}

static int ads1278_consume_socket_bytes(
    int client_fd,
    ads1278_server_state *state,
    const ads1278_server_options *options,
    const uint8_t *buffer,
    size_t buffer_len,
    bool dma_mode,
    unsigned int snapshot_retries
)
{
    size_t offset;

    offset = 0u;
    while (offset < buffer_len) {
        ads1278_command command;
        size_t consumed;
        int have_command;

        have_command = ads1278_cmd_parser_push(
            &state->parser,
            buffer + offset,
            buffer_len - offset,
            &command,
            &consumed
        );
        offset += consumed;
        if (have_command != 0) {
            if (ads1278_handle_command(client_fd, state, options, &command, dma_mode, snapshot_retries) != 0) {
                return -1;
            }
        }
    }

    return 0;
}

static int ads1278_service_client_socket(
    int client_fd,
    ads1278_server_state *state,
    const ads1278_server_options *options,
    bool dma_mode,
    unsigned int snapshot_retries
)
{
    uint8_t buffer[256];
    ssize_t recv_result;

    while (1) {
        recv_result = recv(client_fd, buffer, sizeof(buffer), 0);
        if (recv_result < 0) {
            if (errno == EINTR) {
                if (g_stop_requested != 0) {
                    return -1;
                }
                continue;
            }
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                return 0;
            }
            return -1;
        }
        if (recv_result == 0) {
            errno = 0;
            return -1;
        }
        if (ads1278_consume_socket_bytes(
                client_fd,
                state,
                options,
                buffer,
                (size_t)recv_result,
                dma_mode,
                snapshot_retries
            ) != 0) {
            return -1;
        }
    }
}

static int ads1278_maybe_send_sample(
    int client_fd,
    ads1278_server_state *state,
    unsigned int snapshot_retries
)
{
    if (ads1278_refresh_snapshot(state, snapshot_retries) != 0) {
        return -1;
    }

    if (state->snapshot.frame_cnt == state->last_streamed_frame_cnt) {
        return 0;
    }

    if (ads1278_send_snapshot_message(client_fd, state, ADS1278_MSG_SAMPLE, 0u, 0u) != 0) {
        return -1;
    }
    state->last_streamed_frame_cnt = state->snapshot.frame_cnt;
    return 0;
}

static int ads1278_dma_arm(
    ads1278_server_state *state,
    const ads1278_server_options *options
)
{
    uint32_t dma_ctrl;

    if (state == NULL || options == NULL) {
        errno = EINVAL;
        return -1;
    }

    ads1278_mmio_write32(&state->mmio, ADS1278_REG_DMA_CTRL, 0u);
    ads1278_mmio_write32(
        &state->mmio,
        ADS1278_REG_DMA_IRQ_ACK,
        ADS1278_DMA_IRQ_WRAP | ADS1278_DMA_IRQ_ERROR | ADS1278_DMA_IRQ_CONFIG | ADS1278_DMA_IRQ_OVERWRITE
    );
    ads1278_mmio_write32(
        &state->mmio,
        ADS1278_REG_DMA_BUF_ACK,
        ADS1278_DMA_BUF_ACK_BUF0 | ADS1278_DMA_BUF_ACK_BUF1
    );
    ads1278_mmio_write32(&state->mmio, ADS1278_REG_DMA_BASE_ADDR, options->dma_base_addr);
    ads1278_mmio_write32(&state->mmio, ADS1278_REG_DMA_BUF_SIZE, options->dma_buf_size);

    dma_ctrl = ADS1278_DMA_CTRL_ENABLE
        | (ADS1278_DMA_MODE_CAPTURE << ADS1278_DMA_CTRL_MODE_SHIFT);
    ads1278_mmio_write32(&state->mmio, ADS1278_REG_DMA_CTRL, dma_ctrl);
    return 0;
}

static void ads1278_dma_stop(ads1278_server_state *state)
{
    if (state == NULL) {
        return;
    }
    ads1278_mmio_write32(&state->mmio, ADS1278_REG_DMA_CTRL, 0u);
}

static int ads1278_dma_find_frame_start_word(
    const ads1278_ddr_map *ddr,
    size_t *frame_start_word
)
{
    size_t word_count;
    size_t index;

    if (ddr == NULL || frame_start_word == NULL || ddr->words == NULL) {
        errno = EINVAL;
        return -1;
    }

    word_count = ddr->map_size / sizeof(uint32_t);
    for (index = 0u; index < word_count; ++index) {
        if (ddr->words[index] == ADS1278_DMA_FRAME_STRIDE_CANARY) {
            *frame_start_word = (index + 1u) % ADS1278_DMA_FRAME_WORDS;
            return 0;
        }
    }

    errno = EIO;
    return -1;
}

static bool ads1278_dma_frame_words_valid(const volatile uint32_t *words)
{
    size_t index;

    if (words == NULL) {
        return false;
    }
    for (index = ADS1278_DMA_FRAME_PAYLOAD_WORDS; index < (ADS1278_DMA_FRAME_WORDS - 1u); ++index) {
        if (words[index] != 0u) {
            return false;
        }
    }
    return words[ADS1278_DMA_FRAME_WORDS - 1u] == ADS1278_DMA_FRAME_STRIDE_CANARY;
}

static void ads1278_snapshot_from_dma_words(
    ads1278_server_state *state,
    const volatile uint32_t *words
)
{
    unsigned int channel;

    state->snapshot.status_raw = words[1];
    state->snapshot.frame_cnt = (uint16_t)words[0];
    for (channel = 0u; channel < ADS1278_CHANNEL_COUNT; ++channel) {
        state->snapshot.channels[channel] = (int32_t)words[2u + channel];
    }
    state->have_snapshot = true;
}

static void ads1278_bulk_frame_from_dma_words(
    ads1278_bulk_frame *frame,
    const volatile uint32_t *words
)
{
    unsigned int channel;

    frame->frame_count = words[0];
    frame->status_raw = words[1];
    for (channel = 0u; channel < ADS1278_CHANNEL_COUNT; ++channel) {
        frame->channels[channel] = (int32_t)words[2u + channel];
    }
}

static void ads1278_snapshot_from_bulk_frame(
    ads1278_server_state *state,
    const ads1278_bulk_frame *frame
)
{
    unsigned int channel;

    state->snapshot.status_raw = frame->status_raw;
    state->snapshot.frame_cnt = (uint16_t)frame->frame_count;
    for (channel = 0u; channel < ADS1278_CHANNEL_COUNT; ++channel) {
        state->snapshot.channels[channel] = frame->channels[channel];
    }
    state->have_snapshot = true;
}

static int ads1278_send_dma_buffer_bulk(
    int client_fd,
    ads1278_server_state *state,
    ads1278_ddr_map *ddr,
    size_t frame_start_word,
    size_t frame_count
)
{
    ads1278_bulk_frame *frames;
    ads1278_message header;
    size_t frame_index;
    size_t valid_count;
    uint32_t base_msg_seq;

    if (frame_count > UINT32_MAX) {
        errno = EOVERFLOW;
        return -1;
    }

    frames = calloc(frame_count, sizeof(*frames));
    if (frames == NULL) {
        return -1;
    }

    valid_count = 0u;
    for (frame_index = 0u; frame_index < frame_count; ++frame_index) {
        size_t word_index;
        const volatile uint32_t *words;

        word_index = frame_start_word + (frame_index * ADS1278_DMA_FRAME_WORDS);
        words = &ddr->words[word_index];
        if (!ads1278_dma_frame_words_valid(words)) {
            state->stats.dma_bad_frames += 1u;
            continue;
        }

        ads1278_bulk_frame_from_dma_words(&frames[valid_count], words);
        ads1278_snapshot_from_bulk_frame(state, &frames[valid_count]);
        valid_count += 1u;
    }

    if (valid_count == 0u) {
        free(frames);
        return 0;
    }

    base_msg_seq = state->stats.next_msg_seq;
    ads1278_fill_message(
        state,
        &header,
        ADS1278_MSG_BULK_SAMPLES,
        0u,
        (uint32_t)valid_count
    );
    header.msg_seq = base_msg_seq;
    state->stats.next_msg_seq = base_msg_seq + (uint32_t)valid_count;
    if (state->local_logger.active) {
        for (frame_index = 0u; frame_index < valid_count; ++frame_index) {
            if (ads1278_csv_logger_write_bulk_frame(
                    &state->local_logger,
                    base_msg_seq + (uint32_t)frame_index,
                    header.ctrl_raw,
                    header.extclk_div,
                    header.mod_div,
                    &frames[frame_index]
                ) != 0) {
                free(frames);
                return -1;
            }
        }
    }
    if (client_fd < 0) {
        state->last_streamed_frame_cnt = state->snapshot.frame_cnt;
        state->stats.dma_frames_streamed += (uint32_t)valid_count;
        state->stats.dma_bulk_messages_streamed += 1u;
        free(frames);
        return 0;
    }
    if (ads1278_send_all(client_fd, &header, sizeof(header)) != 0
        || ads1278_send_all(client_fd, frames, valid_count * sizeof(*frames)) != 0) {
        free(frames);
        return -1;
    }

    state->last_streamed_frame_cnt = state->snapshot.frame_cnt;
    state->stats.dma_frames_streamed += (uint32_t)valid_count;
    state->stats.dma_bulk_messages_streamed += 1u;
    free(frames);
    return 0;
}

static int ads1278_send_dma_buffer_samples(
    int client_fd,
    ads1278_server_state *state,
    ads1278_ddr_map *ddr,
    size_t frame_start_word,
    size_t frame_count
)
{
    size_t frame_index;

    for (frame_index = 0u; frame_index < frame_count; ++frame_index) {
        size_t word_index;
        const volatile uint32_t *words;

        word_index = frame_start_word + (frame_index * ADS1278_DMA_FRAME_WORDS);
        words = &ddr->words[word_index];
        if (!ads1278_dma_frame_words_valid(words)) {
            state->stats.dma_bad_frames += 1u;
            continue;
        }

        ads1278_snapshot_from_dma_words(state, words);
        if (ads1278_send_snapshot_message(client_fd, state, ADS1278_MSG_SAMPLE, 0u, 0u) != 0) {
            return -1;
        }
        state->last_streamed_frame_cnt = state->snapshot.frame_cnt;
        state->stats.dma_frames_streamed += 1u;
    }

    return 0;
}

static int ads1278_send_dma_buffer(
    int client_fd,
    ads1278_server_state *state,
    unsigned int buffer_index,
    bool bulk_mode
)
{
    ads1278_ddr_map *ddr;
    size_t frame_start_word;
    size_t word_count;
    size_t frame_count;
    uint32_t ack_mask;

    if (state == NULL || buffer_index > 1u || !state->dma.maps_open) {
        errno = EINVAL;
        return -1;
    }

    ddr = &state->dma.buffers[buffer_index];
    ads1278_ddr_sync_for_cpu((void *)ddr->words, ddr->map_size);
    if (ads1278_dma_find_frame_start_word(ddr, &frame_start_word) != 0) {
        return -1;
    }

    word_count = ddr->map_size / sizeof(uint32_t);
    frame_count = (word_count - frame_start_word) / ADS1278_DMA_FRAME_WORDS;
    ads1278_refresh_control_fields(state);

    if (bulk_mode) {
        if (ads1278_send_dma_buffer_bulk(client_fd, state, ddr, frame_start_word, frame_count) != 0) {
            return -1;
        }
    } else {
        if (ads1278_send_dma_buffer_samples(client_fd, state, ddr, frame_start_word, frame_count) != 0) {
            return -1;
        }
    }

    ack_mask = (buffer_index == 0u) ? ADS1278_DMA_BUF_ACK_BUF0 : ADS1278_DMA_BUF_ACK_BUF1;
    ads1278_mmio_write32(&state->mmio, ADS1278_REG_DMA_BUF_ACK, ack_mask);
    state->stats.dma_buffers_consumed += 1u;
    return 0;
}

static int ads1278_service_dma_buffers(
    int client_fd,
    ads1278_server_state *state,
    bool bulk_mode
)
{
    uint32_t buf_status;

    buf_status = ads1278_mmio_read32(&state->mmio, ADS1278_REG_DMA_BUF_STATUS);
    if ((buf_status & ADS1278_DMA_BUF_STATUS_BUF0_FULL) != 0u) {
        if (ads1278_send_dma_buffer(client_fd, state, 0u, bulk_mode) != 0) {
            return -1;
        }
    }
    if ((buf_status & ADS1278_DMA_BUF_STATUS_BUF1_FULL) != 0u) {
        if (ads1278_send_dma_buffer(client_fd, state, 1u, bulk_mode) != 0) {
            return -1;
        }
    }

    return 0;
}

static int ads1278_maybe_stop_expired_local_log(
    ads1278_server_state *state,
    bool dma_mode
)
{
    uint32_t rows_written;

    if (!ads1278_local_log_deadline_expired(state)) {
        return 0;
    }

    rows_written = ads1278_stop_local_log(state);
    if (dma_mode) {
        ads1278_dma_stop(state);
    }
    fprintf(stderr, "Timed local CSV log completed after %u rows\n", rows_written);
    return 0;
}

static int ads1278_service_local_log_without_client(
    ads1278_server_state *state,
    const ads1278_server_options *options,
    struct timespec *next_sample_deadline,
    bool *next_sample_deadline_valid
)
{
    if (ads1278_maybe_stop_expired_local_log(state, options->dma_mode) != 0) {
        return -1;
    }
    if (!state->local_logger.active) {
        return 0;
    }

    if (options->dma_mode) {
        return ads1278_service_dma_buffers(-1, state, options->dma_bulk_mode);
    }

    if (next_sample_deadline == NULL || next_sample_deadline_valid == NULL) {
        errno = EINVAL;
        return -1;
    }
    if (!*next_sample_deadline_valid) {
        if (ads1278_set_next_sample_deadline(next_sample_deadline, state, options) != 0) {
            return -1;
        }
        *next_sample_deadline_valid = true;
    }
    if (ads1278_time_until_deadline_ns(next_sample_deadline) == 0u) {
        if (ads1278_maybe_send_sample(-1, state, options->snapshot_retries) != 0) {
            return -1;
        }
        if (ads1278_set_next_sample_deadline(next_sample_deadline, state, options) != 0) {
            return -1;
        }
    }
    return 0;
}

static void ads1278_close_client(
    int *client_fd,
    ads1278_server_state *state,
    bool dma_mode
)
{
    if (*client_fd >= 0) {
        if (dma_mode && !ads1278_local_log_should_continue_unattended(state)) {
            ads1278_dma_stop(state);
        }
        if (!ads1278_local_log_should_continue_unattended(state)) {
            ads1278_stop_local_log(state);
        }
        close(*client_fd);
        *client_fd = -1;
    }
}

int ads1278_server_run(const ads1278_server_options *options)
{
    ads1278_server_state state;
    int listener_fd;
    int client_fd;
    struct timespec next_sample_deadline;
    bool next_sample_deadline_valid;

    memset(&state, 0, sizeof(state));
    state.mmio.fd = -1;
    ads1278_dma_state_init(&state.dma);
    ads1278_csv_logger_init(&state.local_logger);
    ads1278_cmd_parser_init(&state.parser);
    listener_fd = -1;
    client_fd = -1;
    next_sample_deadline_valid = false;

    if (ads1278_install_signal_handlers() != 0) {
        perror("sigaction");
        return EXIT_FAILURE;
    }
    if (ads1278_mmio_open(&state.mmio, options->mem_path) != 0) {
        perror("open /dev/mem");
        return EXIT_FAILURE;
    }
    if (ads1278_refresh_snapshot(&state, options->snapshot_retries) != 0) {
        perror("read initial snapshot");
        ads1278_mmio_close(&state.mmio);
        return EXIT_FAILURE;
    }
    if (options->dma_mode && ads1278_dma_open_buffers(&state.dma, options) != 0) {
        perror("open DMA buffers");
        ads1278_mmio_close(&state.mmio);
        return EXIT_FAILURE;
    }

    listener_fd = ads1278_make_listener(options->port);
    if (listener_fd < 0) {
        perror("listen");
        ads1278_dma_close_buffers(&state.dma);
        ads1278_mmio_close(&state.mmio);
        return EXIT_FAILURE;
    }

    fprintf(
        stderr,
        "Listening on port %u using %s%s%s; local CSV dir %s\n",
        (unsigned int)options->port,
        options->mem_path,
        options->dma_mode ? " (DMA mode" : "",
        options->dma_mode ? (options->dma_bulk_mode ? ", bulk)" : ")") : "",
        options->local_log_dir
    );

    while (g_stop_requested == 0) {
        fd_set read_fds;
        int select_result;
        int max_fd;
        struct timeval timeout;
        struct timeval *timeout_ptr;

        FD_ZERO(&read_fds);
        max_fd = -1;
        timeout_ptr = NULL;

        if (client_fd < 0) {
            FD_SET(listener_fd, &read_fds);
            max_fd = listener_fd;
            if (state.local_logger.active) {
                uint64_t timeout_ns;

                if (options->dma_mode) {
                    timeout_ns = (uint64_t)options->poll_timeout_ms * ADS1278_NS_PER_MS;
                    if (timeout_ns == 0u) {
                        timeout_ns = ADS1278_NS_PER_MS;
                    }
                } else if (!next_sample_deadline_valid) {
                    if (ads1278_set_next_sample_deadline(&next_sample_deadline, &state, options) != 0) {
                        perror("clock_gettime");
                        break;
                    }
                    next_sample_deadline_valid = true;
                    timeout_ns = ads1278_time_until_deadline_ns(&next_sample_deadline);
                } else {
                    timeout_ns = ads1278_time_until_deadline_ns(&next_sample_deadline);
                }
                if (state.local_log_deadline_valid) {
                    uint64_t deadline_ns;

                    deadline_ns = ads1278_time_until_deadline_ns(&state.local_log_deadline);
                    if (deadline_ns < timeout_ns) {
                        timeout_ns = deadline_ns;
                    }
                }
                ads1278_ns_to_timeval(timeout_ns, &timeout);
                timeout_ptr = &timeout;
            }
        } else {
            uint64_t timeout_ns;

            FD_SET(client_fd, &read_fds);
            max_fd = client_fd;

            if (options->dma_mode) {
                timeout_ns = (uint64_t)options->poll_timeout_ms * ADS1278_NS_PER_MS;
                if (timeout_ns == 0u) {
                    timeout_ns = ADS1278_NS_PER_MS;
                }
            } else if (!next_sample_deadline_valid) {
                if (ads1278_set_next_sample_deadline(&next_sample_deadline, &state, options) != 0) {
                    perror("clock_gettime");
                    break;
                }
                next_sample_deadline_valid = true;
                timeout_ns = ads1278_time_until_deadline_ns(&next_sample_deadline);
            } else {
                timeout_ns = ads1278_time_until_deadline_ns(&next_sample_deadline);
            }

            ads1278_ns_to_timeval(timeout_ns, &timeout);
            timeout_ptr = &timeout;
        }

        select_result = select(max_fd + 1, &read_fds, NULL, NULL, timeout_ptr);
        if (select_result < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("select");
            break;
        }

        if (client_fd < 0) {
            if (select_result > 0 && FD_ISSET(listener_fd, &read_fds)) {
                client_fd = accept(listener_fd, NULL, NULL);
                if (client_fd < 0) {
                    if (errno == EINTR) {
                        continue;
                    }
                    perror("accept");
                    break;
                }
                if (ads1278_set_nonblocking(client_fd) != 0) {
                    perror("fcntl");
                    ads1278_close_client(&client_fd, &state, options->dma_mode);
                    continue;
                }
                if (ads1278_handle_new_client(client_fd, &state, options, options->snapshot_retries) != 0) {
                    perror("client setup");
                    ads1278_close_client(&client_fd, &state, options->dma_mode);
                } else if (!options->dma_mode
                    && ads1278_set_next_sample_deadline(&next_sample_deadline, &state, options) != 0) {
                    perror("clock_gettime");
                    ads1278_close_client(&client_fd, &state, options->dma_mode);
                } else {
                    next_sample_deadline_valid = !options->dma_mode;
                }
            }
            if (ads1278_service_local_log_without_client(
                    &state,
                    options,
                    &next_sample_deadline,
                    &next_sample_deadline_valid
                ) != 0) {
                perror("local log service");
                if (options->dma_mode) {
                    ads1278_dma_stop(&state);
                }
                ads1278_stop_local_log(&state);
                next_sample_deadline_valid = false;
            }
            continue;
        }

        if (select_result > 0 && FD_ISSET(client_fd, &read_fds)) {
            if (ads1278_service_client_socket(client_fd, &state, options, options->dma_mode, options->snapshot_retries) != 0) {
                ads1278_close_client(&client_fd, &state, options->dma_mode);
                next_sample_deadline_valid = false;
                continue;
            }
            if (!options->dma_mode
                && ads1278_set_next_sample_deadline(&next_sample_deadline, &state, options) != 0) {
                perror("clock_gettime");
                ads1278_close_client(&client_fd, &state, options->dma_mode);
                next_sample_deadline_valid = false;
                continue;
            }
            next_sample_deadline_valid = !options->dma_mode;
        }

        if (options->dma_mode) {
            if (ads1278_service_dma_buffers(client_fd, &state, options->dma_bulk_mode) != 0) {
                ads1278_close_client(&client_fd, &state, options->dma_mode);
                next_sample_deadline_valid = false;
                continue;
            }
        } else if (next_sample_deadline_valid && ads1278_time_until_deadline_ns(&next_sample_deadline) == 0u) {
            if (ads1278_maybe_send_sample(client_fd, &state, options->snapshot_retries) != 0) {
                ads1278_close_client(&client_fd, &state, options->dma_mode);
                next_sample_deadline_valid = false;
                continue;
            }
            if (ads1278_set_next_sample_deadline(&next_sample_deadline, &state, options) != 0) {
                perror("clock_gettime");
                ads1278_close_client(&client_fd, &state, options->dma_mode);
                next_sample_deadline_valid = false;
                continue;
            }
        }

        if (ads1278_maybe_stop_expired_local_log(&state, options->dma_mode) != 0) {
            perror("local log deadline");
            ads1278_close_client(&client_fd, &state, options->dma_mode);
            next_sample_deadline_valid = false;
            continue;
        }
    }

    ads1278_close_client(&client_fd, &state, options->dma_mode);
    ads1278_csv_logger_close(&state.local_logger);
    if (listener_fd >= 0) {
        close(listener_fd);
    }
    ads1278_dma_close_buffers(&state.dma);
    ads1278_mmio_close(&state.mmio);
    return EXIT_SUCCESS;
}

int main(int argc, char **argv)
{
    ads1278_server_options options;
    int parse_result;

    ads1278_server_options_init(&options);
    parse_result = ads1278_server_parse_args(argc, argv, &options);
    if (parse_result > 0) {
        return EXIT_SUCCESS;
    }
    if (parse_result < 0) {
        ads1278_server_print_usage(stderr, argv[0]);
        return EXIT_FAILURE;
    }

    return ads1278_server_run(&options);
}
