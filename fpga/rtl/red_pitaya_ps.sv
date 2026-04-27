module red_pitaya_ps (
  inout  logic [54-1:0] FIXED_IO_mio     ,
  inout  logic          FIXED_IO_ps_clk  ,
  inout  logic          FIXED_IO_ps_porb ,
  inout  logic          FIXED_IO_ps_srstb,
  inout  logic          FIXED_IO_ddr_vrn ,
  inout  logic          FIXED_IO_ddr_vrp ,
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
  output logic  [4-1:0] fclk_clk_o ,
  output logic  [4-1:0] fclk_rstn_o,
  gpio_if.m              gpio,
  input logic            irq,
  input logic            dma_phase4_enable,
  input logic [1:0]      dma_phase4_mode,
  input logic [31:0]     dma_phase4_base_addr,
  input logic [31:0]     dma_phase4_buf_size,
  output logic [15:0]    dma_phase4_write_index,
  output logic           dma_phase4_wrap_pulse,
  output logic           dma_phase4_running,
  output logic           dma_phase4_config_error,
  output logic           dma_phase4_bresp_error_pulse,
  output logic [1:0]     dma_phase4_last_bresp,
  axi4_lite_if.m         bus
);

logic [4-1:0] fclk_clk ;
logic [4-1:0] fclk_rstn;

logic [5:0]  hp0_awid;
logic [31:0] hp0_awaddr;
logic [3:0]  hp0_awlen;
logic [2:0]  hp0_awsize;
logic [1:0]  hp0_awburst;
logic [1:0]  hp0_awlock;
logic [3:0]  hp0_awcache;
logic [2:0]  hp0_awprot;
logic [3:0]  hp0_awqos;
logic        hp0_awvalid;
logic        hp0_awready;

logic [5:0]  hp0_wid;
logic [63:0] hp0_wdata;
logic [7:0]  hp0_wstrb;
logic        hp0_wlast;
logic        hp0_wvalid;
logic        hp0_wready;

logic [5:0]  hp0_bid;
logic [1:0]  hp0_bresp;
logic        hp0_bvalid;
logic        hp0_bready;

logic [5:0]  hp0_arid;
logic [31:0] hp0_araddr;
logic [3:0]  hp0_arlen;
logic [2:0]  hp0_arsize;
logic [1:0]  hp0_arburst;
logic [1:0]  hp0_arlock;
logic [3:0]  hp0_arcache;
logic [2:0]  hp0_arprot;
logic [3:0]  hp0_arqos;
logic        hp0_arvalid;
logic        hp0_arready;

logic [5:0]  hp0_rid;
logic [63:0] hp0_rdata;
logic [1:0]  hp0_rresp;
logic        hp0_rlast;
logic        hp0_rvalid;
logic        hp0_rready;

assign fclk_rstn_o = fclk_rstn;

BUFG fclk_buf [4-1:0] (.O(fclk_clk_o), .I(fclk_clk));

system system (
  .FIXED_IO_mio      (FIXED_IO_mio     ),
  .FIXED_IO_ps_clk   (FIXED_IO_ps_clk  ),
  .FIXED_IO_ps_porb  (FIXED_IO_ps_porb ),
  .FIXED_IO_ps_srstb (FIXED_IO_ps_srstb),
  .FIXED_IO_ddr_vrn  (FIXED_IO_ddr_vrn ),
  .FIXED_IO_ddr_vrp  (FIXED_IO_ddr_vrp ),
  .DDR_addr          (DDR_addr   ),
  .DDR_ba            (DDR_ba     ),
  .DDR_cas_n         (DDR_cas_n  ),
  .DDR_ck_n          (DDR_ck_n   ),
  .DDR_ck_p          (DDR_ck_p   ),
  .DDR_cke           (DDR_cke    ),
  .DDR_cs_n          (DDR_cs_n   ),
  .DDR_dm            (DDR_dm     ),
  .DDR_dq            (DDR_dq     ),
  .DDR_dqs_n         (DDR_dqs_n  ),
  .DDR_dqs_p         (DDR_dqs_p  ),
  .DDR_odt           (DDR_odt    ),
  .DDR_ras_n         (DDR_ras_n  ),
  .DDR_reset_n       (DDR_reset_n),
  .DDR_we_n          (DDR_we_n   ),
  .FCLK_CLK0         (fclk_clk[0]),
  .FCLK_CLK1         (fclk_clk[1]),
  .FCLK_CLK2         (fclk_clk[2]),
  .FCLK_CLK3         (fclk_clk[3]),
  .FCLK_RESET0_N     (fclk_rstn[0]),
  .FCLK_RESET1_N     (fclk_rstn[1]),
  .FCLK_RESET2_N     (fclk_rstn[2]),
  .FCLK_RESET3_N     (fclk_rstn[3]),
  .PL_ACLK            (bus.ACLK   ),
  .PL_ARESETn         (bus.ARESETn),
  .M_AXI_GP0_araddr   (bus.ARADDR ),
  .M_AXI_GP0_arprot   (bus.ARPROT ),
  .M_AXI_GP0_arready  (bus.ARREADY),
  .M_AXI_GP0_arvalid  (bus.ARVALID),
  .M_AXI_GP0_awaddr   (bus.AWADDR ),
  .M_AXI_GP0_awprot   (bus.AWPROT ),
  .M_AXI_GP0_awready  (bus.AWREADY),
  .M_AXI_GP0_awvalid  (bus.AWVALID),
  .M_AXI_GP0_bready   (bus.BREADY ),
  .M_AXI_GP0_bresp    (bus.BRESP  ),
  .M_AXI_GP0_bvalid   (bus.BVALID ),
  .M_AXI_GP0_rdata    (bus.RDATA  ),
  .M_AXI_GP0_rready   (bus.RREADY ),
  .M_AXI_GP0_rresp    (bus.RRESP  ),
  .M_AXI_GP0_rvalid   (bus.RVALID ),
  .M_AXI_GP0_wdata    (bus.WDATA  ),
  .M_AXI_GP0_wready   (bus.WREADY ),
  .M_AXI_GP0_wstrb    (bus.WSTRB  ),
  .M_AXI_GP0_wvalid   (bus.WVALID ),
  .S_AXI_HP0_araddr   (hp0_araddr ),
  .S_AXI_HP0_arburst  (hp0_arburst),
  .S_AXI_HP0_arcache  (hp0_arcache),
  .S_AXI_HP0_arid     (hp0_arid   ),
  .S_AXI_HP0_arlen    (hp0_arlen  ),
  .S_AXI_HP0_arlock   (hp0_arlock ),
  .S_AXI_HP0_arprot   (hp0_arprot ),
  .S_AXI_HP0_arqos    (hp0_arqos  ),
  .S_AXI_HP0_arready  (hp0_arready),
  .S_AXI_HP0_arsize   (hp0_arsize ),
  .S_AXI_HP0_arvalid  (hp0_arvalid),
  .S_AXI_HP0_awaddr   (hp0_awaddr ),
  .S_AXI_HP0_awburst  (hp0_awburst),
  .S_AXI_HP0_awcache  (hp0_awcache),
  .S_AXI_HP0_awid     (hp0_awid   ),
  .S_AXI_HP0_awlen    (hp0_awlen  ),
  .S_AXI_HP0_awlock   (hp0_awlock ),
  .S_AXI_HP0_awprot   (hp0_awprot ),
  .S_AXI_HP0_awqos    (hp0_awqos  ),
  .S_AXI_HP0_awready  (hp0_awready),
  .S_AXI_HP0_awsize   (hp0_awsize ),
  .S_AXI_HP0_awvalid  (hp0_awvalid),
  .S_AXI_HP0_bid      (hp0_bid    ),
  .S_AXI_HP0_bready   (hp0_bready ),
  .S_AXI_HP0_bresp    (hp0_bresp  ),
  .S_AXI_HP0_bvalid   (hp0_bvalid ),
  .S_AXI_HP0_rdata    (hp0_rdata  ),
  .S_AXI_HP0_rid      (hp0_rid    ),
  .S_AXI_HP0_rlast    (hp0_rlast  ),
  .S_AXI_HP0_rready   (hp0_rready ),
  .S_AXI_HP0_rresp    (hp0_rresp  ),
  .S_AXI_HP0_rvalid   (hp0_rvalid ),
  .S_AXI_HP0_wdata    (hp0_wdata  ),
  .S_AXI_HP0_wid      (hp0_wid    ),
  .S_AXI_HP0_wlast    (hp0_wlast  ),
  .S_AXI_HP0_wready   (hp0_wready ),
  .S_AXI_HP0_wstrb    (hp0_wstrb  ),
  .S_AXI_HP0_wvalid   (hp0_wvalid ),
  .GPIO_tri_i (gpio.i),
  .GPIO_tri_o (gpio.o),
  .GPIO_tri_t (gpio.t),
  .IRQ        (irq)
);

ads1278_dma_phase4 u_dma_phase4 (
  .clk          (fclk_clk_o[0]),
  .rstn         (fclk_rstn[0]),
  .enable       (dma_phase4_enable),
  .mode_select  (dma_phase4_mode),
  .base_addr    (dma_phase4_base_addr),
  .buffer_size_bytes(dma_phase4_buf_size),
  .write_index  (dma_phase4_write_index),
  .wrap_pulse   (dma_phase4_wrap_pulse),
  .running      (dma_phase4_running),
  .config_error (dma_phase4_config_error),
  .bresp_error_pulse(dma_phase4_bresp_error_pulse),
  .last_bresp   (dma_phase4_last_bresp),
  .m_axi_awid   (hp0_awid),
  .m_axi_awaddr (hp0_awaddr),
  .m_axi_awlen  (hp0_awlen),
  .m_axi_awsize (hp0_awsize),
  .m_axi_awburst(hp0_awburst),
  .m_axi_awlock (hp0_awlock),
  .m_axi_awcache(hp0_awcache),
  .m_axi_awprot (hp0_awprot),
  .m_axi_awqos  (hp0_awqos),
  .m_axi_awvalid(hp0_awvalid),
  .m_axi_awready(hp0_awready),
  .m_axi_wid    (hp0_wid),
  .m_axi_wdata  (hp0_wdata),
  .m_axi_wstrb  (hp0_wstrb),
  .m_axi_wlast  (hp0_wlast),
  .m_axi_wvalid (hp0_wvalid),
  .m_axi_wready (hp0_wready),
  .m_axi_bid    (hp0_bid),
  .m_axi_bresp  (hp0_bresp),
  .m_axi_bvalid (hp0_bvalid),
  .m_axi_bready (hp0_bready),
  .m_axi_arid   (hp0_arid),
  .m_axi_araddr (hp0_araddr),
  .m_axi_arlen  (hp0_arlen),
  .m_axi_arsize (hp0_arsize),
  .m_axi_arburst(hp0_arburst),
  .m_axi_arlock (hp0_arlock),
  .m_axi_arcache(hp0_arcache),
  .m_axi_arprot (hp0_arprot),
  .m_axi_arqos  (hp0_arqos),
  .m_axi_arvalid(hp0_arvalid),
  .m_axi_arready(hp0_arready),
  .m_axi_rid    (hp0_rid),
  .m_axi_rdata  (hp0_rdata),
  .m_axi_rresp  (hp0_rresp),
  .m_axi_rlast  (hp0_rlast),
  .m_axi_rvalid (hp0_rvalid),
  .m_axi_rready (hp0_rready)
);

endmodule: red_pitaya_ps
