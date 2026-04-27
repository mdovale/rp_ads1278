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
//   0x38  DMA_CTRL   R/W  [0] enable [2:1] mode [8] irq_enable
//   0x3C  DMA_BASE_ADDR R/W Physical DDR base for the DMA test buffer
//   0x40  DMA_BUF_SIZE R/W Buffer size in bytes, aligned to 128-byte bursts
//   0x44  DMA_STATUS R   [0] enabled [1] running [2] config_error
//                        [3] wrap_pending [4] error_pending
//                        [9:8] last_bresp [31:16] write_index
//   0x48  DMA_WRITE_INDEX R Current writer burst index
//   0x4C  DMA_WRAP_COUNT R Number of completed buffer wraps
//   0x50  DMA_ERROR_COUNT R Number of non-OKAY AXI write responses
//   0x54  DMA_IRQ_STATUS R Sticky DMA interrupt/status bits
//   0x58  DMA_IRQ_ACK W1C Clear DMA_IRQ_STATUS bits
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
  output logic        dma_phase4_enable,
  output logic [1:0]  dma_phase4_mode,
  output logic [DW-1:0] dma_phase4_base_addr,
  output logic [DW-1:0] dma_phase4_buf_size,
  input  logic [15:0] dma_phase4_write_index,
  input  logic        dma_phase4_wrap_pulse,
  input  logic        dma_phase4_running,
  input  logic        dma_phase4_config_error,
  input  logic        dma_phase4_bresp_error_pulse,
  input  logic [1:0]  dma_phase4_last_bresp,
  axi4_lite_if.s      bus
);

localparam int unsigned ADDR_LSB = $clog2(DW/8);
localparam int unsigned REG_AW   = AW - ADDR_LSB;

localparam int unsigned REG_CH1          = 'h0;
localparam int unsigned REG_CH2          = 'h1;
localparam int unsigned REG_CH3          = 'h2;
localparam int unsigned REG_CH4          = 'h3;
localparam int unsigned REG_CH5          = 'h4;
localparam int unsigned REG_CH6          = 'h5;
localparam int unsigned REG_CH7          = 'h6;
localparam int unsigned REG_CH8          = 'h7;
localparam int unsigned REG_STATUS       = 'h8;
localparam int unsigned REG_CTRL         = 'h9;
localparam int unsigned REG_EXTCLK_DIV   = 'hA;
localparam int unsigned REG_FIFO_STATUS  = 'hB;
localparam int unsigned REG_FIFO_DROPS   = 'hC;
localparam int unsigned REG_FIFO_CAP     = 'hD;
localparam int unsigned REG_DMA_CTRL     = 'hE;
localparam int unsigned REG_DMA_BASE     = 'hF;
localparam int unsigned REG_DMA_SIZE     = 'h10;
localparam int unsigned REG_DMA_STATUS   = 'h11;
localparam int unsigned REG_DMA_INDEX    = 'h12;
localparam int unsigned REG_DMA_WRAPS    = 'h13;
localparam int unsigned REG_DMA_ERRORS   = 'h14;
localparam int unsigned REG_DMA_IRQ_STAT = 'h15;
localparam int unsigned REG_DMA_IRQ_ACK  = 'h16;

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
logic [DW-1:0] dma_ctrl_reg;
logic [DW-1:0] dma_base_addr_reg;
logic [DW-1:0] dma_buf_size_reg;
logic [DW-1:0] dma_wrap_count_reg;
logic [DW-1:0] dma_error_count_reg;
logic [DW-1:0] dma_irq_status_reg;
logic [DW-1:0] dma_status_reg;
logic [DW-1:0] dma_write_index_reg;
logic [DW-1:0] dma_irq_ack_mask;

// Derived control signals
logic ctrl_enable;
logic sync_trigger;
logic dma_irq_enable;
logic dma_irq_pending;

assign ctrl_enable  = ctrl_reg[1];
assign sync_trigger = ctrl_reg[0];
assign dma_phase4_enable = dma_ctrl_reg[0];
assign dma_phase4_mode = dma_ctrl_reg[2:1];
assign dma_phase4_base_addr = dma_base_addr_reg;
assign dma_phase4_buf_size = dma_buf_size_reg;
assign dma_irq_enable = dma_ctrl_reg[8];
assign dma_irq_pending = |dma_irq_status_reg[2:0];

always_comb begin
  dma_status_reg = '0;
  dma_status_reg[0] = dma_phase4_enable;
  dma_status_reg[1] = dma_phase4_running;
  dma_status_reg[2] = dma_phase4_config_error;
  dma_status_reg[3] = dma_irq_status_reg[0];
  dma_status_reg[4] = dma_irq_status_reg[1];
  dma_status_reg[9:8] = dma_phase4_last_bresp;
  dma_status_reg[31:16] = dma_phase4_write_index;

  dma_write_index_reg = '0;
  dma_write_index_reg[15:0] = dma_phase4_write_index;

  dma_irq_ack_mask = '0;
  if (slv_reg_wren && (axi_awaddr == REG_DMA_IRQ_ACK)) begin
    for (int unsigned i = 0; i < (DW/8); i++) begin
      if (bus.WSTRB[i]) dma_irq_ack_mask[(i*8)+:8] = bus.WDATA[(i*8)+:8];
    end
  end
end

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
  dma_ctrl_reg      <= 32'h0000_0000;
  dma_base_addr_reg <= 32'h1E00_0000;
  dma_buf_size_reg  <= 32'h0001_0000;
end else begin
  // Auto-clear SYNC trigger after one cycle
  ctrl_reg[0] <= 1'b0;

  if (slv_reg_wren) begin
    case (axi_awaddr)
      REG_CTRL: begin // CTRL @ 0x24
        for (int unsigned i = 0; i < (DW/8); i++)
          if (bus.WSTRB[i]) ctrl_reg[(i*8)+:8] <= bus.WDATA[(i*8)+:8];
      end
      REG_EXTCLK_DIV: begin // EXTCLK_DIV @ 0x28
        for (int unsigned i = 0; i < (DW/8); i++)
          if (bus.WSTRB[i]) extclk_div_reg[(i*8)+:8] <= bus.WDATA[(i*8)+:8];
      end
      REG_DMA_CTRL: begin
        for (int unsigned i = 0; i < (DW/8); i++)
          if (bus.WSTRB[i]) dma_ctrl_reg[(i*8)+:8] <= bus.WDATA[(i*8)+:8];
      end
      REG_DMA_BASE: begin
        for (int unsigned i = 0; i < (DW/8); i++)
          if (bus.WSTRB[i]) dma_base_addr_reg[(i*8)+:8] <= bus.WDATA[(i*8)+:8];
      end
      REG_DMA_SIZE: begin
        for (int unsigned i = 0; i < (DW/8); i++)
          if (bus.WSTRB[i]) dma_buf_size_reg[(i*8)+:8] <= bus.WDATA[(i*8)+:8];
      end
      default: ;
    endcase
  end
end

always_ff @(posedge bus.ACLK)
if (~bus.ARESETn) begin
  dma_wrap_count_reg <= '0;
  dma_error_count_reg <= '0;
  dma_irq_status_reg <= '0;
end else begin
  dma_irq_status_reg <= dma_irq_status_reg & ~dma_irq_ack_mask;

  if (dma_phase4_wrap_pulse) begin
    dma_wrap_count_reg <= dma_wrap_count_reg + 1'b1;
    dma_irq_status_reg[0] <= 1'b1;
  end

  if (dma_phase4_bresp_error_pulse) begin
    dma_error_count_reg <= dma_error_count_reg + 1'b1;
    dma_irq_status_reg[1] <= 1'b1;
  end

  if (dma_phase4_config_error) begin
    dma_irq_status_reg[2] <= 1'b1;
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
    REG_CH1: bus.RDATA <= ch_data[0];
    REG_CH2: bus.RDATA <= ch_data[1];
    REG_CH3: bus.RDATA <= ch_data[2];
    REG_CH4: bus.RDATA <= ch_data[3];
    REG_CH5: bus.RDATA <= ch_data[4];
    REG_CH6: bus.RDATA <= ch_data[5];
    REG_CH7: bus.RDATA <= ch_data[6];
    REG_CH8: bus.RDATA <= ch_data[7];
    REG_STATUS: bus.RDATA <= status_reg;
    REG_CTRL: bus.RDATA <= ctrl_reg;
    REG_EXTCLK_DIV: bus.RDATA <= extclk_div_reg;
    REG_FIFO_STATUS: bus.RDATA <= fifo_status_reg;
    REG_FIFO_DROPS: bus.RDATA <= fifo_drop_count_reg;
    REG_FIFO_CAP: bus.RDATA <= fifo_capacity_reg;
    REG_DMA_CTRL: bus.RDATA <= dma_ctrl_reg;
    REG_DMA_BASE: bus.RDATA <= dma_base_addr_reg;
    REG_DMA_SIZE: bus.RDATA <= dma_buf_size_reg;
    REG_DMA_STATUS: bus.RDATA <= dma_status_reg;
    REG_DMA_INDEX: bus.RDATA <= dma_write_index_reg;
    REG_DMA_WRAPS: bus.RDATA <= dma_wrap_count_reg;
    REG_DMA_ERRORS: bus.RDATA <= dma_error_count_reg;
    REG_DMA_IRQ_STAT: bus.RDATA <= dma_irq_status_reg;
    REG_DMA_IRQ_ACK: bus.RDATA <= 32'h0000_0000;
    default: bus.RDATA <= 32'hDEAD_BEEF;
  endcase
end

// IRQ on new data ready, optionally ORed with DMA sticky status.
assign irq = status_reg[0] | (dma_irq_enable & dma_irq_pending);

endmodule: ads1278_axi_slave
