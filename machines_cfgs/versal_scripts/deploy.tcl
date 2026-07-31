# deploy.tcl - Load PDI + ELF over JTAG (run after debug.tcl has switched to JTAG mode)
#
# Uses name-based target selection since target numbers shift depending on board state.
# When more than one identical board is on JTAG, board_select.tcl (sourced
# below) scopes each selection to one physical board via BOARD/BOARD_SERIAL
# -- see that file for details.

source [file join [file dirname [info script]] board_select.tcl]

set PDI_PATH $::env(PDI_PATH)

puts "Loading PDI: $PDI_PATH"
select_target {name =~ "PMC"}
device program $PDI_PATH
after 3000

if {[info exists ::env(ELF_PATH)]} {
    set ELF_PATH $::env(ELF_PATH)
    puts "Loading ELF: $ELF_PATH"
    select_target {name =~ "Cortex-A72 #0"}
    rst -processor -clear-registers
    dow -force $ELF_PATH
    con
} else {
    puts "No ELF_PATH set — ELF is embedded in PDI, PLM will boot A72."
}

puts "Done. Watch UART for output."
