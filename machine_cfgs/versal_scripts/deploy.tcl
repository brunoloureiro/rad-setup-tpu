# deploy.tcl - Load PDI + ELF over JTAG (run after debug.tcl has switched to JTAG mode)
#
# Uses name-based target selection since target numbers shift depending on board state.

set PDI_PATH $::env(PDI_PATH)

puts "Loading PDI: $PDI_PATH"
targets -set -filter {name =~ "PMC"}
device program $PDI_PATH
after 3000

if {[info exists ::env(ELF_PATH)]} {
    set ELF_PATH $::env(ELF_PATH)
    puts "Loading ELF: $ELF_PATH"
    targets -set -filter {name =~ "Cortex-A72 #0"}
    rst -processor -clear-registers
    dow -force $ELF_PATH
    con
} else {
    puts "No ELF_PATH set — ELF is embedded in PDI, PLM will boot A72."
}

puts "Done. Watch UART for output."
