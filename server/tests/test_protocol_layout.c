#include "protocol.h"

#include <assert.h>
#include <stddef.h>
#include <stdint.h>

int main(void)
{
    assert(sizeof(ads1278_command) == ADS1278_COMMAND_SIZE);
    assert(sizeof(ads1278_message) == ADS1278_MESSAGE_SIZE);
    assert(offsetof(ads1278_message, msg_type) == 0u);
    assert(offsetof(ads1278_message, msg_seq) == 4u);
    assert(offsetof(ads1278_message, opcode) == 8u);
    assert(offsetof(ads1278_message, value) == 12u);
    assert(offsetof(ads1278_message, status_raw) == 16u);
    assert(offsetof(ads1278_message, ctrl_raw) == 20u);
    assert(offsetof(ads1278_message, extclk_div) == 24u);
    assert(offsetof(ads1278_message, channels[0]) == 28u);
    assert(offsetof(ads1278_message, channels[7]) == 56u);
    return 0;
}
