`timescale 1 ns / 1 ps

module ads1278_demod_divider_tb;

reg clk = 1'b0;
reg rstn = 1'b0;
reg start = 1'b0;
reg signed [47:0] dividend = 48'sd0;
reg [15:0] divisor = 16'd1;
wire busy;
wire done;
wire signed [31:0] quotient;

integer failures = 0;
integer wait_cycles;

always #5 clk = ~clk;

ads1278_demod_divider dut (
    .clk      (clk),
    .rstn     (rstn),
    .start    (start),
    .dividend (dividend),
    .divisor  (divisor),
    .busy     (busy),
    .done     (done),
    .quotient (quotient)
);

task run_case;
    input signed [47:0] dividend_value;
    input [15:0] divisor_value;
    input [255:0] label;
    reg signed [47:0] expected_full;
    reg signed [31:0] expected;
    begin
        expected_full = (divisor_value == 16'd0)
                      ? 48'sd0
                      : (dividend_value / $signed({32'd0, divisor_value}));
        expected = expected_full[31:0];

        @(negedge clk);
        dividend = dividend_value;
        divisor = divisor_value;
        start = 1'b1;
        @(negedge clk);
        start = 1'b0;

        wait_cycles = 0;
        while (!done && wait_cycles < 80) begin
            @(negedge clk);
            wait_cycles = wait_cycles + 1;
        end

        if (!done) begin
            $display("FAIL: %0s timed out", label);
            failures = failures + 1;
        end else if (quotient !== expected) begin
            $display(
                "FAIL: %0s expected %0d got %0d",
                label,
                expected,
                quotient
            );
            failures = failures + 1;
        end else begin
            $display("PASS: %0s = %0d", label, quotient);
        end
    end
endtask

initial begin
    repeat (3) @(negedge clk);
    rstn = 1'b1;
    repeat (2) @(negedge clk);

    run_case(48'sd110, 16'd2, "positive exact");
    run_case(48'sd101, 16'd3, "positive truncates toward zero");
    run_case(-48'sd101, 16'd3, "negative truncates toward zero");
    run_case(48'sd0, 16'd17, "zero dividend");
    run_case(48'sh00007fff_ffff, 16'd255, "large positive");
    run_case(-48'sh00007fff_ffff, 16'd255, "large negative");
    run_case(48'sd1234, 16'd0, "zero divisor returns zero");

    @(negedge clk);
    dividend = -48'sd9999;
    divisor = 16'd7;
    start = 1'b1;
    @(negedge clk);
    start = 1'b0;
    repeat (5) @(negedge clk);
    rstn = 1'b0;
    repeat (2) @(negedge clk);
    rstn = 1'b1;
    repeat (2) @(negedge clk);
    if (busy || done) begin
        $display("FAIL: reset mid-run did not return divider to idle");
        failures = failures + 1;
    end else begin
        $display("PASS: reset mid-run returns divider to idle");
    end

    if (failures == 0) begin
        $display("ads1278_demod_divider_tb PASS");
    end else begin
        $display("ads1278_demod_divider_tb FAIL: %0d failure(s)", failures);
    end

    $finish;
end

endmodule
