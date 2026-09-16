"""
Example Monitor: unconditionally issues a POWER_CYCLE command to its own Machine on a fixed
interval (default every 3 minutes) - see TODO.md, "Operator -> Machine command interface". The
timer is purely internal to this Monitor - Machine/run() know nothing about it, and this Monitor
never touches Machine state directly, only ever through command_callback (see base.py), exactly
like any other Monitor implementation would.

Registered under the name 'periodic_reboot' in enabled_monitors.py - select it per-DUT with
'monitor: periodic_reboot' in that machine's YAML config.
"""
from .base import Monitor

_DEFAULT_INTERVAL_SECONDS = 180.0  # 3 minutes


class PeriodicRebootMonitor(Monitor):
    def __init__(self, *args, interval_seconds: float = _DEFAULT_INTERVAL_SECONDS, **kwargs):
        super().__init__(*args, **kwargs)
        self.__interval_seconds = interval_seconds

    def run(self) -> None:
        self._logger.info(f"PeriodicRebootMonitor started on {self._hostname}: requesting a "
                          f"POWER_CYCLE every {self.__interval_seconds}s")
        while not self._stop_event.is_set():
            # wait() returns True as soon as the event is set, so shutdown is prompt rather than
            # having to wait out the rest of the interval (see Machine.stop(), which sets the
            # very same stop_event this Monitor was constructed with).
            if self._stop_event.wait(self.__interval_seconds):
                return
            self._logger.info(f"PeriodicRebootMonitor requesting POWER_CYCLE on {self._hostname}")
            self._command("POWER_CYCLE")
