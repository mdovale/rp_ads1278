`timescale 1 ns / 1 ps

////////////////////////////////////////////////////////////////////////////////
// One-entry output buffer with backpressure.
////////////////////////////////////////////////////////////////////////////////

module output_buffer #(
    parameter integer DATA_WIDTH = 32
) (
    input  wire                  aclk,
    input  wire                  aresetn,
    input  wire [DATA_WIDTH-1:0] in_data,
    input  wire                  in_valid,
    output wire                  in_ready,
    output reg  [DATA_WIDTH-1:0] out_data,
    output reg                   out_valid,
    input  wire                  out_ready
);

assign in_ready = ~out_valid || out_ready;

always @(posedge aclk) begin
    if (!aresetn) begin
        out_data  <= {DATA_WIDTH{1'b0}};
        out_valid <= 1'b0;
    end else if (in_ready) begin
        out_data  <= in_data;
        out_valid <= in_valid;
    end
end

endmodule
