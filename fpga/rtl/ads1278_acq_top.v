`timescale 1 ns / 1 ps

////////////////////////////////////////////////////////////////////////////////
// ADS1278 acquisition top — wraps SPI TDM, EXTCLK generator, SYNC pulse.
////////////////////////////////////////////////////////////////////////////////

module ads1278_acq_top (
    input  wire        clk,
    input  wire        rstn,
    // External SPI / control signals
    output wire        sclk_o,
    input  wire        miso_i,
    input  wire        drdy_n_i,
    output wire        sync_n_o,
    output wire        extclk_o,
    input  wire        mod_i,
    // Channel data (32-bit, 24-bit sample zero-extended)
    output wire [31:0] ch_data_0,
    output wire [31:0] ch_data_1,
    output wire [31:0] ch_data_2,
    output wire [31:0] ch_data_3,
    output wire [31:0] ch_data_4,
    output wire [31:0] ch_data_5,
    output wire [31:0] ch_data_6,
    output wire [31:0] ch_data_7,
    // Status: [0] new_data, [1] overflow, [31:16] frame_cnt
    output wire [31:0] status,
    // FIFO debug: [15:0] level, [16] empty, [17] full
    output wire [31:0] fifo_status,
    output wire [31:0] fifo_drop_count,
    output wire [31:0] fifo_capacity,
    // Staged DMA FIFO read port (consumed by ads1278_dma_phase4 capture mode)
    output wire [319:0] dma_fifo_dout,
    output wire        dma_fifo_empty,
    input  wire        dma_fifo_pop,
    // Control inputs (from AXI registers)
    input  wire        ctrl_enable,
    input  wire        demod_enable,
    input  wire        sync_trigger,
    input  wire [31:0] extclk_div,
    input  wire [15:0] demod_skip
);

localparam integer DMA_FIFO_DEPTH = 512;
localparam integer DMA_FIFO_LEVEL_W = $clog2(DMA_FIFO_DEPTH + 1);

// Internal 24-bit channel data from SPI TDM
wire [23:0] spi_ch0, spi_ch1, spi_ch2, spi_ch3;
wire [23:0] spi_ch4, spi_ch5, spi_ch6, spi_ch7;
wire [23:0] spi_ch7_effective;
wire        spi_new_data;
wire [15:0] spi_frame_cnt;
wire        spi_overflow;
wire [31:0] dma_status_raw;
wire [31:0] demod_ch1;

// FIFO state for staged DMA bring-up
wire [319:0] fifo_frame_in;
wire [319:0] fifo_frame_out;
wire [DMA_FIFO_LEVEL_W-1:0] fifo_level_raw;
wire        fifo_empty_raw;
wire        fifo_full_raw;
wire [15:0] fifo_level_dbg;
wire        fifo_push;
reg  [31:0] fifo_drop_count_reg;

// Zero-extend 24-bit data to 32-bit registers
assign ch_data_0 = {8'd0, spi_ch0};
assign ch_data_1 = {8'd0, spi_ch1};
assign ch_data_2 = {8'd0, spi_ch2};
assign ch_data_3 = {8'd0, spi_ch3};
assign ch_data_4 = {8'd0, spi_ch4};
assign ch_data_5 = {8'd0, spi_ch5};
assign ch_data_6 = {8'd0, spi_ch6};
assign ch_data_7 = {8'd0, spi_ch7_effective};

assign dma_status_raw = {spi_frame_cnt, 14'd0, spi_overflow, spi_new_data};
assign status = dma_status_raw;

assign fifo_push = ctrl_enable && spi_new_data;
assign fifo_level_dbg = {{(16 - DMA_FIFO_LEVEL_W){1'b0}}, fifo_level_raw};
assign fifo_status = {14'd0, fifo_full_raw, fifo_empty_raw, fifo_level_dbg};
assign fifo_drop_count = fifo_drop_count_reg;
assign fifo_capacity = DMA_FIFO_DEPTH;
assign dma_fifo_dout = fifo_frame_out;
assign dma_fifo_empty = fifo_empty_raw;

assign fifo_frame_in = {
    {16'd0, spi_frame_cnt},
    dma_status_raw,
    {{8{spi_ch0[23]}}, spi_ch0},
    {{8{spi_ch1[23]}}, spi_ch1},
    {{8{spi_ch2[23]}}, spi_ch2},
    {{8{spi_ch3[23]}}, spi_ch3},
    {{8{spi_ch4[23]}}, spi_ch4},
    {{8{spi_ch5[23]}}, spi_ch5},
    {{8{spi_ch6[23]}}, spi_ch6},
    {{8{spi_ch7_effective[23]}}, spi_ch7_effective}
};

assign spi_ch7_effective = demod_enable ? demod_ch1[23:0] : spi_ch7;

ads1278_demod u_demod_ch1 (
    .clk       (clk),
    .rstn      (rstn),
    .enable    (ctrl_enable && demod_enable),
    .new_data  (spi_new_data),
    .mod_i     (mod_i),
    .sample    (spi_ch0),
    .demod_skip(demod_skip),
    .demod_out (demod_ch1)
);

ads1278_frame_fifo #(
    .DATA_W  (320),
    .DEPTH   (DMA_FIFO_DEPTH),
    .LEVEL_W (DMA_FIFO_LEVEL_W)
) u_frame_fifo (
    .clk   (clk),
    .rstn  (rstn),
    .clear (~ctrl_enable),
    .push  (fifo_push),
    .pop   (dma_fifo_pop),
    .din   (fifo_frame_in),
    .dout  (fifo_frame_out),
    .empty (fifo_empty_raw),
    .full  (fifo_full_raw),
    .level (fifo_level_raw)
);

always @(posedge clk or negedge rstn) begin
    if (!rstn) begin
        fifo_drop_count_reg <= 32'd0;
    end else if (!ctrl_enable) begin
        fifo_drop_count_reg <= 32'd0;
    end else if (fifo_push && fifo_full_raw) begin
        fifo_drop_count_reg <= fifo_drop_count_reg + 32'd1;
    end
end

// ---- SPI TDM receiver ----
ads1278_spi_tdm u_spi_tdm (
    .clk        (clk),
    .rstn       (rstn),
    .enable     (ctrl_enable),
    .miso_i     (miso_i),
    .drdy_n_i   (drdy_n_i),
    .sclk_div   (extclk_div),
    .sclk_o     (sclk_o),
    .ch_data_0  (spi_ch0),
    .ch_data_1  (spi_ch1),
    .ch_data_2  (spi_ch2),
    .ch_data_3  (spi_ch3),
    .ch_data_4  (spi_ch4),
    .ch_data_5  (spi_ch5),
    .ch_data_6  (spi_ch6),
    .ch_data_7  (spi_ch7),
    .new_data   (spi_new_data),
    .frame_cnt  (spi_frame_cnt),
    .overflow   (spi_overflow)
);

// ---- EXTCLK generator ----
ads1278_extclk_gen u_extclk (
    .clk        (clk),
    .rstn       (rstn),
    .enable     (ctrl_enable),
    .div_val    (extclk_div),
    .extclk_o   (extclk_o)
);

// ---- SYNC pulse generator ----
ads1278_sync_pulse u_sync (
    .clk          (clk),
    .rstn         (rstn),
    .trigger      (sync_trigger),
    .extclk_div   (extclk_div),
    .sync_n_o     (sync_n_o)
);

endmodule
