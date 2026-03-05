`timescale 1 ns / 1 ps

////////////////////////////////////////////////////////////////////////////////
// SYNC pulse generator — drives /SYNC low for 1 EXTCLK period when triggered.
// Trigger is a single-cycle pulse from the AXI CTRL register write.
////////////////////////////////////////////////////////////////////////////////

module ads1278_sync_pulse (
    input  wire        clk,
    input  wire        rstn,
    input  wire        trigger,
    input  wire [31:0] extclk_div,
    output reg         sync_n_o
);

// Pulse duration = 2 × extclk_div sys-clk cycles (= 1 EXTCLK period)
wire [31:0] pulse_len = (extclk_div < 32'd2)
                      ? 32'd4
                      : {extclk_div[30:0], 1'b0};

reg        active;
reg [31:0] cnt;

always @(posedge clk or negedge rstn) begin
    if (!rstn) begin
        active   <= 1'b0;
        cnt      <= 32'd0;
        sync_n_o <= 1'b1;
    end else begin
        if (!active && trigger) begin
            active   <= 1'b1;
            cnt      <= pulse_len;
            sync_n_o <= 1'b0;
        end else if (active) begin
            if (cnt == 32'd0) begin
                active   <= 1'b0;
                sync_n_o <= 1'b1;
            end else begin
                cnt <= cnt - 32'd1;
            end
        end
    end
end

endmodule
