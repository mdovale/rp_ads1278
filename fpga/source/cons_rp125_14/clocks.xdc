############################################################################
# Clock constraints for rp_ads1278 (RedPitaya 125-14)
############################################################################

# ADC input clock — 125 MHz differential
create_clock -period 8.000 -name adc_clk [get_ports adc_clk_i[1]]

set_input_delay -clock adc_clk 3.400 [get_ports adc_dat_i[*][*]]

# SATA RX clock (active even if unused — prevents timing warnings)
create_clock -period 4.000 -name rx_clk  [get_ports daisy_p_i[1]]
