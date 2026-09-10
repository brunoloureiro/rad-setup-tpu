"""
Resolves a JTAG probe's serial/UART bridge device (typically /dev/ttyUSB<n> on Linux, but anything
pyserial can enumerate on any platform) from a stable "JTAG ID" - the probe's own USB serial number
- instead of a raw device path. A literal path is not stable across reboots/re-enumerations: a
probe unplugged and replugged, or two probes enumerated in a different order than last time, can
silently swap which physical board ends up on /dev/ttyUSB1 vs /dev/ttyUSB2 (see the
machines_cfgs/versal1_*.yaml / versal2_*.yaml git history, previously hand-edited every time this
happened in the lab).

This is the same identifier already used to pin one physical Versal board in
machines_cfgs/versal_scripts/board_select.tcl ('jtag_cable_serial'/'BOARD_SERIAL'): the JTAG probes
used here expose that same value as their USB device serial number (visible via 'lsusb -v', udev's
ID_SERIAL_SHORT, or - as used below - pyserial's serial_number attribute), since the UART bridge
used for the console/message channel and the JTAG interface used by xsdb/hw_server live on the same
physical USB device (typically an FTDI FT2232H/FT4232H).
"""
import logging
import typing


def find_serial_port_by_id(jtag_id: str, logger: logging.Logger) -> typing.Optional[str]:
    """ Search every serial port pyserial currently sees for one whose USB serial number matches
    `jtag_id`, re-enumerating fresh on every call so a probe that moved to a different device node
    since the last lookup (e.g. after being unplugged/replugged, or after this or another probe's
    device node shifted) is still found.
    :return: the resolved device path (e.g. '/dev/ttyUSB2'), or None if no port currently matches
    """
    import serial.tools.list_ports as list_ports

    candidates = [p for p in list_ports.comports() if p.serial_number]
    matches = [p for p in candidates if p.serial_number == jtag_id]
    if not matches:
        # Some JTAG-probe UART bridges (e.g. FTDI FT2232H/FT4232H parts with a per-interface
        # serial suffix programmed into their EEPROM) report a serial_number that only starts
        # with - or is a prefix of - the id printed by board_select.tcl/lsusb for the whole
        # device. Fall back to that before giving up entirely.
        matches = [p for p in candidates
                  if p.serial_number.startswith(jtag_id) or jtag_id.startswith(p.serial_number)]

    if not matches:
        return None

    matches.sort(key=lambda p: p.device)
    if len(matches) > 1:
        logger.warning(
            f"Multiple serial ports match JTAG id '{jtag_id}': {[p.device for p in matches]} - "
            f"using {matches[0].device} (lowest device name). If this picks the wrong one, use an "
            f"explicit 'jtag_port'/'console_jtag_port' device path instead of an id.")
    return matches[0].device
