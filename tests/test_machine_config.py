"""
Hermetic tests for Machine's config validation around the console_type axis (Telnet vs JTAG
console for dut_mode: active DUTs, in MachineConsoleTypeConfigTestCase) and the connection_type
axis's jtag_id alternative to a literal jtag_port (in MachineConnectionTypeJtagConfigTestCase).
Unlike test_machine.py, these never call Machine.run()/start() or touch real hardware:
MachineConsoleTypeConfigTestCase uses connection_type: ethernet (an in-process UDP socket on an
OS-assigned ephemeral port) so Machine.__init__ never opens a console itself (that only happens
later, from run()/__wait_for_booting/__soft_app_reboot); MachineConnectionTypeJtagConfigTestCase
uses connection_type: jtag with a port/id that is never actually available, exercising
JTAGMessageChannel.open()'s "must not raise, ever" contract (see dut_message_channel.py).
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import yaml

from server.logger_formatter import logging_setup
from server.machine import Machine

_JSON_FILES = [os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "machines_cfgs", "dummy.json"))]


class MachineConsoleTypeConfigTestCase(unittest.TestCase):
    def setUp(self):
        logging_setup(logger_name="TEST_MACHINE_CONSOLE_TYPE", log_file="unit_test_log_MachineConsoleType.log",
                     enable_curses=False)
        self.tmp_dir = tempfile.mkdtemp()
        self.server_log_path = os.path.join(self.tmp_dir, "logs")
        os.mkdir(self.server_log_path)
        self._machines_to_stop = []

    def tearDown(self):
        for machine in self._machines_to_stop:
            machine.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_cfg(self, name: str, overrides: dict) -> str:
        base = {
            "hostname": name,
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
        }
        base.update(overrides)
        cfg_path = os.path.join(self.tmp_dir, f"{name}.yaml")
        with open(cfg_path, "w") as fp:
            yaml.safe_dump(base, fp)
        return cfg_path

    def _build_machine(self, name: str, overrides: dict) -> Machine:
        cfg_path = self._write_cfg(name, overrides)
        machine = Machine(configuration_file=cfg_path, server_ip="127.0.0.1",
                          logger_name="TEST_MACHINE_CONSOLE_TYPE", server_log_path=self.server_log_path)
        self._machines_to_stop.append(machine)
        return machine

    def test_default_console_type_is_telnet_and_requires_ip(self):
        with self.assertRaises(ValueError):
            self._write_and_build_without_stop_tracking("no_ip", {})

    def _write_and_build_without_stop_tracking(self, name, overrides):
        # Helper for cases expected to raise before a Machine object (and its message channel)
        # ever gets created, so there is nothing to stop() in tearDown.
        cfg_path = self._write_cfg(name, overrides)
        return Machine(configuration_file=cfg_path, server_ip="127.0.0.1",
                       logger_name="TEST_MACHINE_CONSOLE_TYPE", server_log_path=self.server_log_path)

    def test_telnet_console_with_ip_succeeds(self):
        machine = self._build_machine("telnet_ok", {"ip": "192.168.1.50"})
        self.assertIn("CONSOLE:telnet", str(machine))
        self.assertNotIn("CONSOLE_JTAGPORT", str(machine))

    def test_jtag_console_does_not_require_ip(self):
        machine = self._build_machine("jtag_no_ip", {
            "console_type": "jtag",
            "console_jtag_port": "/dev/ttyFAKE_CONSOLE",
        })
        self.assertIn("CONSOLE:jtag", str(machine))
        self.assertIn("CONSOLE_JTAGPORT:/dev/ttyFAKE_CONSOLE", str(machine))

    def test_jtag_console_still_requires_username_and_password(self):
        with self.assertRaises(ValueError):
            self._write_and_build_without_stop_tracking("jtag_no_creds", {
                "console_type": "jtag",
                "console_jtag_port": "/dev/ttyFAKE_CONSOLE",
                "username": None,
                "password": None,
            })

    def test_jtag_console_without_port_raises(self):
        with self.assertRaises(ValueError):
            self._write_and_build_without_stop_tracking("jtag_no_port", {"console_type": "jtag"})

    def test_unsupported_console_type_raises(self):
        with self.assertRaises(ValueError):
            self._write_and_build_without_stop_tracking("bad_console_type", {"console_type": "ssh"})

    def test_jtag_console_baudrate_defaults_when_omitted(self):
        # No exception, and the default baud rate is applied silently - exercised indirectly via
        # successful construction (console_jtag_baudrate has no public getter, and__str__ does not
        # surface it, so absence of a raise is the observable contract here).
        machine = self._build_machine("jtag_default_baud", {
            "console_type": "jtag",
            "console_jtag_port": "/dev/ttyFAKE_CONSOLE",
        })
        self.assertIn("CONSOLE:jtag", str(machine))

    def test_passive_dut_ignores_console_type_entirely(self):
        # console_type is only meaningful for dut_mode: active - a passive DUT never opens a
        # console at all, so an otherwise-invalid-looking console_type/no console_jtag_port
        # combination must not raise for it.
        machine = self._build_machine("passive_ignores_console", {
            "dut_mode": "passive",
            "redeploy_cmd": ["/bin/true"],
            "test_name": "passive_dummy",
            "console_type": "jtag",
        })
        self.assertIn("HOSTNAME:passive_ignores_console", str(machine))

    def test_jtag_console_accepts_console_jtag_id_instead_of_port(self):
        machine = self._build_machine("jtag_console_id", {
            "console_type": "jtag",
            "console_jtag_id": "PROBE_SERIAL_XYZ",
        })
        self.assertIn("CONSOLE:jtag", str(machine))
        self.assertIn("CONSOLE_JTAGID:PROBE_SERIAL_XYZ", str(machine))
        self.assertNotIn("CONSOLE_JTAGPORT", str(machine))

    def test_jtag_console_without_port_or_id_raises(self):
        with self.assertRaises(ValueError):
            self._write_and_build_without_stop_tracking("jtag_no_port_or_id", {"console_type": "jtag"})


class MachineConnectionTypeJtagConfigTestCase(unittest.TestCase):
    """ Hermetic tests for the connection_type: jtag axis's config validation and its jtag_id
    alternative to a literal jtag_port. Unlike ethernet's in-process UDP socket, opening a JTAG
    serial channel can no longer fail Machine construction even when the port/id is not available
    (see JTAGMessageChannel.open()) - that is exactly the behavior under test here, since a Machine
    thread failing to construct used to take down the entire server (see server.py's main()). """

    def setUp(self):
        logging_setup(logger_name="TEST_MACHINE_CONNECTION_TYPE_JTAG",
                     log_file="unit_test_log_MachineConnectionTypeJtag.log", enable_curses=False)
        self.tmp_dir = tempfile.mkdtemp()
        self.server_log_path = os.path.join(self.tmp_dir, "logs")
        os.mkdir(self.server_log_path)
        self._machines_to_stop = []

    def tearDown(self):
        for machine in self._machines_to_stop:
            machine.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_cfg(self, name: str, overrides: dict) -> str:
        base = {
            "hostname": name,
            "power_switch_ip": "127.0.0.1",
            "power_switch_port": 1,
            "power_switch_model": "lindy",
            "boot_waiting_time": 1,
            "max_timeout_time": 1,
            "connection_type": "jtag",
            "dut_mode": "passive",
            "redeploy_cmd": ["/bin/true"],
            "test_name": name,
        }
        base.update(overrides)
        cfg_path = os.path.join(self.tmp_dir, f"{name}.yaml")
        with open(cfg_path, "w") as fp:
            yaml.safe_dump(base, fp)
        return cfg_path

    def _build_machine(self, name: str, overrides: dict):
        from server.machine import Machine
        cfg_path = self._write_cfg(name, overrides)
        machine = Machine(configuration_file=cfg_path, server_ip="127.0.0.1",
                          logger_name="TEST_MACHINE_CONNECTION_TYPE_JTAG",
                          server_log_path=self.server_log_path)
        self._machines_to_stop.append(machine)
        return machine

    def test_connection_type_jtag_without_port_or_id_raises(self):
        with self.assertRaises(ValueError):
            self._build_machine("jtag_conn_no_port_or_id", {})

    def test_connection_type_jtag_accepts_jtag_id_instead_of_port(self):
        machine = self._build_machine("jtag_conn_id", {"jtag_id": "PROBE_SERIAL_MSG"})
        self.assertIn("JTAGID:PROBE_SERIAL_MSG", str(machine))
        self.assertNotIn("JTAGPORT", str(machine))

    def test_construction_does_not_raise_when_jtag_port_is_missing_at_startup(self):
        # This is the core "server must start even if a jtag/serial port cannot be opened right
        # away" fix - Machine.__init__ previously called MessageChannel.open() eagerly and let a
        # missing port's exception propagate all the way out (crashing every Machine in the
        # server, not just this one - see server.py's main()).
        machine = self._build_machine("jtag_conn_missing_port", {
            "jtag_port": "/dev/ttyDOES_NOT_EXIST_MACHINE_STARTUP",
        })
        self.assertIn("JTAGPORT:/dev/ttyDOES_NOT_EXIST_MACHINE_STARTUP", str(machine))

    def test_construction_does_not_raise_when_jtag_id_is_unresolved_at_startup(self):
        with mock.patch("serial.tools.list_ports.comports", return_value=[]):
            machine = self._build_machine("jtag_conn_missing_id", {"jtag_id": "NOT_PLUGGED_IN_YET"})
        self.assertIn("JTAGID:NOT_PLUGGED_IN_YET", str(machine))


if __name__ == '__main__':
    unittest.main()
