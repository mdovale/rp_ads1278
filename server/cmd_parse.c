#include "cmd_parse.h"

#include <string.h>

void ads1278_cmd_parser_init(ads1278_cmd_parser *parser)
{
    if (parser == NULL) {
        return;
    }

    memset(parser, 0, sizeof(*parser));
}

int ads1278_cmd_parser_push(
    ads1278_cmd_parser *parser,
    const uint8_t *data,
    size_t data_len,
    ads1278_command *command,
    size_t *consumed
)
{
    size_t room;
    size_t to_copy;

    if (parser == NULL || command == NULL || consumed == NULL) {
        return 0;
    }

    *consumed = 0;
    if (data == NULL || data_len == 0u) {
        return 0;
    }

    room = ADS1278_COMMAND_SIZE - parser->buffered;
    to_copy = data_len < room ? data_len : room;
    memcpy(parser->buffer + parser->buffered, data, to_copy);
    parser->buffered += to_copy;
    *consumed = to_copy;

    if (parser->buffered < ADS1278_COMMAND_SIZE) {
        return 0;
    }

    memcpy(command, parser->buffer, ADS1278_COMMAND_SIZE);
    parser->buffered = 0u;
    return 1;
}

ads1278_cmd_validation_result ads1278_command_validate(const ads1278_command *command)
{
    if (command == NULL) {
        return ADS1278_CMD_ERR_UNKNOWN_OPCODE;
    }

    switch (command->opcode) {
    case ADS1278_OPCODE_SET_ENABLE:
        if (command->value == 0u || command->value == 1u) {
            return ADS1278_CMD_VALID;
        }
        return ADS1278_CMD_ERR_INVALID_ENABLE_VALUE;
    case ADS1278_OPCODE_TRIGGER_SYNC:
    case ADS1278_OPCODE_MARK_CAPTURE:
        return ADS1278_CMD_VALID;
    case ADS1278_OPCODE_SET_EXTCLK_DIV:
        if (command->value >= 3u) {
            return ADS1278_CMD_VALID;
        }
        return ADS1278_CMD_ERR_INVALID_EXTCLK_DIV;
    default:
        return ADS1278_CMD_ERR_UNKNOWN_OPCODE;
    }
}

const char *ads1278_cmd_validation_result_string(ads1278_cmd_validation_result result)
{
    switch (result) {
    case ADS1278_CMD_VALID:
        return "valid";
    case ADS1278_CMD_ERR_UNKNOWN_OPCODE:
        return "unknown opcode";
    case ADS1278_CMD_ERR_INVALID_ENABLE_VALUE:
        return "SET_ENABLE requires value 0 or 1";
    case ADS1278_CMD_ERR_INVALID_EXTCLK_DIV:
        return "SET_EXTCLK_DIV requires value >= 3";
    default:
        return "invalid command";
    }
}
