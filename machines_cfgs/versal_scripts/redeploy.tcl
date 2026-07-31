# redeploy.tcl - Reload ELF only (PDI already loaded, use this for iteration)
#
# Uses name-based target selection since target numbers shift depending on board state.
# When more than one identical board is on JTAG, board_select.tcl (sourced
# below) scopes each selection to one physical board via BOARD/BOARD_SERIAL
# -- see that file for details.

source [file join [file dirname [info script]] board_select.tcl]

set ELF_PATH $::env(ELF_PATH)

puts "Reloading ELF: $ELF_PATH"
select_target {name =~ "Cortex-A72 #0"}
rst -processor -clear-registers
dow -force $ELF_PATH
con

puts "Done. ELF reloaded on A72."
