module red_pitaya_pll (
  input  logic clk       ,
  input  logic rstn      ,
  output logic clk_adc   ,
  output logic clk_dac_1x,
  output logic clk_dac_2x,
  output logic clk_dac_2p,
  output logic clk_ser   ,
  output logic clk_pdm   ,
  output logic pll_locked
);

logic clk_fb;

PLLE2_ADV #(
   .BANDWIDTH            ("OPTIMIZED"),
   .COMPENSATION         ("ZHOLD"    ),
   .DIVCLK_DIVIDE        ( 1         ),
   .CLKFBOUT_MULT        ( 8         ),
   .CLKFBOUT_PHASE       ( 0.000     ),
   .CLKOUT0_DIVIDE       ( 8         ),
   .CLKOUT0_PHASE        ( 0.000     ),
   .CLKOUT0_DUTY_CYCLE   ( 0.5       ),
   .CLKOUT1_DIVIDE       ( 8         ),
   .CLKOUT1_PHASE        ( 0.000     ),
   .CLKOUT1_DUTY_CYCLE   ( 0.5       ),
   .CLKOUT2_DIVIDE       ( 4         ),
   .CLKOUT2_PHASE        ( 0.000     ),
   .CLKOUT2_DUTY_CYCLE   ( 0.5       ),
   .CLKOUT3_DIVIDE       ( 4         ),
   .CLKOUT3_PHASE        (-45.000    ),
   .CLKOUT3_DUTY_CYCLE   ( 0.5       ),
   .CLKOUT4_DIVIDE       ( 4         ),
   .CLKOUT4_PHASE        ( 0.000     ),
   .CLKOUT4_DUTY_CYCLE   ( 0.5       ),
   .CLKOUT5_DIVIDE       ( 4         ),
   .CLKOUT5_PHASE        ( 0.000     ),
   .CLKOUT5_DUTY_CYCLE   ( 0.5       ),
   .CLKIN1_PERIOD        ( 8.000     ),
   .REF_JITTER1          ( 0.010     )
) pll (
   .CLKFBOUT     (clk_fb    ),
   .CLKOUT0      (clk_adc   ),
   .CLKOUT1      (clk_dac_1x),
   .CLKOUT2      (clk_dac_2x),
   .CLKOUT3      (clk_dac_2p),
   .CLKOUT4      (clk_ser   ),
   .CLKOUT5      (clk_pdm   ),
   .CLKFBIN      (clk_fb    ),
   .CLKIN1       (clk       ),
   .CLKIN2       (1'b0      ),
   .CLKINSEL     (1'b1      ),
   .DADDR        (7'h0      ),
   .DCLK         (1'b0      ),
   .DEN          (1'b0      ),
   .DI           (16'h0     ),
   .DO           (          ),
   .DRDY         (          ),
   .DWE          (1'b0      ),
   .LOCKED       (pll_locked),
   .PWRDWN       (1'b0      ),
   .RST          (!rstn     )
);

endmodule: red_pitaya_pll
