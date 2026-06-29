`timescale 1 ns / 1 ps

module ads1278_demod_tb;

reg clk = 1'b0;
reg rstn = 1'b0;
reg enable = 1'b0;
reg new_data = 1'b0;
reg mod_i = 1'b1;
reg [23:0] sample = 24'd0;
reg [15:0] demod_skip = 16'd0;
wire [31:0] demod_out;

integer failures = 0;

always #5 clk = ~clk;

ads1278_demod dut (
    .clk        (clk),
    .rstn       (rstn),
    .enable     (enable),
    .new_data   (new_data),
    .mod_i      (mod_i),
    .sample     (sample),
    .demod_skip (demod_skip),
    .demod_out  (demod_out)
);

task send_sample;
    input mod_value;
    input signed [31:0] value;
    begin
        @(negedge clk);
        mod_i = mod_value;
        sample = value[23:0];
        new_data = 1'b1;
        @(negedge clk);
        new_data = 1'b0;
    end
endtask

task reset_and_enable;
    input [15:0] skip_value;
    begin
        @(negedge clk);
        rstn = 1'b0;
        enable = 1'b0;
        new_data = 1'b0;
        mod_i = 1'b1;
        sample = 24'd0;
        demod_skip = skip_value;
        repeat (3) @(negedge clk);
        rstn = 1'b1;
        repeat (2) @(negedge clk);
        enable = 1'b1;
        @(negedge clk);
    end
endtask

task expect_demod;
    input signed [31:0] expected;
    input [255:0] label;
    begin
        if ($signed(demod_out) !== expected) begin
            $display("FAIL: %0s expected %0d got %0d", label, expected, $signed(demod_out));
            failures = failures + 1;
        end else begin
            $display("PASS: %0s = %0d", label, $signed(demod_out));
        end
    end
endtask

initial begin
    reset_and_enable(16'd0);

    // N=0 matches the original behavior: the first sample after an edge is accumulated.
    send_sample(1'b1, 32'sd10);
    send_sample(1'b1, 32'sd14);
    send_sample(1'b0, -32'sd1000);
    send_sample(1'b0, -32'sd4);
    send_sample(1'b0, -32'sd6);
    send_sample(1'b1, 32'sd20);
    expect_demod(32'sd174, "demod_skip=0 includes falling-edge sample");

    reset_and_enable(16'd3);

    // The first three enabled samples are skipped because the post-edge counter starts at zero.
    send_sample(1'b1, 32'sd900);
    send_sample(1'b1, 32'sd901);
    send_sample(1'b1, 32'sd902);
    send_sample(1'b1, 32'sd10);
    send_sample(1'b1, 32'sd14);

    // After the falling edge, these three settling samples must not affect the negative average.
    send_sample(1'b0, -32'sd1000);
    send_sample(1'b0, -32'sd1000);
    send_sample(1'b0, -32'sd1000);
    send_sample(1'b0, -32'sd2);
    send_sample(1'b0, -32'sd4);
    send_sample(1'b0, -32'sd6);
    send_sample(1'b1, 32'sd20);
    expect_demod(32'sd8, "demod_skip=3 excludes first three post-edge samples");

    if (failures == 0) begin
        $display("ads1278_demod_tb PASS");
    end else begin
        $display("ads1278_demod_tb FAIL: %0d failure(s)", failures);
    end

    $finish;
end

endmodule
