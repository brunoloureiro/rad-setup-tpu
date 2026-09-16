"""
Registry of Monitor implementations selectable per-DUT via the 'monitor:' field in a machine's
YAML config - see OPERATOR_COMMANDS.md, "Operator -> Machine command interface" / "Monitor thread API". This
is the one file to edit to plug in a custom Monitor: write your Monitor subclass in its own file
under server/monitors/, import it below, and register it under whatever name DUT configs should
use for 'monitor: <name>'.

Each import+registration is wrapped in its own try/except, so a broken custom monitor module
(bad import, syntax error, whatever) can never prevent the server from starting for every other
DUT - see CLAUDE.md's prime directive. This only ever runs once, at server startup (this module
is imported by machine.py), so the failure blast radius of one bad import here is small and
contained to "that one monitor name is simply unavailable", never "the server won't start".

A name registered twice keeps whichever registration happened first and logs a warning about the
second - it never silently overwrites, and it never raises.
"""
import logging
import typing

from .base import Monitor

_logger = logging.getLogger(__name__)

MONITORS: typing.Dict[str, typing.Type[Monitor]] = dict()


def _register(name: str, monitor_cls: typing.Type[Monitor]) -> None:
    if name in MONITORS:
        _logger.warning(f"Duplicate monitor name '{name}' ({monitor_cls}) - keeping the first "
                        f"registration ({MONITORS[name]}) and ignoring this one")
        return
    MONITORS[name] = monitor_cls


try:
    from .periodic_reboot_monitor import PeriodicRebootMonitor
    _register("periodic_reboot", PeriodicRebootMonitor)
except Exception:
    _logger.exception("Failed to import/register the built-in 'periodic_reboot' monitor - "
                      "it will be unavailable, but the server will still start")

# Add your own custom monitors below, each guarded the same way as above, e.g.:
#
# try:
#     from .my_monitor import MyMonitor
#     _register("my_monitor", MyMonitor)
# except Exception:
#     _logger.exception("Failed to import/register 'my_monitor' - it will be unavailable")
