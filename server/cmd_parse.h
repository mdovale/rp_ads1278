#ifndef ADS1278_CMD_PARSE_H
#define ADS1278_CMD_PARSE_H

#include <stddef.h>
#include <stdint.h>

#include "protocol.h"

typedef struct {
    uint8_t buffer[ADS1278_COMMAND_SIZE];
    size_t buffered;
} ads1278_cmd_parser;

typedef enum {
    ADS1278_CMD_VALID = 0,
    ADS1278_CMD_ERR_UNKNOWN_OPCODE,
    ADS1278_CMD_ERR_INVALID_ENABLE_VALUE,
    ADS1278_CMD_ERR_INVALID_EXTCLK_DIV
} ads1278_cmd_validation_result;

void ads1278_cmd_parser_init(ads1278_cmd_parser *parser);
int ads1278_cmd_parser_push(
    ads1278_cmd_parser *parser,
    const uint8_t *data,
    size_t data_len,
    ads1278_command *command,
    size_t *consumed
);
ads1278_cmd_validation_result ads1278_command_validate(const ads1278_command *command);
const char *ads1278_cmd_validation_result_string(ads1278_cmd_validation_result result);

#endif
