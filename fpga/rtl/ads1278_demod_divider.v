`timescale 1 ns / 1 ps

////////////////////////////////////////////////////////////////////////////////
// Iterative signed divider for ADS1278 demodulation averages.
// Computes a signed 48-bit dividend divided by a positive 16-bit divisor.
////////////////////////////////////////////////////////////////////////////////

module ads1278_demod_divider (
    input  wire              clk,
    input  wire              rstn,
    input  wire              start,
    input  wire signed [47:0] dividend,
    input  wire [15:0]       divisor,
    output reg               busy,
    output reg               done,
    output reg signed [31:0] quotient
);

reg [47:0] dividend_shift;
reg [15:0] divisor_abs;
reg [48:0] remainder;
reg [47:0] quotient_work;
reg [5:0]  bit_count;
reg        quotient_neg;

wire [47:0] dividend_mag = dividend[47] ? (~dividend + 48'd1) : dividend;
wire [48:0] divisor_ext = {33'd0, divisor_abs};
wire [48:0] remainder_shift = {remainder[47:0], dividend_shift[47]};
wire        subtract_divisor = remainder_shift >= divisor_ext;
wire [48:0] remainder_next =
    subtract_divisor ? (remainder_shift - divisor_ext) : remainder_shift;
wire [47:0] quotient_next = {quotient_work[46:0], subtract_divisor};
wire signed [47:0] quotient_signed =
    quotient_neg ? -$signed(quotient_next) : $signed(quotient_next);

always @(posedge clk or negedge rstn) begin
    if (!rstn) begin
        dividend_shift <= 48'd0;
        divisor_abs    <= 16'd0;
        remainder      <= 49'd0;
        quotient_work  <= 48'd0;
        bit_count      <= 6'd0;
        quotient_neg   <= 1'b0;
        busy           <= 1'b0;
        done           <= 1'b0;
        quotient       <= 32'sd0;
    end else begin
        done <= 1'b0;

        if (start && !busy) begin
            if (divisor == 16'd0) begin
                quotient <= 32'sd0;
                busy     <= 1'b0;
                done     <= 1'b1;
            end else begin
                dividend_shift <= dividend_mag;
                divisor_abs    <= divisor;
                remainder      <= 49'd0;
                quotient_work  <= 48'd0;
                bit_count      <= 6'd0;
                quotient_neg   <= dividend[47];
                busy           <= 1'b1;
            end
        end else if (busy) begin
            dividend_shift <= {dividend_shift[46:0], 1'b0};
            remainder      <= remainder_next;
            quotient_work  <= quotient_next;

            if (bit_count == 6'd47) begin
                quotient <= quotient_signed[31:0];
                busy     <= 1'b0;
                done     <= 1'b1;
            end else begin
                bit_count <= bit_count + 6'd1;
            end
        end
    end
end

endmodule
