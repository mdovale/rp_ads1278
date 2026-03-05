`timescale 1 ns / 1 ps

////////////////////////////////////////////////////////////////////////////////
// EXTCLK generator — divides 125 MHz system clock to produce the ADS1278
// conversion clock.  EXTCLK frequency = 125 MHz / (2 × div_val).
//   div_val = 625  → 100 kHz
//   div_val = 63   → ~992 kHz
//   div_val = 6    → ~10.4 MHz
//   div_val = 3    → ~20.8 MHz  (max practical with 50% duty cycle)
////////////////////////////////////////////////////////////////////////////////

module ads1278_extclk_gen (
    input  wire        clk,
    input  wire        rstn,
    input  wire        enable,
    input  wire [31:0] div_val,
    output reg         extclk_o
);

wire [31:0] div_eff = (div_val < 32'd2) ? 32'd2 : div_val;

reg [31:0] cnt;

always @(posedge clk or negedge rstn) begin
    if (!rstn) begin
        cnt      <= 32'd0;
        extclk_o <= 1'b0;
    end else if (!enable) begin
        cnt      <= 32'd0;
        extclk_o <= 1'b0;
    end else begin
        if (cnt >= div_eff - 32'd1) begin
            cnt      <= 32'd0;
            extclk_o <= ~extclk_o;
        end else begin
            cnt <= cnt + 32'd1;
        end
    end
end

endmodule
