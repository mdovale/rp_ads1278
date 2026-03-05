# ads1278.tcl — Vivado project configuration for rp_ads1278

set origin_dir "./"

if { [info exists ::origin_dir_loc] } {
  set origin_dir $::origin_dir_loc
}

# Load board config if not already set
if {![info exists board_part]} {
  source [file join $origin_dir tcl board_config_rp125_14.tcl]
}

source [file join $origin_dir tcl create_project_common.tcl]

# ---------- RTL sources ----------
set obj [get_filesets sources_1]
set files [list \
 "[file normalize "$origin_dir/rtl/axi4_lite_if.sv"]"\
 "[file normalize "$origin_dir/rtl/gpio_if.sv"]"\
 "[file normalize "$origin_dir/rtl/red_pitaya_pll.sv"]"\
 "[file normalize "$origin_dir/rtl/red_pitaya_ps.sv"]"\
 "[file normalize "$origin_dir/rtl/red_pitaya_top.sv"]"\
 "[file normalize "$origin_dir/rtl/ads1278_axi_slave.sv"]"\
 "[file normalize "$origin_dir/rtl/ads1278_acq_top.v"]"\
 "[file normalize "$origin_dir/rtl/ads1278_spi_tdm.v"]"\
 "[file normalize "$origin_dir/rtl/ads1278_extclk_gen.v"]"\
 "[file normalize "$origin_dir/rtl/ads1278_sync_pulse.v"]"\
]
add_files -norecurse -fileset $obj $files

# Mark SystemVerilog files
foreach f [list \
  "$origin_dir/rtl/axi4_lite_if.sv" \
  "$origin_dir/rtl/gpio_if.sv" \
  "$origin_dir/rtl/red_pitaya_pll.sv" \
  "$origin_dir/rtl/red_pitaya_ps.sv" \
  "$origin_dir/rtl/red_pitaya_top.sv" \
  "$origin_dir/rtl/ads1278_axi_slave.sv" \
] {
  set file_obj [get_files -of_objects [get_filesets sources_1] [file normalize $f]]
  set_property -name "file_type" -value "SystemVerilog" -objects $file_obj
}

set_property -name "top" -value "red_pitaya_top" -objects $obj

# ---------- Constraint files ----------
if {[string equal [get_filesets -quiet constrs_1] ""]} {
  create_fileset -constrset constrs_1
}
set obj [get_filesets constrs_1]

set cons_files [list \
  "[file normalize "$origin_dir/$board_cons_dir/ports.xdc"]"\
  "[file normalize "$origin_dir/$board_cons_dir/clocks.xdc"]"\
]
add_files -norecurse -fileset $obj $cons_files

# ---------- Runs ----------
# synth_1 and impl_1 are auto-created by create_project.
# Top module is already set on sources_1 fileset above.
current_run -synthesis [get_runs synth_1]
current_run -implementation [get_runs impl_1]
