`timescale 1 ns / 1 ps

////////////////////////////////////////////////////////////////////////////////
// Simple streaming test-pattern source for Phase 4 DDR write bring-up.
////////////////////////////////////////////////////////////////////////////////

module ads1278_dma_pattern_source (
    input  wire        clk,
    input  wire        rstn,
    input  wire        enable,
    output wire [31:0] m_axis_tdata,
    output wire        m_axis_tvalid,
    input  wire        m_axis_tready
);

reg [31:0] word_counter;

assign m_axis_tdata  = word_counter;
assign m_axis_tvalid = enable;

always @(posedge clk or negedge rstn) begin
    if (!rstn) begin
        word_counter <= 32'd0;
    end else if (!enable) begin
        word_counter <= 32'd0;
    end else if (m_axis_tvalid && m_axis_tready) begin
        word_counter <= word_counter + 32'd1;
    end
end

endmodule
