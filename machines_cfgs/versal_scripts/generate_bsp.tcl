# generate_bsp.tcl - generate BSP from a linked XSA using xsct
# Usage: xsct scripts/generate_bsp.tcl <path/to/linked.xsa> <output/bsp/dir>

set xsa_path  [lindex $argv 0]
set out_dir   [lindex $argv 1]
set ws        [file join $out_dir workspace]

# Clean any previous workspace so the build is reproducible
file delete -force $ws
setws $ws

platform create -name bsp_platform \
    -hw $xsa_path \
    -out $out_dir

platform active bsp_platform
domain create -name standalone_psv_cortexa72_0 \
    -os standalone \
    -proc versal_cips_0_pspmc_0_psv_cortexa72_0

platform generate

# The generated BSP headers and libs are now under:
# $out_dir/bsp_platform/export/bsp_platform/sw/standalone_psv_cortexa72_0/
puts "BSP generated at: $out_dir"