# debug.tcl - Switch Versal boot mode to JTAG for one session
# From AMD KB 000033254 / versal_change_boot_mode.tcl
# Board returns to SD boot on next power cycle (physical switches unchanged).
#
# Uses name-based target selection since target numbers shift depending on board state.

# Switch boot mode to JTAG
targets -set -filter {name =~ "Versal*"}
mwr 0xF1260200 0x0100
mrd 0xF1260200

# Clear MULTIBOOT address
mwr -force 0xF1110004 0x0

# Reset via PMC
targets -set -filter {name =~ "PMC"}
rst -system

after 3000
puts "Done. Board rebooted in JTAG mode."
