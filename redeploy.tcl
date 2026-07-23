# redeploy.tcl - Reload ELF only (PDI already loaded, use this for iteration)
#
# Uses name-based target selection since target numbers shift depending on board state.

set ELF_PATH $::env(ELF_PATH)

puts "Reloading ELF: $ELF_PATH"
targets -set -filter {name =~ "Cortex-A72 #0"}
rst -processor -clear-registers
dow -force $ELF_PATH
con

puts "Done. ELF reloaded on A72."
