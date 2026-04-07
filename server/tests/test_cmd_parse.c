#include "cmd_parse.h"

#include <assert.h>
#include <stdint.h>
#include <string.h>

static void test_partial_reads(void)
{
    ads1278_cmd_parser parser;
    ads1278_command parsed;
    ads1278_command expected;
    uint8_t bytes[ADS1278_COMMAND_SIZE];
    size_t consumed;

    expected.opcode = ADS1278_OPCODE_SET_ENABLE;
    expected.value = 1u;
    memcpy(bytes, &expected, sizeof(bytes));

    ads1278_cmd_parser_init(&parser);
    assert(ads1278_cmd_parser_push(&parser, bytes, 3u, &parsed, &consumed) == 0);
    assert(consumed == 3u);
    assert(ads1278_cmd_parser_push(&parser, bytes + 3u, sizeof(bytes) - 3u, &parsed, &consumed) == 1);
    assert(consumed == 5u);
    assert(parsed.opcode == expected.opcode);
    assert(parsed.value == expected.value);
}

static void test_multiple_commands_in_one_buffer(void)
{
    ads1278_cmd_parser parser;
    ads1278_command commands[2];
    ads1278_command parsed;
    uint8_t bytes[ADS1278_COMMAND_SIZE * 2];
    size_t consumed;
    size_t offset;

    commands[0].opcode = ADS1278_OPCODE_TRIGGER_SYNC;
    commands[0].value = 1u;
    commands[1].opcode = ADS1278_OPCODE_SET_EXTCLK_DIV;
    commands[1].value = 625u;
    memcpy(bytes, &commands[0], ADS1278_COMMAND_SIZE);
    memcpy(bytes + ADS1278_COMMAND_SIZE, &commands[1], ADS1278_COMMAND_SIZE);

    ads1278_cmd_parser_init(&parser);
    offset = 0u;

    assert(ads1278_cmd_parser_push(&parser, bytes + offset, sizeof(bytes) - offset, &parsed, &consumed) == 1);
    offset += consumed;
    assert(parsed.opcode == commands[0].opcode);
    assert(parsed.value == commands[0].value);

    assert(ads1278_cmd_parser_push(&parser, bytes + offset, sizeof(bytes) - offset, &parsed, &consumed) == 1);
    offset += consumed;
    assert(offset == sizeof(bytes));
    assert(parsed.opcode == commands[1].opcode);
    assert(parsed.value == commands[1].value);
}

static void test_invalid_opcode_rejection(void)
{
    ads1278_command command;

    command.opcode = 99u;
    command.value = 0u;
    assert(ads1278_command_validate(&command) == ADS1278_CMD_ERR_UNKNOWN_OPCODE);
}

static void test_invalid_divider_rejection(void)
{
    ads1278_command command;

    command.opcode = ADS1278_OPCODE_SET_EXTCLK_DIV;
    command.value = 2u;
    assert(ads1278_command_validate(&command) == ADS1278_CMD_ERR_INVALID_EXTCLK_DIV);
}

int main(void)
{
    test_partial_reads();
    test_multiple_commands_in_one_buffer();
    test_invalid_opcode_rejection();
    test_invalid_divider_rejection();
    return 0;
}
