`timescale 1 ns / 1 ps

////////////////////////////////////////////////////////////////////////////////
// Serialize 320-bit DMA frame FIFO records into a 32-bit AXI stream.
// Payload word order matches docs/feats/dma-frame-record.md (10 words).
// Emits 32 stream words per capture (128 B DDR stride) so one record fills the
// minimum axis_ram_writer burst (32 stream words = 128 B). See dma-frame-record.md.
////////////////////////////////////////////////////////////////////////////////

module ads1278_dma_fifo_axis (
    input  wire        clk,
    input  wire        rstn,
    input  wire        enable,
    input  wire        fifo_empty,
    input  wire [319:0] fifo_dout,
    output reg         fifo_pop,
    output reg  [31:0] m_axis_tdata,
    output wire        m_axis_tvalid,
    input  wire        m_axis_tready
);

localparam integer FRAME_PAYLOAD_WORDS = 10;
localparam integer FRAME_STREAM_WORDS  = 32;
localparam [31:0]  FRAME_STRIDE_CANARY = 32'hAD12_7831;

reg [319:0] frame_reg;
reg [5:0]   beat_idx;
reg         frame_active;
reg         load_frame;

wire beat_xfer = m_axis_tvalid && m_axis_tready;
wire last_beat = (beat_idx == (FRAME_STREAM_WORDS - 1));

assign m_axis_tvalid = enable && frame_active;

always @(*) begin
    if (beat_idx < FRAME_PAYLOAD_WORDS) begin
        case (beat_idx[3:0])
            4'd0:  m_axis_tdata = frame_reg[319:288];
            4'd1:  m_axis_tdata = frame_reg[287:256];
            4'd2:  m_axis_tdata = frame_reg[255:224];
            4'd3:  m_axis_tdata = frame_reg[223:192];
            4'd4:  m_axis_tdata = frame_reg[191:160];
            4'd5:  m_axis_tdata = frame_reg[159:128];
            4'd6:  m_axis_tdata = frame_reg[127:96];
            4'd7:  m_axis_tdata = frame_reg[95:64];
            4'd8:  m_axis_tdata = frame_reg[63:32];
            default: m_axis_tdata = frame_reg[31:0];
        endcase
    end else if (beat_idx == (FRAME_STREAM_WORDS - 1)) begin
        m_axis_tdata = FRAME_STRIDE_CANARY;
    end else begin
        m_axis_tdata = 32'd0;
    end
end

always @(posedge clk or negedge rstn) begin
    if (!rstn) begin
        frame_reg    <= 320'd0;
        beat_idx     <= 6'd0;
        frame_active <= 1'b0;
        load_frame   <= 1'b0;
        fifo_pop     <= 1'b0;
    end else if (!enable) begin
        frame_reg    <= 320'd0;
        beat_idx     <= 6'd0;
        frame_active <= 1'b0;
        load_frame   <= 1'b0;
        fifo_pop     <= 1'b0;
    end else begin
        fifo_pop <= 1'b0;

        if (load_frame) begin
            frame_reg    <= fifo_dout;
            beat_idx     <= 6'd0;
            frame_active <= 1'b1;
            load_frame   <= 1'b0;
        end else if (!frame_active && !fifo_empty) begin
            fifo_pop   <= 1'b1;
            load_frame <= 1'b1;
        end else if (frame_active && beat_xfer) begin
            if (last_beat) begin
                frame_active <= 1'b0;
                beat_idx     <= 6'd0;
            end else begin
                beat_idx <= beat_idx + 6'd1;
            end
        end
    end
end

endmodule
