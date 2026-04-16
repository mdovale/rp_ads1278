#ifndef ADS1278_PROTOCOL_H
#define ADS1278_PROTOCOL_H

#include <stdint.h>

#if defined(__BYTE_ORDER__) && (__BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__)
#error "rp_ads1278 server protocol requires a little-endian host"
#endif

#define ADS1278_SERVER_PORT 5000u
#define ADS1278_CAPABILITY_LINE "RP_CAP:ads1278_v1\n"

enum {
    ADS1278_CHANNEL_COUNT = 8,
    ADS1278_COMMAND_WORDS = 2,
    ADS1278_COMMAND_SIZE = 8,
    ADS1278_MESSAGE_WORDS = 15,
    ADS1278_MESSAGE_SIZE = 60
};

enum {
    ADS1278_OPCODE_SET_ENABLE = 1,
    ADS1278_OPCODE_TRIGGER_SYNC = 2,
    ADS1278_OPCODE_SET_EXTCLK_DIV = 3,
    ADS1278_OPCODE_MARK_CAPTURE = 4
};

enum {
    ADS1278_MSG_SAMPLE = 1,
    ADS1278_MSG_ACK = 2,
    ADS1278_MSG_ERROR = 3
};

#if defined(__GNUC__) || defined(__clang__)
#define ADS1278_PACKED __attribute__((packed))
#else
#define ADS1278_PACKED
#endif

typedef struct ADS1278_PACKED {
    uint32_t opcode;
    uint32_t value;
} ads1278_command;

typedef struct ADS1278_PACKED {
    uint32_t msg_type;
    uint32_t msg_seq;
    uint32_t opcode;
    uint32_t value;
    uint32_t status_raw;
    uint32_t ctrl_raw;
    uint32_t extclk_div;
    int32_t channels[ADS1278_CHANNEL_COUNT];
} ads1278_message;

typedef char ads1278_command_size_must_be_8_bytes[
    (sizeof(ads1278_command) == ADS1278_COMMAND_SIZE) ? 1 : -1
];
typedef char ads1278_message_size_must_be_60_bytes[
    (sizeof(ads1278_message) == ADS1278_MESSAGE_SIZE) ? 1 : -1
];

#endif
