`timescale 1 ns / 1 ps

////////////////////////////////////////////////////////////////////////////////
// AXI4-Lite slave for ADS1278 acquisition.
// Register map (byte offsets from the assigned AXI base):
//   0x00  CH1       R    24-bit channel 1 data  (bits [23:0])
//   0x04  CH2       R    24-bit channel 2 data
//   0x08  CH3       R    24-bit channel 3 data
//   0x0C  CH4       R    24-bit channel 4 data
//   0x10  CH5       R    24-bit channel 5 data
//   0x14  CH6       R    24-bit channel 6 data
//   0x18  CH7       R    24-bit channel 7 data
//   0x1C  CH8       R    24-bit channel 8 data
//   0x20  STATUS    R    [0] drdy_seen  [1] overflow  [31:16] frame_cnt
//   0x24  CTRL      R/W  [0] sync_trigger (W1C)  [1] enable
//   0x28  EXTCLK_DIV R/W half-period in sys-clk cycles (125 MHz / (2*val))
//   0x2C  FIFO_STATUS R  [15:0] level  [16] empty  [17] full
//   0x30  FIFO_DROPS  R  Count of frames not queued because the FIFO was full
//   0x34  FIFO_CAPACITY R Configured frame depth of the staged DMA FIFO
////////////////////////////////////////////////////////////////////////////////

module ads1278_axi_slave #(
  int unsigned DW = 32,
  int unsigned AW = 6
)(
  output logic        sclk_o,
  input  logic        miso_i,
  input  logic        drdy_n_i,
  output logic        sync_n_o,
  output logic        extclk_o,
  output logic [7:0]  led_o,
  output logic        irq,
  axi4_lite_if.s      bus
);

localparam int unsigned ADDR_LSB = $clog2(DW/8);
localparam int unsigned REG_AW   = AW - ADDR_LSB;    // 4-bit word address

// AXI latched addresses
logic [AW-1:ADDR_LSB] axi_awaddr;
logic [AW-1:ADDR_LSB] axi_araddr;

logic slv_reg_rden;
logic slv_reg_wren;

logic AWtransfer, Wtransfer, Btransfer, ARtransfer, Rtransfer;
assign AWtransfer = bus.AWVALID & bus.AWREADY;
assign  Wtransfer =  bus.WVALID &  bus.WREADY;
assign  Btransfer =  bus.BVALID &  bus.BREADY;
assign ARtransfer = bus.ARVALID & bus.ARREADY;
assign  Rtransfer =  bus.RVALID &  bus.RREADY;

// ---- Registers ----
logic [DW-1:0] ctrl_reg;
logic [DW-1:0] extclk_div_reg;

// Derived control signals
logic ctrl_enable;
logic sync_trigger;
assign ctrl_enable  = ctrl_reg[1];
assign sync_trigger = ctrl_reg[0];

// Acquisition data from acq_top
logic [DW-1:0] ch_data [8];
logic [DW-1:0] status_reg;
logic [DW-1:0] fifo_status_reg;
logic [DW-1:0] fifo_drop_count_reg;
logic [DW-1:0] fifo_capacity_reg;

// ---- Acquisition core ----
ads1278_acq_top u_acq (
  .clk          (bus.ACLK),
  .rstn         (bus.ARESETn),
  .sclk_o       (sclk_o),
  .miso_i       (miso_i),
  .drdy_n_i     (drdy_n_i),
  .sync_n_o     (sync_n_o),
  .extclk_o     (extclk_o),
  .ch_data_0    (ch_data[0]),
  .ch_data_1    (ch_data[1]),
  .ch_data_2    (ch_data[2]),
  .ch_data_3    (ch_data[3]),
  .ch_data_4    (ch_data[4]),
  .ch_data_5    (ch_data[5]),
  .ch_data_6    (ch_data[6]),
  .ch_data_7    (ch_data[7]),
  .status       (status_reg),
  .fifo_status  (fifo_status_reg),
  .fifo_drop_count (fifo_drop_count_reg),
  .fifo_capacity (fifo_capacity_reg),
  .ctrl_enable  (ctrl_enable),
  .sync_trigger (sync_trigger),
  .extclk_div   (extclk_div_reg)
);

// LED: frame counter toggle on bit 0, enable on bit 1, EXTCLK on bit 2
assign led_o = {status_reg[20:16], extclk_o, ctrl_enable, status_reg[0]};

// ======================================================================
// AXI4-Lite write logic
// ======================================================================

// AWREADY
always_ff @(posedge bus.ACLK)
if (~bus.ARESETn) bus.AWREADY <= 1'b0;
else              bus.AWREADY <= ~bus.AWREADY & bus.AWVALID & bus.WVALID;

// Latch write address
always_ff @(posedge bus.ACLK)
if (~bus.AWREADY & bus.AWVALID & bus.WVALID)
  axi_awaddr <= bus.AWADDR[AW-1:ADDR_LSB];

// WREADY
always_ff @(posedge bus.ACLK)
if (~bus.ARESETn) bus.WREADY <= 1'b0;
else              bus.WREADY <= ~bus.WREADY & bus.WVALID & bus.AWVALID;

// Write-enable
assign slv_reg_wren = Wtransfer & AWtransfer;

// Register writes
always_ff @(posedge bus.ACLK)
if (~bus.ARESETn) begin
  ctrl_reg       <= 32'h0000_0000;
  extclk_div_reg <= 32'h0000_0271;   // default 625 → 100 kHz EXTCLK
end else begin
  // Auto-clear SYNC trigger after one cycle
  ctrl_reg[0] <= 1'b0;

  if (slv_reg_wren) begin
    case (axi_awaddr)
      4'h9: begin // CTRL @ 0x24
        for (int unsigned i = 0; i < (DW/8); i++)
          if (bus.WSTRB[i]) ctrl_reg[(i*8)+:8] <= bus.WDATA[(i*8)+:8];
      end
      4'hA: begin // EXTCLK_DIV @ 0x28
        for (int unsigned i = 0; i < (DW/8); i++)
          if (bus.WSTRB[i]) extclk_div_reg[(i*8)+:8] <= bus.WDATA[(i*8)+:8];
      end
      default: ;
    endcase
  end
end

// Write response
always_ff @(posedge bus.ACLK)
if (AWtransfer & ~bus.BVALID & Wtransfer)
  bus.BRESP <= 2'b0;

always_ff @(posedge bus.ACLK)
if (~bus.ARESETn)                          bus.BVALID <= 1'b0;
else if (AWtransfer & ~bus.BVALID & Wtransfer) bus.BVALID <= 1'b1;
else if (bus.BREADY & bus.BVALID)          bus.BVALID <= 1'b0;

// ======================================================================
// AXI4-Lite read logic
// ======================================================================

// ARREADY
always_ff @(posedge bus.ACLK)
if (~bus.ARESETn) bus.ARREADY <= 1'b0;
else              bus.ARREADY <= ~bus.ARREADY & bus.ARVALID;

// Latch read address
always_ff @(posedge bus.ACLK)
if (~bus.ARREADY & bus.ARVALID)
  axi_araddr <= bus.ARADDR[AW-1:ADDR_LSB];

// Read-enable
assign slv_reg_rden = ARtransfer & ~bus.RVALID;

always_ff @(posedge bus.ACLK)
if (slv_reg_rden)
  bus.RRESP <= 2'b0;

always_ff @(posedge bus.ACLK)
if (~bus.ARESETn)       bus.RVALID <= 1'b0;
else if (slv_reg_rden)  bus.RVALID <= 1'b1;
else if (Rtransfer)     bus.RVALID <= 1'b0;

// Read data mux
always_ff @(posedge bus.ACLK)
if (slv_reg_rden) begin
  case (axi_araddr)
    4'h0: bus.RDATA <= ch_data[0];
    4'h1: bus.RDATA <= ch_data[1];
    4'h2: bus.RDATA <= ch_data[2];
    4'h3: bus.RDATA <= ch_data[3];
    4'h4: bus.RDATA <= ch_data[4];
    4'h5: bus.RDATA <= ch_data[5];
    4'h6: bus.RDATA <= ch_data[6];
    4'h7: bus.RDATA <= ch_data[7];
    4'h8: bus.RDATA <= status_reg;
    4'h9: bus.RDATA <= ctrl_reg;
    4'hA: bus.RDATA <= extclk_div_reg;
    4'hB: bus.RDATA <= fifo_status_reg;
    4'hC: bus.RDATA <= fifo_drop_count_reg;
    4'hD: bus.RDATA <= fifo_capacity_reg;
    default: bus.RDATA <= 32'hDEAD_BEEF;
  endcase
end

// IRQ on new data ready (directly from status bit 0)
assign irq = status_reg[0];

endmodule: ads1278_axi_slave
