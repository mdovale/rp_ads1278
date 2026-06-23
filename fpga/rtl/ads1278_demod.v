`timescale 1 ns / 1 ps

////////////////////////////////////////////////////////////////////////////////
// Half-cycle square-wave demodulator.
// Averages samples during each MOD half-cycle and outputs
// (avg_pos - avg_neg) / 2 once per full cycle.
////////////////////////////////////////////////////////////////////////////////

module ads1278_demod (
    input  wire        clk,
    input  wire        rstn,
    input  wire        enable,
    input  wire        new_data,
    input  wire        mod_i,
    input  wire [23:0] sample,
    output reg  [31:0] demod_out
);

reg signed [47:0] sum_pos;
reg signed [47:0] sum_neg;
reg [15:0]        count_pos;
reg [15:0]        count_neg;
reg signed [31:0] avg_pos;
reg signed [31:0] avg_neg;
reg               mod_prev;

wire signed [31:0] sample_s = {{8{sample[23]}}, sample};
wire               mod_edge = mod_i ^ mod_prev;
wire signed [31:0] pos_avg_next =
    (count_pos != 16'd0) ? (sum_pos / $signed({16'd0, count_pos})) : avg_pos;
wire signed [31:0] neg_avg_next =
    (count_neg != 16'd0) ? (sum_neg / $signed({16'd0, count_neg})) : avg_neg;

always @(posedge clk or negedge rstn) begin
    if (!rstn) begin
        sum_pos   <= 48'sd0;
        sum_neg   <= 48'sd0;
        count_pos <= 16'd0;
        count_neg <= 16'd0;
        avg_pos   <= 32'sd0;
        avg_neg   <= 32'sd0;
        mod_prev  <= 1'b0;
        demod_out <= 32'd0;
    end else if (!enable) begin
        sum_pos   <= 48'sd0;
        sum_neg   <= 48'sd0;
        count_pos <= 16'd0;
        count_neg <= 16'd0;
        avg_pos   <= 32'sd0;
        avg_neg   <= 32'sd0;
        mod_prev  <= mod_i;
        demod_out <= 32'd0;
    end else if (new_data) begin
        if (mod_edge) begin
            if (mod_prev) begin
                avg_pos   <= pos_avg_next;
                sum_pos   <= 48'sd0;
                count_pos <= 16'd0;
            end else begin
                avg_neg   <= neg_avg_next;
                demod_out <= (avg_pos - neg_avg_next) >>> 1;
                sum_neg   <= 48'sd0;
                count_neg <= 16'd0;
            end
        end

        if (mod_i) begin
            sum_pos   <= (mod_edge && mod_prev) ? {{16{sample_s[31]}}, sample_s}
                         : sum_pos + {{16{sample_s[31]}}, sample_s};
            count_pos <= (mod_edge && mod_prev) ? 16'd1 : count_pos + 16'd1;
        end else begin
            sum_neg   <= (mod_edge && !mod_prev) ? {{16{sample_s[31]}}, sample_s}
                         : sum_neg + {{16{sample_s[31]}}, sample_s};
            count_neg <= (mod_edge && !mod_prev) ? 16'd1 : count_neg + 16'd1;
        end

        mod_prev <= mod_i;
    end
end

endmodule
