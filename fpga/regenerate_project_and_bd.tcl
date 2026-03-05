set origin_dir [file normalize .]

# Load board config (part, work_dir, paths)
if {$rp_model == "rp125_14"} {
    source [file join $origin_dir tcl board_config_rp125_14.tcl]
} else {
    puts "Only rp125_14 is supported for rp_ads1278."
    exit 1
}

# Delete old project files
file delete -force ./$board_work_dir

# Create project, add sources, configure runs
source [file join $origin_dir $board_cfg_script]

# Generate block design
source [file join $origin_dir $board_bd_script]

# Generate the block design wrapper and import (but do NOT set as top)
set design_name [get_bd_designs]
make_wrapper -files [get_files $design_name.bd] -top -import

# Ensure red_pitaya_top is the synthesis top (not the BD wrapper)
set_property top red_pitaya_top [current_fileset]
