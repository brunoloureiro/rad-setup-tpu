"""
Hermetic tests for Machine's Monitor wiring (the 'monitor:' YAML field, resolved against
enabled_monitors.py's MONITORS registry - see machine.py's __start_monitor and OPERATOR_COMMANDS.md, "Monitor
thread API"). Like test_machine_operator_commands.py, this builds real Machine instances from
temp YAML configs using connection_type: ethernet, and calls the private __start_monitor directly
(via name mangling) rather than run()/start() - run() also powers the DUT on, waits for boot, and
performs the initial app (re)start, none of which are hermetically testable without real
hardware. __start_monitor is what actually implements the "never crash on a bad/unknown monitor
name" contract this file exists to check, so it is exercised directly.
"""
import os
import shutil
import tempfile
import threading
import unittest

import yaml

from server.logger_formatter import logging_setup
from server.machine import Machine
from server.monitors.periodic_reboot_monitor import PeriodicRebootMonitor

_JSON_FILES = [os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "machines_cfgs", "dummy.json"))]


class MachineMonitorTestCase(unittest.TestCase):
    def setUp(self):
        logging_setup(logger_name="TEST_MACHINE_MONITOR", log_file="unit_test_log_MachineMonitor.log",
                     enable_curses=False)
        self.tmp_dir = tempfile.mkdtemp()
        self.server_log_path = os.path.join(self.tmp_dir, "logs")
        os.mkdir(self.server_log_path)
        self._machines_to_stop = []

    def tearDown(self):
        for machine in self._machines_to_stop:
            machine.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _build_machine(self, monitor_value) -> Machine:
        cfg_path = os.path.join(self.tmp_dir, "dut01.yaml")
        with open(cfg_path, "w") as fp:
            yaml.safe_dump({
                "hostname": "host-alpha",
                "ip": "127.0.0.1",
                "power_switch_ip": "127.0.0.1",
                "power_switch_port": 1,
                "power_switch_model": "lindy",
                "boot_waiting_time": 5,
                "max_timeout_time": 5,
                "connection_type": "ethernet",
                "receive_port": 0,
                "dut_mode": "active",
                "username": "carol",
                "password": "qwerty0",
                "json_files": _JSON_FILES,
                "monitor": monitor_value,
            }, fp)
        machine = Machine(configuration_file=cfg_path, server_ip="127.0.0.1",
                          logger_name="TEST_MACHINE_MONITOR", server_log_path=self.server_log_path)
        self._machines_to_stop.append(machine)
        return machine

    def test_no_monitor_field_does_not_raise(self):
        machine = self._build_machine(monitor_value=None)
        machine._Machine__start_monitor()  # must be a no-op, never raise

    def test_unknown_monitor_name_does_not_raise(self):
        machine = self._build_machine(monitor_value="not_a_real_monitor")
        machine._Machine__start_monitor()  # must log an error and return, never raise

    def test_known_monitor_name_spawns_a_thread_without_raising(self):
        machine = self._build_machine(monitor_value="periodic_reboot")
        machine._Machine__start_monitor()

        try:
            self.assertTrue(any(isinstance(t, PeriodicRebootMonitor) for t in threading.enumerate()))
        finally:
            # Signal shutdown immediately - PeriodicRebootMonitor's default 180s interval is
            # never actually waited out, since it wakes as soon as the shared stop_event is set.
            machine.stop()


if __name__ == "__main__":
    unittest.main()
