#include "server.h"

#include "cmd_parse.h"
#include "protocol.h"

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif

typedef struct {
    ads1278_mmio mmio;
    ads1278_snapshot snapshot;
    ads1278_cmd_parser parser;
    ads1278_server_stats stats;
    uint16_t last_streamed_frame_cnt;
    bool have_snapshot;
} ads1278_server_state;

static volatile sig_atomic_t g_stop_requested = 0;

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
}

void ads1278_server_print_usage(FILE *stream, const char *argv0)
{
    fprintf(
        stream,
        "Usage: %s [--port N] [--mem-path PATH] [--poll-ms N] [--snapshot-retries N]\n",
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
    return ads1278_send_all(client_fd, &message, sizeof(message));
}

static uint32_t ads1278_build_enable_ctrl(uint32_t ctrl_raw, uint32_t enable_value)
{
    uint32_t next_ctrl;

    next_ctrl = ctrl_raw & ~ADS1278_CTRL_ENABLE;
    next_ctrl |= (enable_value << 1);
    return next_ctrl;
}

static uint32_t ads1278_build_sync_ctrl(uint32_t ctrl_raw)
{
    return (ctrl_raw & ADS1278_CTRL_ENABLE) | ADS1278_CTRL_SYNC_TRIGGER;
}

static void ads1278_apply_command(
    ads1278_server_state *state,
    const ads1278_command *command
)
{
    switch (command->opcode) {
    case ADS1278_OPCODE_SET_ENABLE:
        ads1278_mmio_write32(
            &state->mmio,
            ADS1278_REG_CTRL,
            ads1278_build_enable_ctrl(state->snapshot.ctrl_raw, command->value)
        );
        break;
    case ADS1278_OPCODE_TRIGGER_SYNC:
        ads1278_mmio_write32(
            &state->mmio,
            ADS1278_REG_CTRL,
            ads1278_build_sync_ctrl(state->snapshot.ctrl_raw)
        );
        break;
    case ADS1278_OPCODE_SET_EXTCLK_DIV:
        ads1278_mmio_write32(&state->mmio, ADS1278_REG_EXTCLK_DIV, command->value);
        break;
    default:
        break;
    }
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
    return 0;
}

static int ads1278_handle_command(
    int client_fd,
    ads1278_server_state *state,
    const ads1278_command *command,
    unsigned int snapshot_retries
)
{
    ads1278_cmd_validation_result validation_result;

    validation_result = ads1278_command_validate(command);
    if (validation_result == ADS1278_CMD_VALID) {
        ads1278_apply_command(state, command);
        if (ads1278_refresh_snapshot(state, snapshot_retries) != 0) {
            return -1;
        }
        state->stats.accepted_commands += 1u;
        if (ads1278_send_snapshot_message(
                client_fd,
                state,
                ADS1278_MSG_ACK,
                command->opcode,
                command->value
            ) != 0) {
            return -1;
        }
    } else {
        if (ads1278_refresh_snapshot(state, snapshot_retries) != 0) {
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
    const uint8_t *buffer,
    size_t buffer_len,
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
            if (ads1278_handle_command(client_fd, state, &command, snapshot_retries) != 0) {
                return -1;
            }
        }
    }

    return 0;
}

static int ads1278_service_client_socket(
    int client_fd,
    ads1278_server_state *state,
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
                buffer,
                (size_t)recv_result,
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

static void ads1278_close_client(int *client_fd)
{
    if (*client_fd >= 0) {
        close(*client_fd);
        *client_fd = -1;
    }
}

int ads1278_server_run(const ads1278_server_options *options)
{
    ads1278_server_state state;
    int listener_fd;
    int client_fd;

    memset(&state, 0, sizeof(state));
    state.mmio.fd = -1;
    ads1278_cmd_parser_init(&state.parser);
    listener_fd = -1;
    client_fd = -1;

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

    listener_fd = ads1278_make_listener(options->port);
    if (listener_fd < 0) {
        perror("listen");
        ads1278_mmio_close(&state.mmio);
        return EXIT_FAILURE;
    }

    fprintf(stderr, "Listening on port %u using %s\n", (unsigned int)options->port, options->mem_path);

    while (g_stop_requested == 0) {
        struct pollfd poll_fds[2];
        nfds_t poll_count;
        int poll_result;

        memset(poll_fds, 0, sizeof(poll_fds));
        poll_count = 0u;

        if (client_fd < 0) {
            poll_fds[poll_count].fd = listener_fd;
            poll_fds[poll_count].events = POLLIN;
            poll_count += 1u;
        } else {
            poll_fds[poll_count].fd = client_fd;
            poll_fds[poll_count].events = POLLIN | POLLERR | POLLHUP;
            poll_count += 1u;
        }

        poll_result = poll(poll_fds, poll_count, options->poll_timeout_ms);
        if (poll_result < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("poll");
            break;
        }

        if (client_fd < 0) {
            if (poll_result > 0 && (poll_fds[0].revents & POLLIN) != 0) {
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
                    ads1278_close_client(&client_fd);
                    continue;
                }
                if (ads1278_handle_new_client(client_fd, &state, options->snapshot_retries) != 0) {
                    perror("client setup");
                    ads1278_close_client(&client_fd);
                }
            }
            continue;
        }

        if (poll_result > 0) {
            if ((poll_fds[0].revents & (POLLERR | POLLHUP)) != 0) {
                ads1278_close_client(&client_fd);
                continue;
            }
            if ((poll_fds[0].revents & POLLIN) != 0) {
                if (ads1278_service_client_socket(client_fd, &state, options->snapshot_retries) != 0) {
                    ads1278_close_client(&client_fd);
                    continue;
                }
            }
        }

        if (ads1278_maybe_send_sample(client_fd, &state, options->snapshot_retries) != 0) {
            ads1278_close_client(&client_fd);
            continue;
        }
    }

    ads1278_close_client(&client_fd);
    if (listener_fd >= 0) {
        close(listener_fd);
    }
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
