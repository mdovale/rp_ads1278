`timescale 1 ns / 1 ps

module ads1278_demod_multichannel_tb;

reg clk = 1'b0;
reg rstn = 1'b0;
reg enable = 1'b0;
reg new_data = 1'b0;
reg mod_i = 1'b1;
reg [15:0] demod_skip = 16'd0;
reg [23:0] sample [0:7];
wire [31:0] demod_out [0:7];

integer failures = 0;
integer channel;

always #5 clk = ~clk;

ads1278_demod_bank dut (
    .clk         (clk),
    .rstn        (rstn),
    .enable      (enable),
    .new_data    (new_data),
    .mod_i       (mod_i),
    .sample_0    (sample[0]),
    .sample_1    (sample[1]),
    .sample_2    (sample[2]),
    .sample_3    (sample[3]),
    .sample_4    (sample[4]),
    .sample_5    (sample[5]),
    .sample_6    (sample[6]),
    .sample_7    (sample[7]),
    .demod_skip  (demod_skip),
    .demod_out_0 (demod_out[0]),
    .demod_out_1 (demod_out[1]),
    .demod_out_2 (demod_out[2]),
    .demod_out_3 (demod_out[3]),
    .demod_out_4 (demod_out[4]),
    .demod_out_5 (demod_out[5]),
    .demod_out_6 (demod_out[6]),
    .demod_out_7 (demod_out[7])
);

task send_scaled_sample;
    input mod_value;
    input signed [31:0] base_value;
    integer i;
    reg signed [31:0] scaled_value;
    begin
        @(negedge clk);
        mod_i = mod_value;
        for (i = 0; i < 8; i = i + 1) begin
            scaled_value = base_value * (i + 1);
            sample[i] = scaled_value[23:0];
        end
        new_data = 1'b1;
        @(negedge clk);
        new_data = 1'b0;
    end
endtask

task expect_channel_demod;
    input integer channel_index;
    input signed [31:0] expected;
    begin
        if ($signed(demod_out[channel_index]) !== expected) begin
            $display(
                "FAIL: ch%0d expected %0d got %0d",
                channel_index + 1,
                expected,
                $signed(demod_out[channel_index])
            );
            failures = failures + 1;
        end else begin
            $display("PASS: ch%0d = %0d", channel_index + 1, $signed(demod_out[channel_index]));
        end
    end
endtask

initial begin
    for (channel = 0; channel < 8; channel = channel + 1) begin
        sample[channel] = 24'd0;
    end

    repeat (3) @(negedge clk);
    rstn = 1'b1;
    repeat (2) @(negedge clk);
    enable = 1'b1;

    send_scaled_sample(1'b1, 32'sd100);
    send_scaled_sample(1'b1, 32'sd120);
    send_scaled_sample(1'b0, -32'sd50);
    repeat (420) @(negedge clk);
    send_scaled_sample(1'b0, -32'sd70);
    send_scaled_sample(1'b0, -32'sd90);
    send_scaled_sample(1'b1, 32'sd200);
    repeat (420) @(negedge clk);

    for (channel = 0; channel < 8; channel = channel + 1) begin
        expect_channel_demod(channel, 32'sd90 * (channel + 1));
    end

    if (failures == 0) begin
        $display("ads1278_demod_multichannel_tb PASS");
    end else begin
        $display("ads1278_demod_multichannel_tb FAIL: %0d failure(s)", failures);
    end

    $finish;
end

endmodule
