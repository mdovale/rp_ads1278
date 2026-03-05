`timescale 1 ns / 1 ps

////////////////////////////////////////////////////////////////////////////////
// ADS1278 SPI TDM receiver.
// On DRDY falling edge: waits 1 EXTCLK period, then clocks 192 SCLKs to
// shift in 8 channels × 24 bits (CH1..CH8, MSB first).
// CPOL=0, CPHA=0 — SCLK idles low; MISO sampled on rising edge.
////////////////////////////////////////////////////////////////////////////////

module ads1278_spi_tdm (
    input  wire        clk,
    input  wire        rstn,
    input  wire        enable,
    input  wire        miso_i,
    input  wire        drdy_n_i,
    input  wire [31:0] sclk_div,    // SCLK half-period in sys-clk cycles
    output reg         sclk_o,
    output reg  [23:0] ch_data_0,
    output reg  [23:0] ch_data_1,
    output reg  [23:0] ch_data_2,
    output reg  [23:0] ch_data_3,
    output reg  [23:0] ch_data_4,
    output reg  [23:0] ch_data_5,
    output reg  [23:0] ch_data_6,
    output reg  [23:0] ch_data_7,
    output reg         new_data,
    output reg  [15:0] frame_cnt,
    output reg         overflow
);

// FSM states
localparam [2:0] S_IDLE     = 3'd0,
                 S_WAIT     = 3'd1,
                 S_SHIFT    = 3'd2,
                 S_LATCH    = 3'd3;

reg [2:0]   state;
reg [31:0]  div_cnt;       // counter for half-period timing
reg [31:0]  wait_cnt;      // counter for DRDY→SCLK wait (2× half-period = 1 EXTCLK period)
reg [7:0]   bit_cnt;       // counts 0..191
reg         sclk_phase;    // 0 = rising edge next, 1 = falling edge next
reg [191:0] shift_reg;
reg         sample_now;    // delayed sampling strobe

// ---- DRDY synchroniser (2FF) + edge detect ----
reg drdy_s0, drdy_s1, drdy_s2;
always @(posedge clk) begin
    drdy_s0 <= drdy_n_i;
    drdy_s1 <= drdy_s0;
    drdy_s2 <= drdy_s1;
end
wire drdy_fall = drdy_s2 & ~drdy_s1;

// ---- MISO synchroniser (2FF) ----
reg miso_s0, miso_s1;
always @(posedge clk) begin
    miso_s0 <= miso_i;
    miso_s1 <= miso_s0;
end

// Effective divider (clamp minimum to 2 to avoid zero-period)
wire [31:0] div_eff = (sclk_div < 32'd2) ? 32'd2 : sclk_div;

// ---- Main FSM ----
always @(posedge clk or negedge rstn) begin
    if (!rstn) begin
        state      <= S_IDLE;
        sclk_o     <= 1'b0;
        sclk_phase <= 1'b0;
        div_cnt    <= 32'd0;
        wait_cnt   <= 32'd0;
        bit_cnt    <= 8'd0;
        shift_reg  <= 192'd0;
        new_data   <= 1'b0;
        frame_cnt  <= 16'd0;
        overflow   <= 1'b0;
        sample_now <= 1'b0;
        ch_data_0  <= 24'd0;
        ch_data_1  <= 24'd0;
        ch_data_2  <= 24'd0;
        ch_data_3  <= 24'd0;
        ch_data_4  <= 24'd0;
        ch_data_5  <= 24'd0;
        ch_data_6  <= 24'd0;
        ch_data_7  <= 24'd0;
    end else begin
        new_data   <= 1'b0;
        sample_now <= 1'b0;

        case (state)
        // ---------------------------------------------------
        S_IDLE: begin
            sclk_o     <= 1'b0;
            sclk_phase <= 1'b0;
            div_cnt    <= 32'd0;
            bit_cnt    <= 8'd0;
            if (enable && drdy_fall) begin
                // Wait 1 EXTCLK period = 2 × half-period sys clk cycles
                wait_cnt <= {div_eff[30:0], 1'b0};  // 2 * div_eff
                state    <= S_WAIT;
            end
        end

        // ---------------------------------------------------
        S_WAIT: begin
            if (wait_cnt == 32'd0) begin
                state <= S_SHIFT;
            end else begin
                wait_cnt <= wait_cnt - 32'd1;
            end
        end

        // ---------------------------------------------------
        S_SHIFT: begin
            if (div_cnt == div_eff - 32'd1) begin
                div_cnt <= 32'd0;
                if (!sclk_phase) begin
                    // Rising edge: assert SCLK high, schedule sampling
                    sclk_o     <= 1'b1;
                    sclk_phase <= 1'b1;
                    sample_now <= 1'b1;
                end else begin
                    // Falling edge: deassert SCLK, advance bit counter
                    sclk_o     <= 1'b0;
                    sclk_phase <= 1'b0;
                    bit_cnt    <= bit_cnt + 8'd1;
                    if (bit_cnt == 8'd191) begin
                        state <= S_LATCH;
                    end
                end
            end else begin
                div_cnt <= div_cnt + 32'd1;
            end

            // Sample MISO one cycle after rising edge for hold margin
            if (sample_now) begin
                shift_reg <= {shift_reg[190:0], miso_s1};
            end
        end

        // ---------------------------------------------------
        S_LATCH: begin
            sclk_o <= 1'b0;
            // Unpack 192-bit shift register: CH1 first (MSB), CH8 last
            ch_data_0 <= shift_reg[191:168];
            ch_data_1 <= shift_reg[167:144];
            ch_data_2 <= shift_reg[143:120];
            ch_data_3 <= shift_reg[119: 96];
            ch_data_4 <= shift_reg[ 95: 72];
            ch_data_5 <= shift_reg[ 71: 48];
            ch_data_6 <= shift_reg[ 47: 24];
            ch_data_7 <= shift_reg[ 23:  0];
            new_data  <= 1'b1;
            frame_cnt <= frame_cnt + 16'd1;
            state     <= S_IDLE;
        end

        default: state <= S_IDLE;
        endcase

        // Overflow: DRDY falls while we're still reading the previous frame
        if ((state == S_SHIFT || state == S_WAIT) && drdy_fall)
            overflow <= 1'b1;

        // Clear overflow when disabled
        if (!enable) begin
            overflow  <= 1'b0;
            frame_cnt <= 16'd0;
        end
    end
end

endmodule
