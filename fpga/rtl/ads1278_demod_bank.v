`timescale 1 ns / 1 ps

////////////////////////////////////////////////////////////////////////////////
// Eight-channel ADS1278 half-cycle demodulator with one shared divider.
// Accumulators run in parallel per channel; averages are divided sequentially
// after each MOD edge and held until the next completed demod cycle.
////////////////////////////////////////////////////////////////////////////////

module ads1278_demod_bank (
    input  wire        clk,
    input  wire        rstn,
    input  wire        enable,
    input  wire        new_data,
    input  wire        mod_i,
    input  wire [23:0] sample_0,
    input  wire [23:0] sample_1,
    input  wire [23:0] sample_2,
    input  wire [23:0] sample_3,
    input  wire [23:0] sample_4,
    input  wire [23:0] sample_5,
    input  wire [23:0] sample_6,
    input  wire [23:0] sample_7,
    input  wire [15:0] demod_skip,
    output wire [31:0] demod_out_0,
    output wire [31:0] demod_out_1,
    output wire [31:0] demod_out_2,
    output wire [31:0] demod_out_3,
    output wire [31:0] demod_out_4,
    output wire [31:0] demod_out_5,
    output wire [31:0] demod_out_6,
    output wire [31:0] demod_out_7
);

localparam integer CHANNELS = 8;

reg signed [47:0] sum_pos [0:CHANNELS-1];
reg signed [47:0] sum_neg [0:CHANNELS-1];
reg [15:0]        count_pos [0:CHANNELS-1];
reg [15:0]        count_neg [0:CHANNELS-1];
reg [15:0]        post_edge_count [0:CHANNELS-1];
reg signed [31:0] avg_pos [0:CHANNELS-1];
reg signed [31:0] avg_neg [0:CHANNELS-1];
reg signed [31:0] demod_out [0:CHANNELS-1];

reg signed [31:0] sample_s [0:CHANNELS-1];
reg signed [47:0] batch_dividend [0:CHANNELS-1];
reg [15:0]        batch_divisor [0:CHANNELS-1];

reg               mod_prev;
reg               batch_active;
reg               batch_op_neg;
reg [2:0]         batch_index;
reg               divider_start;
reg signed [47:0] divider_dividend;
reg [15:0]        divider_divisor;

wire              divider_busy;
wire              divider_done;
wire signed [31:0] divider_quotient;
wire              mod_edge = mod_i ^ mod_prev;
wire              divider_rstn = rstn && enable;

integer i;

assign demod_out_0 = demod_out[0];
assign demod_out_1 = demod_out[1];
assign demod_out_2 = demod_out[2];
assign demod_out_3 = demod_out[3];
assign demod_out_4 = demod_out[4];
assign demod_out_5 = demod_out[5];
assign demod_out_6 = demod_out[6];
assign demod_out_7 = demod_out[7];

always @* begin
    sample_s[0] = {{8{sample_0[23]}}, sample_0};
    sample_s[1] = {{8{sample_1[23]}}, sample_1};
    sample_s[2] = {{8{sample_2[23]}}, sample_2};
    sample_s[3] = {{8{sample_3[23]}}, sample_3};
    sample_s[4] = {{8{sample_4[23]}}, sample_4};
    sample_s[5] = {{8{sample_5[23]}}, sample_5};
    sample_s[6] = {{8{sample_6[23]}}, sample_6};
    sample_s[7] = {{8{sample_7[23]}}, sample_7};
end

ads1278_demod_divider u_divider (
    .clk      (clk),
    .rstn     (divider_rstn),
    .start    (divider_start),
    .dividend (divider_dividend),
    .divisor  (divider_divisor),
    .busy     (divider_busy),
    .done     (divider_done),
    .quotient (divider_quotient)
);

always @(posedge clk or negedge rstn) begin
    if (!rstn) begin
        for (i = 0; i < CHANNELS; i = i + 1) begin
            sum_pos[i]         <= 48'sd0;
            sum_neg[i]         <= 48'sd0;
            count_pos[i]       <= 16'd0;
            count_neg[i]       <= 16'd0;
            post_edge_count[i] <= 16'd0;
            avg_pos[i]         <= 32'sd0;
            avg_neg[i]         <= 32'sd0;
            demod_out[i]       <= 32'sd0;
            batch_dividend[i]  <= 48'sd0;
            batch_divisor[i]   <= 16'd0;
        end
        mod_prev         <= 1'b0;
        batch_active     <= 1'b0;
        batch_op_neg     <= 1'b0;
        batch_index      <= 3'd0;
        divider_start    <= 1'b0;
        divider_dividend <= 48'sd0;
        divider_divisor  <= 16'd0;
    end else if (!enable) begin
        for (i = 0; i < CHANNELS; i = i + 1) begin
            sum_pos[i]         <= 48'sd0;
            sum_neg[i]         <= 48'sd0;
            count_pos[i]       <= 16'd0;
            count_neg[i]       <= 16'd0;
            post_edge_count[i] <= 16'd0;
            avg_pos[i]         <= 32'sd0;
            avg_neg[i]         <= 32'sd0;
            demod_out[i]       <= 32'sd0;
            batch_dividend[i]  <= 48'sd0;
            batch_divisor[i]   <= 16'd0;
        end
        mod_prev         <= mod_i;
        batch_active     <= 1'b0;
        batch_op_neg     <= 1'b0;
        batch_index      <= 3'd0;
        divider_start    <= 1'b0;
        divider_dividend <= 48'sd0;
        divider_divisor  <= 16'd0;
    end else begin
        divider_start <= 1'b0;

        if (divider_done) begin
            if (batch_op_neg) begin
                avg_neg[batch_index]   <= divider_quotient;
                demod_out[batch_index] <= (avg_pos[batch_index] - divider_quotient) >>> 1;
            end else begin
                avg_pos[batch_index] <= divider_quotient;
            end

            if (batch_index == 3'd7) begin
                batch_active <= 1'b0;
            end else begin
                batch_index <= batch_index + 3'd1;
            end
        end else if (batch_active && !divider_busy) begin
            if (batch_divisor[batch_index] == 16'd0) begin
                if (batch_op_neg) begin
                    demod_out[batch_index] <=
                        (avg_pos[batch_index] - avg_neg[batch_index]) >>> 1;
                end

                if (batch_index == 3'd7) begin
                    batch_active <= 1'b0;
                end else begin
                    batch_index <= batch_index + 3'd1;
                end
            end else begin
                divider_dividend <= batch_dividend[batch_index];
                divider_divisor  <= batch_divisor[batch_index];
                divider_start    <= 1'b1;
            end
        end

        if (new_data) begin
            if (mod_edge && !batch_active) begin
                batch_active <= 1'b1;
                batch_op_neg <= !mod_prev;
                batch_index  <= 3'd0;

                for (i = 0; i < CHANNELS; i = i + 1) begin
                    if (mod_prev) begin
                        batch_dividend[i] <= sum_pos[i];
                        batch_divisor[i]  <= count_pos[i];
                        sum_pos[i]        <= 48'sd0;
                        count_pos[i]      <= 16'd0;
                    end else begin
                        batch_dividend[i] <= sum_neg[i];
                        batch_divisor[i]  <= count_neg[i];
                        sum_neg[i]        <= 48'sd0;
                        count_neg[i]      <= 16'd0;
                    end
                end
            end

            for (i = 0; i < CHANNELS; i = i + 1) begin
                if ((mod_edge ? 16'd0 : post_edge_count[i]) < demod_skip) begin
                    post_edge_count[i] <= (mod_edge ? 16'd0 : post_edge_count[i]) + 16'd1;
                end else begin
                    post_edge_count[i] <= mod_edge ? 16'd0 : post_edge_count[i];

                    if (mod_i) begin
                        sum_pos[i]   <= sum_pos[i] + {{16{sample_s[i][31]}}, sample_s[i]};
                        count_pos[i] <= count_pos[i] + 16'd1;
                    end else begin
                        sum_neg[i]   <= sum_neg[i] + {{16{sample_s[i][31]}}, sample_s[i]};
                        count_neg[i] <= count_neg[i] + 16'd1;
                    end
                end
            end

            mod_prev <= mod_i;
        end
    end
end

endmodule
