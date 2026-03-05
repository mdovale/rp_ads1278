interface gpio_if #(
  int unsigned DW = 8
);

logic [DW-1:0] i;
logic [DW-1:0] o;
logic [DW-1:0] t;

modport m (
  input  i,
  output o,
  output t
);

modport s (
  output i,
  input  o,
  input  t
);

endinterface: gpio_if
