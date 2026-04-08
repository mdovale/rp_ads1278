////////////////////////////////////////////////////////////////////////////////
// Red Pitaya TOP module for ADS1278 acquisition.
// Based on RedPitaya axi4lite project; axi4lite_gpio replaced with
// ads1278_axi_slave.  Expansion pins use explicit tri-state buffers so the
// top-level preserves the stock Red Pitaya inout contract.
////////////////////////////////////////////////////////////////////////////////

module red_pitaya_top #(
  bit [0:5*32-1] GITH = '0,
  int unsigned MNO = 2,
  int unsigned MNG = 2
)(
  // PS connections
  inout  logic [54-1:0] FIXED_IO_mio     ,
  inout  logic          FIXED_IO_ps_clk  ,
  inout  logic          FIXED_IO_ps_porb ,
  inout  logic          FIXED_IO_ps_srstb,
  inout  logic          FIXED_IO_ddr_vrn ,
  inout  logic          FIXED_IO_ddr_vrp ,
  // DDR
  inout  logic [15-1:0] DDR_addr   ,
  inout  logic [ 3-1:0] DDR_ba     ,
  inout  logic          DDR_cas_n  ,
  inout  logic          DDR_ck_n   ,
  inout  logic          DDR_ck_p   ,
  inout  logic          DDR_cke    ,
  inout  logic          DDR_cs_n   ,
  inout  logic [ 4-1:0] DDR_dm     ,
  inout  logic [32-1:0] DDR_dq     ,
  inout  logic [ 4-1:0] DDR_dqs_n  ,
  inout  logic [ 4-1:0] DDR_dqs_p  ,
  inout  logic          DDR_odt    ,
  inout  logic          DDR_ras_n  ,
  inout  logic          DDR_reset_n,
  inout  logic          DDR_we_n   ,
  // Red Pitaya periphery — ADC
  input  logic [MNO-1:0] [16-1:0] adc_dat_i,
  input  logic           [ 2-1:0] adc_clk_i,
  output logic           [ 2-1:0] adc_clk_o,
  output logic                    adc_cdcs_o,
  // DAC
  output logic [14-1:0] dac_dat_o  ,
  output logic          dac_wrt_o  ,
  output logic          dac_sel_o  ,
  output logic          dac_clk_o  ,
  output logic          dac_rst_o  ,
  // PDM DAC
  output logic [ 4-1:0] dac_pwm_o  ,
  // Expansion connector (directly wired to ADS1278 signals)
  inout  logic [ 8-1:0] exp_p_io   ,
  inout  logic [ 8-1:0] exp_n_io   ,
  // SATA connector
  output logic [ 2-1:0] daisy_p_o  ,
  output logic [ 2-1:0] daisy_n_o  ,
  input  logic [ 2-1:0] daisy_p_i  ,
  input  logic [ 2-1:0] daisy_n_i  ,
  // LED
  output logic [ 8-1:0] led_o
);

////////////////////////////////////////////////////////////////////////////////
// local signals
////////////////////////////////////////////////////////////////////////////////

localparam type DTG = logic   signed [14-1:0];
localparam type DTO = logic   signed [16-1:0];

logic [4-1:0] fclk ;
logic [4-1:0] frstn;

// PLL signals
logic adc_clk_in;
logic pll_adc_clk;
logic pll_locked;

// ADC clock
logic adc_clk;

// DAC signals
logic dac_clk_1x;
logic dac_clk_2x;
logic dac_clk_2p;
logic dac_rst;

////////////////////////////////////////////////////////////////////////////////
// PLL (clock and reset)
////////////////////////////////////////////////////////////////////////////////

IBUFDS i_clk (.I (adc_clk_i[1]), .IB (adc_clk_i[0]), .O (adc_clk_in));

red_pitaya_pll pll (
  .clk         (adc_clk_in),
  .rstn        (frstn[0]  ),
  .clk_adc     (pll_adc_clk),
  .clk_dac_1x  (dac_clk_1x ),
  .clk_dac_2x  (dac_clk_2x ),
  .clk_dac_2p  (dac_clk_2p ),
  .clk_ser     (           ),
  .clk_pdm     (           ),
  .pll_locked  (pll_locked)
);

BUFG bufg_adc_clk (.O (adc_clk), .I (pll_adc_clk));

logic top_rst;
assign top_rst = ~frstn[0] | ~pll_locked;

always_ff @(posedge dac_clk_1x, posedge top_rst)
if (top_rst) dac_rst  <= 1'b1;
else         dac_rst  <= top_rst;

// Expansion connector buffering
logic [8-1:0] exp_p_in;
logic [8-1:0] exp_p_out;
logic [8-1:0] exp_p_t;
logic [8-1:0] exp_n_in;
logic [8-1:0] exp_n_out;
logic [8-1:0] exp_n_t;

generate
for (genvar i = 0; i < 8; i++) begin : gen_exp_iobuf
  IOBUF iobuf_exp_p (
    .I  (exp_p_out[i]),
    .IO (exp_p_io[i]),
    .O  (exp_p_in[i]),
    .T  (exp_p_t[i])
  );

  IOBUF iobuf_exp_n (
    .I  (exp_n_out[i]),
    .IO (exp_n_io[i]),
    .O  (exp_n_in[i]),
    .T  (exp_n_t[i])
  );
end
endgenerate

////////////////////////////////////////////////////////////////////////////////
// ADC IO (active for RP board compatibility)
////////////////////////////////////////////////////////////////////////////////

generate
for (genvar i=0; i<MNO; i++) begin: for_adc
  DTO adc_raw;
  always_ff @(posedge adc_clk)
  adc_raw <= adc_dat_i[i];
end: for_adc
endgenerate

assign adc_clk_o  = 2'b10;
assign adc_cdcs_o = 1'b1;

////////////////////////////////////////////////////////////////////////////////
// DAC IO (active for RP board compatibility)
////////////////////////////////////////////////////////////////////////////////

logic [MNG-1:0] [14-1:0] dac_raw;

generate
for (genvar i=0; i<MNG; i++) begin: for_dac
  always_ff @(posedge dac_clk_1x)
  if (dac_rst) dac_raw[i] <= '0;
  else         dac_raw[i] <= '0;
end: for_dac
endgenerate

ODDR oddr_dac_clk          (.Q(dac_clk_o), .D1(1'b0      ), .D2(1'b1      ), .C(dac_clk_2p), .CE(1'b1), .R(1'b0   ), .S(1'b0));
ODDR oddr_dac_wrt          (.Q(dac_wrt_o), .D1(1'b0      ), .D2(1'b1      ), .C(dac_clk_2x), .CE(1'b1), .R(1'b0   ), .S(1'b0));
ODDR oddr_dac_sel          (.Q(dac_sel_o), .D1(1'b0      ), .D2(1'b1      ), .C(dac_clk_1x), .CE(1'b1), .R(dac_rst), .S(1'b0));
ODDR oddr_dac_rst          (.Q(dac_rst_o), .D1(dac_rst   ), .D2(dac_rst   ), .C(dac_clk_1x), .CE(1'b1), .R(1'b0   ), .S(1'b0));
ODDR oddr_dac_dat [14-1:0] (.Q(dac_dat_o), .D1(dac_raw[0]), .D2(dac_raw[1]), .C(dac_clk_1x), .CE(1'b1), .R(dac_rst), .S(1'b0));

////////////////////////////////////////////////////////////////////////////////
// PWM DAC (active for RP board compatibility — drive low)
////////////////////////////////////////////////////////////////////////////////

assign dac_pwm_o = 4'h0;

////////////////////////////////////////////////////////////////////////////////
// Daisy chain (unused)
////////////////////////////////////////////////////////////////////////////////

assign daisy_p_o = 1'bz;
assign daisy_n_o = 1'bz;

////////////////////////////////////////////////////////////////////////////////
// PS connections
////////////////////////////////////////////////////////////////////////////////

gpio_if #(.DW (24)) gpio_dummy ();

logic gpio_irq;

// Keep the PS-facing AXI path on the stock FCLK/reset pair instead of tying it
// to the ADC PLL domain.
axi4_lite_if bus (.ACLK (fclk[0]), .ARESETn (frstn[0]));

red_pitaya_ps ps (
  .FIXED_IO_mio       (FIXED_IO_mio     ),
  .FIXED_IO_ps_clk    (FIXED_IO_ps_clk  ),
  .FIXED_IO_ps_porb   (FIXED_IO_ps_porb ),
  .FIXED_IO_ps_srstb  (FIXED_IO_ps_srstb),
  .FIXED_IO_ddr_vrn   (FIXED_IO_ddr_vrn ),
  .FIXED_IO_ddr_vrp   (FIXED_IO_ddr_vrp ),
  .DDR_addr      (DDR_addr   ),
  .DDR_ba        (DDR_ba     ),
  .DDR_cas_n     (DDR_cas_n  ),
  .DDR_ck_n      (DDR_ck_n   ),
  .DDR_ck_p      (DDR_ck_p   ),
  .DDR_cke       (DDR_cke    ),
  .DDR_cs_n      (DDR_cs_n   ),
  .DDR_dm        (DDR_dm     ),
  .DDR_dq        (DDR_dq     ),
  .DDR_dqs_n     (DDR_dqs_n  ),
  .DDR_dqs_p     (DDR_dqs_p  ),
  .DDR_odt       (DDR_odt    ),
  .DDR_ras_n     (DDR_ras_n  ),
  .DDR_reset_n   (DDR_reset_n),
  .DDR_we_n      (DDR_we_n   ),
  .fclk_clk_o    (fclk       ),
  .fclk_rstn_o   (frstn      ),
  .gpio          (gpio_dummy),
  .irq           (gpio_irq),
  .bus           (bus)
);

////////////////////////////////////////////////////////////////////////////////
// ADS1278 acquisition — replaces axi4lite_gpio
////////////////////////////////////////////////////////////////////////////////

logic       ads_sclk;
logic       ads_miso;
logic       ads_drdy_n;
logic       ads_sync_n;
logic       ads_extclk;
logic [7:0] ads_led;

ads1278_axi_slave #(
  .DW (32)
) u_ads1278 (
  .sclk_o   (ads_sclk  ),
  .miso_i   (ads_miso  ),
  .drdy_n_i (ads_drdy_n),
  .sync_n_o (ads_sync_n),
  .extclk_o (ads_extclk),
  .led_o    (ads_led   ),
  .irq      (gpio_irq  ),
  .bus      (bus        )
);

////////////////////////////////////////////////////////////////////////////////
// Expansion connector pin assignment
//   exp_p_io[0] = SCLK      (output → ADS1278 SCLK)
//   exp_p_io[1] = MISO      (input  ← ADS1278 DOUT1)
//   exp_p_io[2] = DRDY      (input  ← ADS1278 /DRDY)
//   exp_p_io[3] = SYNC      (output → ADS1278 /SYNC)
//   exp_p_io[4] = EXTCLK    (output → ADS1278 CLK)
//   exp_p_io[5:7], exp_n_io[0:7] = unused (high-Z)
////////////////////////////////////////////////////////////////////////////////

assign exp_p_out[0] = ads_sclk;
assign exp_p_out[1] = 1'b0;
assign exp_p_out[2] = 1'b0;
assign exp_p_out[3] = ads_sync_n;
assign exp_p_out[4] = ads_extclk;
assign exp_p_out[5] = 1'b0;
assign exp_p_out[6] = 1'b0;
assign exp_p_out[7] = 1'b0;

assign exp_p_t[0] = 1'b0;
assign exp_p_t[1] = 1'b1;
assign exp_p_t[2] = 1'b1;
assign exp_p_t[3] = 1'b0;
assign exp_p_t[4] = 1'b0;
assign exp_p_t[5] = 1'b1;
assign exp_p_t[6] = 1'b1;
assign exp_p_t[7] = 1'b1;

assign exp_n_out = 8'h00;
assign exp_n_t   = 8'hff;

assign ads_miso   = exp_p_in[1];
assign ads_drdy_n = exp_p_in[2];

////////////////////////////////////////////////////////////////////////////////
// LED output (directly driven by ADS1278 status)
////////////////////////////////////////////////////////////////////////////////

assign led_o = ads_led;

endmodule: red_pitaya_top
