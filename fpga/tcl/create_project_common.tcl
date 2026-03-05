# Shared project creation for rp_ads1278 Vivado projects.
# Expects: origin_dir, board_part, board_work_dir (from board config).
# Optional: rp_force (recreate project).

set _proj_name "rp_ads1278"
if {[info exists _xil_proj_name_]} {
  set _proj_name $_xil_proj_name_
}

set orig_proj_dir [file normalize "$origin_dir/$board_work_dir"]

if {[info exists rp_force] && $rp_force} {
  create_project $_proj_name "./$board_work_dir" -part $board_part -force
} else {
  create_project $_proj_name "./$board_work_dir" -part $board_part
}

set proj_dir [get_property directory [current_project]]

set obj [current_project]
set_property -name "default_lib"              -value "xil_defaultlib"                    -objects $obj
set_property -name "ip_cache_permissions"     -value "read write"                        -objects $obj
set_property -name "ip_output_repo"           -value "$proj_dir/$_proj_name.cache/ip"    -objects $obj
set_property -name "part"                     -value "$board_part"                       -objects $obj
set_property -name "sim.ip.auto_export_scripts" -value "1"                              -objects $obj
set_property -name "simulator_language"       -value "Mixed"                             -objects $obj
set_property -name "xpm_libraries"            -value "XPM_CDC XPM_MEMORY"                -objects $obj

if {[string equal [get_filesets -quiet sources_1] ""]} {
  create_fileset -srcset sources_1
}
