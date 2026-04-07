#ifndef ADS1278_SERVER_H
#define ADS1278_SERVER_H

#include <stdint.h>
#include <stdio.h>

#include "memory_map.h"

#define ADS1278_SERVER_LISTEN_BACKLOG 4
#define ADS1278_SERVER_POLL_TIMEOUT_MS 10

typedef struct {
    const char *mem_path;
    uint16_t port;
    int poll_timeout_ms;
    unsigned int snapshot_retries;
} ads1278_server_options;

typedef struct {
    uint32_t next_msg_seq;
    uint32_t unstable_snapshot_reads;
    uint32_t accepted_commands;
    uint32_t rejected_commands;
} ads1278_server_stats;

void ads1278_server_options_init(ads1278_server_options *options);
void ads1278_server_print_usage(FILE *stream, const char *argv0);
int ads1278_server_parse_args(int argc, char **argv, ads1278_server_options *options);
int ads1278_server_run(const ads1278_server_options *options);

#endif
