############################################################################
# Red Pitaya 125-14 IO constraints for rp_ads1278
# Based on RedPitaya-FPGA/sdc/red_pitaya.xdc
############################################################################

### ADC
set_property IOSTANDARD LVCMOS18 [get_ports {adc_dat_i[*][*]}]
set_property IOB        TRUE     [get_ports {adc_dat_i[*][*]}]

set_property PACKAGE_PIN V17     [get_ports {adc_dat_i[0][0]}]
set_property PACKAGE_PIN U17     [get_ports {adc_dat_i[0][1]}]
set_property PACKAGE_PIN Y17     [get_ports {adc_dat_i[0][2]}]
set_property PACKAGE_PIN W16     [get_ports {adc_dat_i[0][3]}]
set_property PACKAGE_PIN Y16     [get_ports {adc_dat_i[0][4]}]
set_property PACKAGE_PIN W15     [get_ports {adc_dat_i[0][5]}]
set_property PACKAGE_PIN W14     [get_ports {adc_dat_i[0][6]}]
set_property PACKAGE_PIN Y14     [get_ports {adc_dat_i[0][7]}]
set_property PACKAGE_PIN W13     [get_ports {adc_dat_i[0][8]}]
set_property PACKAGE_PIN V12     [get_ports {adc_dat_i[0][9]}]
set_property PACKAGE_PIN V13     [get_ports {adc_dat_i[0][10]}]
set_property PACKAGE_PIN T14     [get_ports {adc_dat_i[0][11]}]
set_property PACKAGE_PIN T15     [get_ports {adc_dat_i[0][12]}]
set_property PACKAGE_PIN V15     [get_ports {adc_dat_i[0][13]}]
set_property PACKAGE_PIN T16     [get_ports {adc_dat_i[0][14]}]
set_property PACKAGE_PIN V16     [get_ports {adc_dat_i[0][15]}]

set_property PACKAGE_PIN T17     [get_ports {adc_dat_i[1][0]}]
set_property PACKAGE_PIN R16     [get_ports {adc_dat_i[1][1]}]
set_property PACKAGE_PIN R18     [get_ports {adc_dat_i[1][2]}]
set_property PACKAGE_PIN P16     [get_ports {adc_dat_i[1][3]}]
set_property PACKAGE_PIN P18     [get_ports {adc_dat_i[1][4]}]
set_property PACKAGE_PIN N17     [get_ports {adc_dat_i[1][5]}]
set_property PACKAGE_PIN R19     [get_ports {adc_dat_i[1][6]}]
set_property PACKAGE_PIN T20     [get_ports {adc_dat_i[1][7]}]
set_property PACKAGE_PIN T19     [get_ports {adc_dat_i[1][8]}]
set_property PACKAGE_PIN U20     [get_ports {adc_dat_i[1][9]}]
set_property PACKAGE_PIN V20     [get_ports {adc_dat_i[1][10]}]
set_property PACKAGE_PIN W20     [get_ports {adc_dat_i[1][11]}]
set_property PACKAGE_PIN W19     [get_ports {adc_dat_i[1][12]}]
set_property PACKAGE_PIN Y19     [get_ports {adc_dat_i[1][13]}]
set_property PACKAGE_PIN W18     [get_ports {adc_dat_i[1][14]}]
set_property PACKAGE_PIN Y18     [get_ports {adc_dat_i[1][15]}]

set_property IOSTANDARD DIFF_HSTL_I_18 [get_ports adc_clk_i[*]]
set_property PACKAGE_PIN U18           [get_ports adc_clk_i[1]]
set_property PACKAGE_PIN U19           [get_ports adc_clk_i[0]]

set_property IOSTANDARD LVCMOS18 [get_ports {adc_clk_o[*]}]
set_property SLEW       FAST     [get_ports {adc_clk_o[*]}]
set_property DRIVE      8        [get_ports {adc_clk_o[*]}]
set_property PACKAGE_PIN N20 [get_ports {adc_clk_o[0]}]
set_property PACKAGE_PIN P20 [get_ports {adc_clk_o[1]}]

set_property IOSTANDARD  LVCMOS18 [get_ports adc_cdcs_o]
set_property PACKAGE_PIN V18     [get_ports adc_cdcs_o]
set_property SLEW        FAST     [get_ports adc_cdcs_o]
set_property DRIVE       8        [get_ports adc_cdcs_o]

### DAC
set_property IOSTANDARD LVCMOS33 [get_ports {dac_dat_o[*]}]
set_property SLEW       SLOW     [get_ports {dac_dat_o[*]}]
set_property DRIVE      8        [get_ports {dac_dat_o[*]}]

set_property PACKAGE_PIN M19 [get_ports {dac_dat_o[0]}]
set_property PACKAGE_PIN M20 [get_ports {dac_dat_o[1]}]
set_property PACKAGE_PIN L19 [get_ports {dac_dat_o[2]}]
set_property PACKAGE_PIN L20 [get_ports {dac_dat_o[3]}]
set_property PACKAGE_PIN K19 [get_ports {dac_dat_o[4]}]
set_property PACKAGE_PIN J19 [get_ports {dac_dat_o[5]}]
set_property PACKAGE_PIN J20 [get_ports {dac_dat_o[6]}]
set_property PACKAGE_PIN H20 [get_ports {dac_dat_o[7]}]
set_property PACKAGE_PIN G19 [get_ports {dac_dat_o[8]}]
set_property PACKAGE_PIN G20 [get_ports {dac_dat_o[9]}]
set_property PACKAGE_PIN F19 [get_ports {dac_dat_o[10]}]
set_property PACKAGE_PIN F20 [get_ports {dac_dat_o[11]}]
set_property PACKAGE_PIN D20 [get_ports {dac_dat_o[12]}]
set_property PACKAGE_PIN D19 [get_ports {dac_dat_o[13]}]

set_property IOSTANDARD LVCMOS33 [get_ports dac_*_o]
set_property SLEW       FAST     [get_ports dac_*_o]
set_property DRIVE      8        [get_ports dac_*_o]

set_property PACKAGE_PIN M17 [get_ports dac_wrt_o]
set_property PACKAGE_PIN N16 [get_ports dac_sel_o]
set_property PACKAGE_PIN M18 [get_ports dac_clk_o]
set_property PACKAGE_PIN N15 [get_ports dac_rst_o]

### PWM DAC
set_property IOSTANDARD LVCMOS18 [get_ports {dac_pwm_o[*]}]
set_property SLEW       FAST     [get_ports {dac_pwm_o[*]}]
set_property DRIVE      12       [get_ports {dac_pwm_o[*]}]
set_property IOB        TRUE     [get_ports {dac_pwm_o[*]}]

set_property PACKAGE_PIN T10 [get_ports {dac_pwm_o[0]}]
set_property PACKAGE_PIN T11 [get_ports {dac_pwm_o[1]}]
set_property PACKAGE_PIN P15 [get_ports {dac_pwm_o[2]}]
set_property PACKAGE_PIN U13 [get_ports {dac_pwm_o[3]}]

### Expansion connector — ADS1278 signals on E1 P-side
# Pin function assignment:
#   exp_p_io[0]  G17  SCLK    (output)
#   exp_p_io[1]  H16  MISO    (input)
#   exp_p_io[2]  J18  DRDY    (input)
#   exp_p_io[3]  K17  SYNC    (output)
#   exp_p_io[4]  L14  EXTCLK  (output)
#   exp_p_io[5..7]    unused
#   exp_n_io[0..7]    unused

set_property -dict {PACKAGE_PIN G17 IOSTANDARD LVCMOS33} [get_ports {exp_p_io[0]}]
set_property -dict {PACKAGE_PIN G18 IOSTANDARD LVCMOS33} [get_ports {exp_n_io[0]}]
set_property -dict {PACKAGE_PIN H16 IOSTANDARD LVCMOS33} [get_ports {exp_p_io[1]}]
set_property -dict {PACKAGE_PIN H17 IOSTANDARD LVCMOS33} [get_ports {exp_n_io[1]}]
set_property -dict {PACKAGE_PIN J18 IOSTANDARD LVCMOS33} [get_ports {exp_p_io[2]}]
set_property -dict {PACKAGE_PIN H18 IOSTANDARD LVCMOS33} [get_ports {exp_n_io[2]}]
set_property -dict {PACKAGE_PIN K17 IOSTANDARD LVCMOS33} [get_ports {exp_p_io[3]}]
set_property -dict {PACKAGE_PIN K18 IOSTANDARD LVCMOS33} [get_ports {exp_n_io[3]}]
set_property -dict {PACKAGE_PIN L14 IOSTANDARD LVCMOS33} [get_ports {exp_p_io[4]}]
set_property -dict {PACKAGE_PIN L15 IOSTANDARD LVCMOS33} [get_ports {exp_n_io[4]}]
set_property -dict {PACKAGE_PIN L16 IOSTANDARD LVCMOS33} [get_ports {exp_p_io[5]}]
set_property -dict {PACKAGE_PIN L17 IOSTANDARD LVCMOS33} [get_ports {exp_n_io[5]}]
set_property -dict {PACKAGE_PIN K16 IOSTANDARD LVCMOS33} [get_ports {exp_p_io[6]}]
set_property -dict {PACKAGE_PIN J16 IOSTANDARD LVCMOS33} [get_ports {exp_n_io[6]}]
set_property -dict {PACKAGE_PIN M14 IOSTANDARD LVCMOS33} [get_ports {exp_p_io[7]}]
set_property -dict {PACKAGE_PIN M15 IOSTANDARD LVCMOS33} [get_ports {exp_n_io[7]}]

# SLEW/DRIVE only meaningful for output pins; Vivado ignores for inputs
set_property SLEW  FAST [get_ports {exp_p_io[0]}]
set_property DRIVE 8    [get_ports {exp_p_io[0]}]
set_property SLEW  FAST [get_ports {exp_p_io[3]}]
set_property DRIVE 8    [get_ports {exp_p_io[3]}]
set_property SLEW  FAST [get_ports {exp_p_io[4]}]
set_property DRIVE 8    [get_ports {exp_p_io[4]}]

### SATA connector
set_property IOSTANDARD LVCMOS18 [get_ports {daisy_p_o[*]}]
set_property IOSTANDARD LVCMOS18 [get_ports {daisy_n_o[*]}]
set_property IOSTANDARD LVCMOS18 [get_ports {daisy_p_i[*]}]
set_property IOSTANDARD LVCMOS18 [get_ports {daisy_n_i[*]}]

set_property PACKAGE_PIN T12 [get_ports {daisy_p_o[0]}]
set_property PACKAGE_PIN U12 [get_ports {daisy_n_o[0]}]
set_property PACKAGE_PIN U14 [get_ports {daisy_p_o[1]}]
set_property PACKAGE_PIN U15 [get_ports {daisy_n_o[1]}]
set_property PACKAGE_PIN P14 [get_ports {daisy_p_i[0]}]
set_property PACKAGE_PIN R14 [get_ports {daisy_n_i[0]}]
set_property PACKAGE_PIN N18 [get_ports {daisy_p_i[1]}]
set_property PACKAGE_PIN P19 [get_ports {daisy_n_i[1]}]

### LED
set_property IOSTANDARD LVCMOS33 [get_ports {led_o[*]}]
set_property SLEW       SLOW     [get_ports {led_o[*]}]
set_property DRIVE      4        [get_ports {led_o[*]}]

set_property PACKAGE_PIN F16     [get_ports {led_o[0]}]
set_property PACKAGE_PIN F17     [get_ports {led_o[1]}]
set_property PACKAGE_PIN G15     [get_ports {led_o[2]}]
set_property PACKAGE_PIN H15     [get_ports {led_o[3]}]
set_property PACKAGE_PIN K14     [get_ports {led_o[4]}]
set_property PACKAGE_PIN G14     [get_ports {led_o[5]}]
set_property PACKAGE_PIN J15     [get_ports {led_o[6]}]
set_property PACKAGE_PIN J14     [get_ports {led_o[7]}]
