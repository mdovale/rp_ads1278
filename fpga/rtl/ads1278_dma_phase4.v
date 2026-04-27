`timescale 1 ns / 1 ps

////////////////////////////////////////////////////////////////////////////////
// Phase 4 DMA bring-up block:
// - streams a deterministic test pattern
// - writes bursts into DDR via a PS HP port
// - keeps the legacy MMIO plane untouched
////////////////////////////////////////////////////////////////////////////////

module ads1278_dma_phase4 #(
    parameter [31:0] DDR_BASE_ADDR = 32'h1E00_0000,
    parameter [15:0] BURST_COUNT_MAX = 16'd511
) (
    input  wire        clk,
    input  wire        rstn,
    input  wire        enable,
    input  wire [1:0]  mode_select,
    input  wire [31:0] base_addr,
    input  wire [31:0] buffer_size_bytes,

    output wire [15:0] write_index,
    output wire        wrap_pulse,
    output wire        running,
    output wire        config_error,
    output wire        bresp_error_pulse,
    output wire [1:0]  last_bresp,

    output wire [5:0]  m_axi_awid,
    output wire [31:0] m_axi_awaddr,
    output wire [3:0]  m_axi_awlen,
    output wire [2:0]  m_axi_awsize,
    output wire [1:0]  m_axi_awburst,
    output wire [1:0]  m_axi_awlock,
    output wire [3:0]  m_axi_awcache,
    output wire [2:0]  m_axi_awprot,
    output wire [3:0]  m_axi_awqos,
    output wire        m_axi_awvalid,
    input  wire        m_axi_awready,

    output wire [5:0]  m_axi_wid,
    output wire [63:0] m_axi_wdata,
    output wire [7:0]  m_axi_wstrb,
    output wire        m_axi_wlast,
    output wire        m_axi_wvalid,
    input  wire        m_axi_wready,

    input  wire [5:0]  m_axi_bid,
    input  wire [1:0]  m_axi_bresp,
    input  wire        m_axi_bvalid,
    output wire        m_axi_bready,

    output wire [5:0]  m_axi_arid,
    output wire [31:0] m_axi_araddr,
    output wire [3:0]  m_axi_arlen,
    output wire [2:0]  m_axi_arsize,
    output wire [1:0]  m_axi_arburst,
    output wire [1:0]  m_axi_arlock,
    output wire [3:0]  m_axi_arcache,
    output wire [2:0]  m_axi_arprot,
    output wire [3:0]  m_axi_arqos,
    output wire        m_axi_arvalid,
    input  wire        m_axi_arready,

    input  wire [5:0]  m_axi_rid,
    input  wire [63:0] m_axi_rdata,
    input  wire [1:0]  m_axi_rresp,
    input  wire        m_axi_rlast,
    input  wire        m_axi_rvalid,
    output wire        m_axi_rready
);

wire [31:0] pattern_tdata;
wire        pattern_tvalid;
wire        pattern_tready;
wire [15:0] writer_burst_index;
wire [31:0] dma_base_addr;
wire [15:0] burst_count_max;
wire [24:0] configured_burst_count;
wire        mode_supported;
wire        size_aligned;
wire        size_in_range;
wire        size_nonzero;
wire        writer_enable;

reg [1:0]   last_bresp_reg;

assign dma_base_addr = (base_addr != 32'd0) ? base_addr : DDR_BASE_ADDR;
assign configured_burst_count = buffer_size_bytes[31:7];
assign size_aligned = (buffer_size_bytes[6:0] == 7'd0);
assign size_in_range = (configured_burst_count != 25'd0) && (configured_burst_count <= 25'd65536);
assign size_nonzero = (buffer_size_bytes != 32'd0);
assign mode_supported = (mode_select == 2'd0);
assign config_error = ~mode_supported | ~size_nonzero | ~size_aligned | ~size_in_range;
assign burst_count_max = size_in_range ? (configured_burst_count[15:0] - 16'd1) : BURST_COUNT_MAX;
assign writer_enable = enable & ~config_error;
assign write_index = writer_burst_index;
assign running = writer_enable;
assign wrap_pulse = m_axi_awvalid && m_axi_awready && (writer_burst_index == burst_count_max);
assign bresp_error_pulse = m_axi_bvalid && m_axi_bready && (m_axi_bresp != 2'b00);
assign last_bresp = last_bresp_reg;

always @(posedge clk or negedge rstn) begin
    if (!rstn) begin
        last_bresp_reg <= 2'b00;
    end else if (!writer_enable) begin
        last_bresp_reg <= 2'b00;
    end else if (m_axi_bvalid && m_axi_bready) begin
        last_bresp_reg <= m_axi_bresp;
    end
end

ads1278_dma_pattern_source u_pattern (
    .clk          (clk),
    .rstn         (rstn),
    .enable       (writer_enable),
    .m_axis_tdata (pattern_tdata),
    .m_axis_tvalid(pattern_tvalid),
    .m_axis_tready(pattern_tready)
);

axis_ram_writer #(
    .ADDR_WIDTH      (16),
    .AXI_ID_WIDTH    (6),
    .AXI_ADDR_WIDTH  (32),
    .AXI_DATA_WIDTH  (64),
    .AXIS_TDATA_WIDTH(32),
    .FIFO_WRITE_DEPTH(1024)
) u_writer (
    .aclk         (clk),
    .aresetn      (rstn & writer_enable),
    .min_addr     (dma_base_addr),
    .cfg_data     (burst_count_max),
    .sts_data     (writer_burst_index),
    .m_axi_awid   (m_axi_awid),
    .m_axi_awlen  (m_axi_awlen),
    .m_axi_awsize (m_axi_awsize),
    .m_axi_awburst(m_axi_awburst),
    .m_axi_awcache(m_axi_awcache),
    .m_axi_awaddr (m_axi_awaddr),
    .m_axi_awvalid(m_axi_awvalid),
    .m_axi_awready(m_axi_awready),
    .m_axi_wid    (m_axi_wid),
    .m_axi_wstrb  (m_axi_wstrb),
    .m_axi_wlast  (m_axi_wlast),
    .m_axi_wdata  (m_axi_wdata),
    .m_axi_wvalid (m_axi_wvalid),
    .m_axi_wready (m_axi_wready),
    .m_axi_bvalid (m_axi_bvalid),
    .m_axi_bready (m_axi_bready),
    .s_axis_tdata (pattern_tdata),
    .s_axis_tvalid(pattern_tvalid),
    .s_axis_tready(pattern_tready)
);

assign m_axi_awlock  = 2'b00;
assign m_axi_awprot  = 3'b000;
assign m_axi_awqos   = 4'b0000;

assign m_axi_arid    = 6'd0;
assign m_axi_araddr  = 32'd0;
assign m_axi_arlen   = 4'd0;
assign m_axi_arsize  = 3'd0;
assign m_axi_arburst = 2'd0;
assign m_axi_arlock  = 2'd0;
assign m_axi_arcache = 4'd0;
assign m_axi_arprot  = 3'd0;
assign m_axi_arqos   = 4'd0;
assign m_axi_arvalid = 1'b0;
assign m_axi_rready  = 1'b1;

endmodule
