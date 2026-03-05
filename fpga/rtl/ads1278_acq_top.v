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
    // Control inputs (from AXI registers)
    input  wire        ctrl_enable,
    input  wire        sync_trigger,
    input  wire [31:0] extclk_div
);

// Internal 24-bit channel data from SPI TDM
wire [23:0] spi_ch0, spi_ch1, spi_ch2, spi_ch3;
wire [23:0] spi_ch4, spi_ch5, spi_ch6, spi_ch7;
wire        spi_new_data;
wire [15:0] spi_frame_cnt;
wire        spi_overflow;

// Zero-extend 24-bit data to 32-bit registers
assign ch_data_0 = {8'd0, spi_ch0};
assign ch_data_1 = {8'd0, spi_ch1};
assign ch_data_2 = {8'd0, spi_ch2};
assign ch_data_3 = {8'd0, spi_ch3};
assign ch_data_4 = {8'd0, spi_ch4};
assign ch_data_5 = {8'd0, spi_ch5};
assign ch_data_6 = {8'd0, spi_ch6};
assign ch_data_7 = {8'd0, spi_ch7};

assign status = {spi_frame_cnt, 14'd0, spi_overflow, spi_new_data};

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
