`timescale 1 ns / 1 ps

////////////////////////////////////////////////////////////////////////////////
// Simple synchronous frame FIFO for staged DMA bring-up.
// Phase 3 uses push-only operation; pop support is included for later work.
////////////////////////////////////////////////////////////////////////////////

module ads1278_frame_fifo #(
    parameter integer DATA_W = 320,
    parameter integer DEPTH = 64,
    parameter integer LEVEL_W = $clog2(DEPTH + 1)
) (
    input  wire              clk,
    input  wire              rstn,
    input  wire              clear,
    input  wire              push,
    input  wire              pop,
    input  wire [DATA_W-1:0] din,
    output reg  [DATA_W-1:0] dout,
    output wire              empty,
    output wire              full,
    output reg  [LEVEL_W-1:0] level
);

localparam integer ADDR_W = (DEPTH <= 1) ? 1 : $clog2(DEPTH);
localparam [LEVEL_W-1:0] DEPTH_COUNT = DEPTH;

(* ram_style = "block" *) reg [DATA_W-1:0] mem [0:DEPTH-1];
reg [ADDR_W-1:0] wr_ptr;
reg [ADDR_W-1:0] rd_ptr;

wire do_push = push && !full;
wire do_pop  = pop && !empty;

wire [ADDR_W-1:0] wr_ptr_next =
    (wr_ptr == DEPTH - 1) ? {ADDR_W{1'b0}} : (wr_ptr + {{(ADDR_W-1){1'b0}}, 1'b1});
wire [ADDR_W-1:0] rd_ptr_next =
    (rd_ptr == DEPTH - 1) ? {ADDR_W{1'b0}} : (rd_ptr + {{(ADDR_W-1){1'b0}}, 1'b1});

assign empty = (level == {LEVEL_W{1'b0}});
assign full  = (level == DEPTH_COUNT);

always @(posedge clk or negedge rstn) begin
    if (!rstn) begin
        wr_ptr <= {ADDR_W{1'b0}};
        rd_ptr <= {ADDR_W{1'b0}};
        dout   <= {DATA_W{1'b0}};
        level  <= {LEVEL_W{1'b0}};
    end else if (clear) begin
        wr_ptr <= {ADDR_W{1'b0}};
        rd_ptr <= {ADDR_W{1'b0}};
        dout   <= {DATA_W{1'b0}};
        level  <= {LEVEL_W{1'b0}};
    end else begin
        case ({do_push, do_pop})
            2'b10: begin
                mem[wr_ptr] <= din;
                wr_ptr      <= wr_ptr_next;
                level       <= level + {{(LEVEL_W-1){1'b0}}, 1'b1};
            end
            2'b01: begin
                dout  <= mem[rd_ptr];
                rd_ptr <= rd_ptr_next;
                level <= level - {{(LEVEL_W-1){1'b0}}, 1'b1};
            end
            2'b11: begin
                mem[wr_ptr] <= din;
                dout        <= mem[rd_ptr];
                wr_ptr      <= wr_ptr_next;
                rd_ptr      <= rd_ptr_next;
            end
            default: begin
            end
        endcase
    end
end

endmodule
