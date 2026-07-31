# board_select.tcl - resolve which physical board to target when hw_server
# sees more than one identical Versal board on JTAG.
#
# xsdb enumerates one full, identically-named target tree per board -- every
# board has its own "Versal xcve2302", "PMC", "Cortex-A72 #0", etc., so a
# plain `targets -set -filter {name =~ ...}` is ambiguous (or silently picks
# whichever board happens to sort first) once a second board is connected.
# Every board's own target subtree does carry a target property that's
# unique per physical board though: jtag_cable_serial (same value on every
# target under one board, since they all sit behind the same JTAG cable).
#
# This file is sourced by debug.tcl/deploy.tcl/redeploy.tcl before they do
# any targeting. It resolves *which* board's jtag_cable_serial to scope to,
# then exposes select_target, a drop-in replacement for
# `targets -set -filter {...}` that additionally constrains the match to
# that one board.
#
# Board selection (env vars, read once at source time):
#   BOARD        1-based index into the boards in xsdb's own enumeration
#                order (i.e. by ascending top-level target id). Default 1.
#                Stable only as long as connection order/topology doesn't
#                change between runs.
#   BOARD_SERIAL exact jtag_cable_serial to pin a specific physical board
#                regardless of enumeration order (see the jtag_cable_serial
#                field of `targets -target-properties`, or the printout
#                this file makes on every run). Takes precedence over BOARD
#                if both are set.

proc board_select_serial {} {
    set boards [targets -target-properties -filter {name =~ "Versal*" && level==0}]
    if {[llength $boards] == 0} {
        error "board_select: no \"Versal*\" (level 0) targets found -- is hw_server connected to a board?"
    }
    set boards [lsort -command {apply {{a b} {expr {[dict get $a target_id] - [dict get $b target_id]}}}} $boards]

    if {[info exists ::env(BOARD_SERIAL)]} {
        set want $::env(BOARD_SERIAL)
        foreach b $boards {
            if {[dict get $b jtag_cable_serial] eq $want} {
                return $want
            }
        }
        set have {}
        foreach b $boards { lappend have [dict get $b jtag_cable_serial] }
        error "board_select: BOARD_SERIAL=$want not found among connected board(s): $have"
    }

    set idx 1
    if {[info exists ::env(BOARD)]} {
        set idx $::env(BOARD)
    }
    if {![string is integer -strict $idx] || $idx < 1 || $idx > [llength $boards]} {
        error "board_select: BOARD=$idx out of range -- found [llength $boards] board(s), valid range is 1-[llength $boards]"
    }
    return [dict get [lindex $boards [expr {$idx - 1}]] jtag_cable_serial]
}

set ::board_select_serial [board_select_serial]
puts "board_select: targeting board with jtag_cable_serial=$::board_select_serial"

# Drop-in replacement for `targets -set -filter {<name_filter>}` that scopes
# the match to the board resolved above. <name_filter> is a bare xsdb filter
# expression body, e.g. {name =~ "PMC"} or {name =~ "Versal*" && level==0}.
proc select_target {name_filter} {
    targets -set -filter "($name_filter) && jtag_cable_serial == \"$::board_select_serial\""
}
