`timescale 1 ns / 1 ps

////////////////////////////////////////////////////////////////////////////////
// Reference-style AXI burst writer adapted from the Red Pitaya DMA examples.
// Writes 16-beat bursts into DDR after enough stream data has accumulated.
////////////////////////////////////////////////////////////////////////////////

module axis_ram_writer #(
    parameter integer ADDR_WIDTH = 16,
    parameter integer AXI_ID_WIDTH = 6,
    parameter integer AXI_ADDR_WIDTH = 32,
    parameter integer AXI_DATA_WIDTH = 64,
    parameter integer AXIS_TDATA_WIDTH = 64,
    parameter integer FIFO_WRITE_DEPTH = 512
) (
    input  wire                        aclk,
    input  wire                        aresetn,

    input  wire [AXI_ADDR_WIDTH-1:0]   min_addr,
    input  wire [ADDR_WIDTH-1:0]       cfg_data,
    output wire [ADDR_WIDTH-1:0]       sts_data,

    output wire [AXI_ID_WIDTH-1:0]     m_axi_awid,
    output wire [3:0]                  m_axi_awlen,
    output wire [2:0]                  m_axi_awsize,
    output wire [1:0]                  m_axi_awburst,
    output wire [3:0]                  m_axi_awcache,
    output wire [AXI_ADDR_WIDTH-1:0]   m_axi_awaddr,
    output wire                        m_axi_awvalid,
    input  wire                        m_axi_awready,

    output wire [AXI_ID_WIDTH-1:0]     m_axi_wid,
    output wire [AXI_DATA_WIDTH/8-1:0] m_axi_wstrb,
    output wire                        m_axi_wlast,
    output wire [AXI_DATA_WIDTH-1:0]   m_axi_wdata,
    output wire                        m_axi_wvalid,
    input  wire                        m_axi_wready,

    input  wire                        m_axi_bvalid,
    output wire                        m_axi_bready,

    input  wire [AXIS_TDATA_WIDTH-1:0] s_axis_tdata,
    input  wire                        s_axis_tvalid,
    output wire                        s_axis_tready
);

localparam integer ADDR_SIZE = $clog2(AXI_DATA_WIDTH / 8);
localparam integer COUNT_WIDTH =
    $clog2(FIFO_WRITE_DEPTH * AXIS_TDATA_WIDTH / AXI_DATA_WIDTH) + 1;
localparam [2:0] AXI_BURST_SIZE = ADDR_SIZE;

reg                       int_awvalid_reg;
reg                       int_wvalid_reg;
reg  [3:0]               int_cntr_reg;
reg  [ADDR_WIDTH-1:0]    int_addr_reg;

wire                      int_full_wire;
wire                      int_valid_wire;
wire                      int_awvalid_wire;
wire                      int_awready_wire;
wire                      int_wlast_wire;
wire                      int_wvalid_wire;
wire                      int_wready_wire;
wire                      int_rden_wire;
wire [COUNT_WIDTH-1:0]    int_count_wire;
wire [AXI_DATA_WIDTH-1:0] int_wdata_wire;

assign int_valid_wire   = (int_count_wire > 15) && !int_wvalid_reg;
assign int_awvalid_wire = int_valid_wire || int_awvalid_reg;
assign int_wvalid_wire  = int_valid_wire || int_wvalid_reg;
assign int_rden_wire    = int_wvalid_wire && int_wready_wire;
assign int_wlast_wire   = &int_cntr_reg;

xpm_fifo_sync #(
    .WRITE_DATA_WIDTH (AXIS_TDATA_WIDTH),
    .FIFO_WRITE_DEPTH (FIFO_WRITE_DEPTH),
    .READ_DATA_WIDTH  (AXI_DATA_WIDTH),
    .READ_MODE        ("fwft"),
    .FIFO_READ_LATENCY(0),
    .FIFO_MEMORY_TYPE ("block"),
    .USE_ADV_FEATURES ("0400"),
    .RD_DATA_COUNT_WIDTH(COUNT_WIDTH)
) fifo_0 (
    .full         (int_full_wire),
    .rd_data_count(int_count_wire),
    .rst          (~aresetn),
    .wr_clk       (aclk),
    .wr_en        (s_axis_tvalid && s_axis_tready),
    .din          (s_axis_tdata),
    .rd_en        (int_rden_wire),
    .dout         (int_wdata_wire)
);

always @(posedge aclk) begin
    if (~aresetn) begin
        int_awvalid_reg <= 1'b0;
        int_wvalid_reg  <= 1'b0;
        int_cntr_reg    <= 4'd0;
        int_addr_reg    <= {ADDR_WIDTH{1'b0}};
    end else begin
        if (int_valid_wire) begin
            int_awvalid_reg <= 1'b1;
            int_wvalid_reg  <= 1'b1;
            int_cntr_reg    <= 4'd0;
        end

        if (int_awvalid_wire && int_awready_wire) begin
            int_awvalid_reg <= 1'b0;
            int_addr_reg    <=
                (int_addr_reg < cfg_data) ? (int_addr_reg + 1'b1) : {ADDR_WIDTH{1'b0}};
        end

        if (int_rden_wire) begin
            int_cntr_reg <= int_cntr_reg + 1'b1;
        end

        if (int_wready_wire && int_wlast_wire) begin
            int_wvalid_reg <= 1'b0;
        end
    end
end

output_buffer #(
    .DATA_WIDTH(AXI_ADDR_WIDTH)
) buf_aw (
    .aclk     (aclk),
    .aresetn  (aresetn),
    .in_data  (min_addr + {int_addr_reg, 4'd0, {ADDR_SIZE{1'b0}}}),
    .in_valid (int_awvalid_wire),
    .in_ready (int_awready_wire),
    .out_data (m_axi_awaddr),
    .out_valid(m_axi_awvalid),
    .out_ready(m_axi_awready)
);

output_buffer #(
    .DATA_WIDTH(AXI_DATA_WIDTH + 1)
) buf_w (
    .aclk     (aclk),
    .aresetn  (aresetn),
    .in_data  ({int_wlast_wire, int_wdata_wire}),
    .in_valid (int_wvalid_wire),
    .in_ready (int_wready_wire),
    .out_data ({m_axi_wlast, m_axi_wdata}),
    .out_valid(m_axi_wvalid),
    .out_ready(m_axi_wready)
);

assign sts_data     = int_addr_reg;
assign m_axi_awid   = {AXI_ID_WIDTH{1'b0}};
assign m_axi_awlen  = 4'd15;
assign m_axi_awsize = AXI_BURST_SIZE;
assign m_axi_awburst = 2'b01;
assign m_axi_awcache = 4'b1111;

assign m_axi_wid    = {AXI_ID_WIDTH{1'b0}};
assign m_axi_wstrb  = {AXI_DATA_WIDTH/8{1'b1}};
assign m_axi_bready = 1'b1;
assign s_axis_tready = ~int_full_wire;

endmodule
