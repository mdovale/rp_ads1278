#define main ads1278_server_main
int ads1278_server_main(int argc, char **argv);
#include "../server.c"
#undef main

#include <assert.h>
#include <stdint.h>
#include <string.h>

static void make_bulk_frame(ads1278_bulk_frame *frame, uint16_t frame_count, int32_t ch1)
{
    memset(frame, 0, sizeof(*frame));
    frame->frame_count = frame_count;
    frame->status_raw = ((uint32_t)frame_count << 16) | 1u;
    frame->channels[0] = ch1;
}

static void fill_record(uint32_t *words, size_t phase, size_t index, uint16_t frame_count, int32_t ch1)
{
    size_t base = phase + (index * ADS1278_DMA_FRAME_WORDS);
    size_t padding_index;

    words[base + 0u] = frame_count;
    words[base + 1u] = ((uint32_t)frame_count << 16) | 1u;
    words[base + 2u] = (uint32_t)ch1;
    for (padding_index = ADS1278_DMA_FRAME_PAYLOAD_WORDS;
         padding_index < ADS1278_DMA_FRAME_WORDS - 1u;
         ++padding_index) {
        words[base + padding_index] = 0u;
    }
    words[base + ADS1278_DMA_FRAME_WORDS - 1u] = ADS1278_DMA_FRAME_STRIDE_CANARY;
}

static void test_phase_scoring_ignores_early_decoy_canary(void)
{
    uint32_t words[4u + (4u * ADS1278_DMA_FRAME_WORDS)];
    ads1278_ddr_map ddr;
    ads1278_dma_phase_score score;
    size_t frame_start_word;

    memset(words, 0, sizeof(words));
    words[1] = ADS1278_DMA_FRAME_STRIDE_CANARY;
    fill_record(words, 3u, 0u, 100u, 1000);
    fill_record(words, 3u, 1u, 101u, 1001);
    fill_record(words, 3u, 2u, 102u, 1002);
    fill_record(words, 3u, 3u, 103u, 1003);

    memset(&ddr, 0, sizeof(ddr));
    ddr.words = words;
    ddr.map_size = sizeof(words);

    assert(ads1278_dma_find_frame_start_word(&ddr, &frame_start_word, &score) == 0);
    assert(frame_start_word == 3u);
    assert(score.metadata_valid_records == 4u);
}

static void test_reassembler_releases_out_of_order_boundary_frames(void)
{
    ads1278_server_state state;
    ads1278_bulk_frame frame;
    ads1278_bulk_frame released[8];
    const uint16_t order[] = {10u, 11u, 9u, 13u, 12u, 14u};
    size_t index;
    size_t released_count;

    memset(&state, 0, sizeof(state));
    ads1278_dma_reassembler_reset(&state);

    for (index = 0u; index < (sizeof(order) / sizeof(order[0])); ++index) {
        memset(&frame, 0, sizeof(frame));
        frame.frame_count = order[index];
        frame.status_raw = ((uint32_t)order[index] << 16) | 1u;
        frame.channels[0] = (int32_t)order[index] * 10;
        assert(ads1278_dma_pending_insert(&state, &frame) == ADS1278_DMA_RELEASE_OK);
    }

    released_count = ads1278_dma_drain_release_queue(
        &state,
        released,
        sizeof(released) / sizeof(released[0])
    );

    assert(released_count == 6u);
    for (index = 0u; index < released_count; ++index) {
        assert(released[index].frame_count == (uint32_t)(9u + index));
    }
    assert(state.dma_pending_count == 0u);
    assert(state.stats.dma_frames_released == 6u);
}

static void test_reassembler_holds_future_frames_until_gap_arrives(void)
{
    ads1278_server_state state;
    ads1278_bulk_frame frame;
    ads1278_bulk_frame released[8];
    size_t released_count;

    memset(&state, 0, sizeof(state));
    ads1278_dma_reassembler_reset(&state);

    frame.frame_count = 20u;
    frame.status_raw = (20u << 16) | 1u;
    frame.channels[0] = 200;
    assert(ads1278_dma_pending_insert(&state, &frame) == ADS1278_DMA_RELEASE_OK);
    frame.frame_count = 21u;
    frame.status_raw = (21u << 16) | 1u;
    frame.channels[0] = 210;
    assert(ads1278_dma_pending_insert(&state, &frame) == ADS1278_DMA_RELEASE_OK);
    frame.frame_count = 23u;
    frame.status_raw = (23u << 16) | 1u;
    frame.channels[0] = 230;
    assert(ads1278_dma_pending_insert(&state, &frame) == ADS1278_DMA_RELEASE_OK);

    released_count = ads1278_dma_drain_release_queue(
        &state,
        released,
        sizeof(released) / sizeof(released[0])
    );
    assert(released_count == 2u);
    assert(released[0].frame_count == 20u);
    assert(released[1].frame_count == 21u);
    assert(state.dma_pending_count == 1u);

    frame.frame_count = 22u;
    frame.status_raw = (22u << 16) | 1u;
    frame.channels[0] = 220;
    assert(ads1278_dma_pending_insert(&state, &frame) == ADS1278_DMA_RELEASE_OK);
    released_count = ads1278_dma_drain_release_queue(
        &state,
        released,
        sizeof(released) / sizeof(released[0])
    );
    assert(released_count == 2u);
    assert(released[0].frame_count == 22u);
    assert(released[1].frame_count == 23u);
}

static void test_reassembler_releases_ping_pong_halves_in_time_order(void)
{
    ads1278_server_state state;
    ads1278_bulk_frame frame;
    ads1278_bulk_frame released[1024];
    size_t index;
    size_t released_count;

    memset(&state, 0, sizeof(state));
    ads1278_dma_reassembler_reset(&state);

    for (index = 0u; index < 512u; ++index) {
        uint16_t frame_count = (uint16_t)(48845u + index);

        make_bulk_frame(&frame, frame_count, (int32_t)index);
        assert(ads1278_dma_pending_insert(&state, &frame) == ADS1278_DMA_RELEASE_OK);
    }
    for (index = 0u; index < 512u; ++index) {
        uint16_t frame_count = (uint16_t)(48333u + index);

        make_bulk_frame(&frame, frame_count, (int32_t)index);
        assert(ads1278_dma_pending_insert(&state, &frame) == ADS1278_DMA_RELEASE_OK);
    }

    released_count = ads1278_dma_drain_release_queue(
        &state,
        released,
        sizeof(released) / sizeof(released[0])
    );

    assert(released_count == 1024u);
    for (index = 0u; index < released_count; ++index) {
        assert(released[index].frame_count == (uint32_t)(48333u + index));
    }
    assert(state.dma_pending_count == 0u);
    assert(state.stats.dma_reordered_frames == 0u);
}

static void test_reassembler_unwraps_16bit_frame_count(void)
{
    ads1278_server_state state;
    ads1278_bulk_frame frame;
    ads1278_bulk_frame released[4];
    const uint16_t order[] = {65534u, 65535u, 0u, 1u};
    size_t index;
    size_t released_count;

    memset(&state, 0, sizeof(state));
    ads1278_dma_reassembler_reset(&state);

    for (index = 0u; index < (sizeof(order) / sizeof(order[0])); ++index) {
        make_bulk_frame(&frame, order[index], (int32_t)index);
        assert(ads1278_dma_pending_insert(&state, &frame) == ADS1278_DMA_RELEASE_OK);
    }

    released_count = ads1278_dma_drain_release_queue(
        &state,
        released,
        sizeof(released) / sizeof(released[0])
    );

    assert(released_count == 4u);
    assert(released[0].frame_count == 65534u);
    assert(released[1].frame_count == 65535u);
    assert(released[2].frame_count == 65536u);
    assert(released[3].frame_count == 65537u);
}

static void test_reassembler_resyncs_after_newer_half_drained_first(void)
{
    ads1278_server_state state;
    ads1278_bulk_frame frame;
    ads1278_bulk_frame released[1024];
    size_t index;
    size_t released_count;

    memset(&state, 0, sizeof(state));
    ads1278_dma_reassembler_reset(&state);

    for (index = 0u; index < 512u; ++index) {
        uint16_t frame_count = (uint16_t)(48845u + index);

        make_bulk_frame(&frame, frame_count, (int32_t)index);
        assert(ads1278_dma_pending_insert(&state, &frame) == ADS1278_DMA_RELEASE_OK);
    }
    released_count = ads1278_dma_drain_release_queue(
        &state,
        released,
        sizeof(released) / sizeof(released[0])
    );
    assert(released_count == 512u);
    assert(released[0].frame_count == 48845u);
    assert(released[511].frame_count == 49356u);
    assert(state.dma_pending_count == 0u);

    for (index = 0u; index < 512u; ++index) {
        uint16_t frame_count = (uint16_t)(48333u + index);

        make_bulk_frame(&frame, frame_count, (int32_t)index);
        assert(ads1278_dma_pending_insert(&state, &frame) == ADS1278_DMA_RELEASE_OK);
    }
    released_count = ads1278_dma_drain_release_queue(
        &state,
        released,
        sizeof(released) / sizeof(released[0])
    );
    assert(released_count == 512u);
    for (index = 0u; index < released_count; ++index) {
        assert(released[index].frame_count == (uint32_t)(48333u + index));
    }
    assert(state.dma_pending_count == 0u);
    assert(state.stats.dma_queue_full == 0u);
}

static void test_reassembler_reports_queue_full_separately(void)
{
    ads1278_server_state state;
    ads1278_bulk_frame frame;
    size_t index;
    ads1278_dma_release_result result;

    memset(&state, 0, sizeof(state));
    ads1278_dma_reassembler_reset(&state);

    for (index = 0u; index < ADS1278_DMA_REORDER_CAPACITY; ++index) {
        make_bulk_frame(&frame, (uint16_t)index, (int32_t)index);
        assert(ads1278_dma_pending_insert(&state, &frame) == ADS1278_DMA_RELEASE_OK);
    }
    make_bulk_frame(&frame, (uint16_t)ADS1278_DMA_REORDER_CAPACITY, 0);
    result = ads1278_dma_pending_insert(&state, &frame);

    assert(result == ADS1278_DMA_RELEASE_QUEUE_FULL);
    ads1278_dma_record_rejected_frame(&state, result, &frame);
    assert(state.stats.dma_queue_full == 1u);
    assert(state.stats.dma_reordered_frames == 0u);
    assert(state.stats.dma_frame_gaps == 0u);
}

int main(void)
{
    test_phase_scoring_ignores_early_decoy_canary();
    test_reassembler_releases_out_of_order_boundary_frames();
    test_reassembler_holds_future_frames_until_gap_arrives();
    test_reassembler_releases_ping_pong_halves_in_time_order();
    test_reassembler_resyncs_after_newer_half_drained_first();
    test_reassembler_unwraps_16bit_frame_count();
    test_reassembler_reports_queue_full_separately();
    return 0;
}
