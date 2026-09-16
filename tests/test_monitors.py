"""
Hermetic tests for server/monitors/ - the base Monitor class's log-access API, the built-in
PeriodicRebootMonitor, and enabled_monitors.py's registry (import isolation / duplicate
handling). No real Machine, no threads other than the Monitor's own, no hardware.
"""
import os
import tempfile
import threading
import time
import unittest

from server.monitors import enabled_monitors
from server.monitors.base import Monitor
from server.monitors.periodic_reboot_monitor import PeriodicRebootMonitor


class _RecordingMonitor(Monitor):
    """ A no-op Monitor, just to exercise the base class's own methods directly """

    def run(self) -> None:
        pass


class MonitorBaseTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.calls = []
        self.current_log_path = None
        self.monitor = _RecordingMonitor(
            command_callback=lambda name, **params: self.calls.append((name, params)) or True,
            log_dir=self.tmp_dir, current_log_file=lambda: self.current_log_path,
            hostname="test-dut", logger_name="TEST_MONITOR_BASE", stop_event=threading.Event())

    def test_log_files_lists_every_log_in_log_dir(self):
        open(os.path.join(self.tmp_dir, "a.log"), "w").close()
        open(os.path.join(self.tmp_dir, "b.log"), "w").close()
        open(os.path.join(self.tmp_dir, "not_a_log.txt"), "w").close()

        files = [os.path.basename(p) for p in self.monitor.log_files()]

        self.assertEqual(sorted(files), ["a.log", "b.log"])

    def test_log_files_empty_dir_returns_empty_list(self):
        self.assertEqual(self.monitor.log_files(), [])

    def test_current_log_file_reflects_the_callback(self):
        self.assertIsNone(self.monitor.current_log_file())
        self.current_log_path = os.path.join(self.tmp_dir, "running.log")
        self.assertEqual(self.monitor.current_log_file(), self.current_log_path)

    def test_command_callback_is_forwarded(self):
        self.monitor._command("POWER_CYCLE", extra="1")
        self.assertEqual(self.calls, [("POWER_CYCLE", {"extra": "1"})])


class PeriodicRebootMonitorTestCase(unittest.TestCase):
    def test_fires_power_cycle_on_the_configured_interval(self):
        calls = []
        stop_event = threading.Event()
        monitor = PeriodicRebootMonitor(
            command_callback=lambda name, **params: calls.append((name, params)),
            log_dir="/tmp", current_log_file=lambda: None, hostname="test-dut",
            logger_name="TEST_PERIODIC_REBOOT_MONITOR", stop_event=stop_event,
            interval_seconds=0.05)

        monitor.start()
        try:
            deadline = time.time() + 2
            while len(calls) < 2 and time.time() < deadline:
                time.sleep(0.01)
        finally:
            stop_event.set()
            monitor.join(timeout=2)

        self.assertFalse(monitor.is_alive())
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(all(call == ("POWER_CYCLE", {}) for call in calls))

    def test_stops_promptly_without_waiting_out_the_interval(self):
        stop_event = threading.Event()
        monitor = PeriodicRebootMonitor(
            command_callback=lambda name, **params: None, log_dir="/tmp",
            current_log_file=lambda: None, hostname="test-dut",
            logger_name="TEST_PERIODIC_REBOOT_MONITOR", stop_event=stop_event,
            interval_seconds=180)

        monitor.start()
        started_at = time.time()
        stop_event.set()
        monitor.join(timeout=2)
        elapsed = time.time() - started_at

        self.assertFalse(monitor.is_alive())
        self.assertLess(elapsed, 2)


class EnabledMonitorsRegistryTestCase(unittest.TestCase):
    def test_built_in_periodic_reboot_monitor_is_registered(self):
        self.assertIs(enabled_monitors.MONITORS.get("periodic_reboot"), PeriodicRebootMonitor)

    def test_register_keeps_first_and_warns_on_duplicate(self):
        registry_backup = dict(enabled_monitors.MONITORS)
        try:
            enabled_monitors.MONITORS.clear()
            enabled_monitors.MONITORS.update(registry_backup)

            class _First(Monitor):
                def run(self):
                    pass

            class _Second(Monitor):
                def run(self):
                    pass

            enabled_monitors._register("dup_name", _First)
            enabled_monitors._register("dup_name", _Second)

            self.assertIs(enabled_monitors.MONITORS["dup_name"], _First)
        finally:
            enabled_monitors.MONITORS.clear()
            enabled_monitors.MONITORS.update(registry_backup)


if __name__ == "__main__":
    unittest.main()
