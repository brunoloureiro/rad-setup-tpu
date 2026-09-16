"""
Hermetic tests for Machine's operator-command surface (matches_dut_name/command - see
machine_commands.py/command_cli.py/TODO.md, "Operator -> Machine command interface"). Like
MachineConsoleTypeConfigTestCase in test_machine_config.py, this builds real Machine instances
from temp YAML configs using connection_type: ethernet (an in-process UDP socket on an
OS-assigned ephemeral port) - Machine.__init__ never opens a console itself, and these Machines
are never .run()/.start()'d, so no real hardware or network peer is needed.
"""
import os
import shutil
import tempfile
import unittest

import yaml

from server.logger_formatter import logging_setup
from server.machine import Machine

_JSON_FILES = [os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "machines_cfgs", "dummy.json"))]


class MachineOperatorCommandsTestCase(unittest.TestCase):
    def setUp(self):
        logging_setup(logger_name="TEST_MACHINE_OPERATOR_COMMANDS",
                     log_file="unit_test_log_MachineOperatorCommands.log", enable_curses=False)
        self.tmp_dir = tempfile.mkdtemp()
        self.server_log_path = os.path.join(self.tmp_dir, "logs")
        os.mkdir(self.server_log_path)

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
            }, fp)

        self.machine = Machine(configuration_file=cfg_path, server_ip="127.0.0.1",
                               logger_name="TEST_MACHINE_OPERATOR_COMMANDS",
                               server_log_path=self.server_log_path)

    def tearDown(self):
        self.machine.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_matches_dut_name_by_config_filename_with_extension(self):
        self.assertTrue(self.machine.matches_dut_name("dut01.yaml"))

    def test_matches_dut_name_by_config_filename_without_extension(self):
        self.assertTrue(self.machine.matches_dut_name("dut01"))

    def test_matches_dut_name_by_hostname_fallback(self):
        self.assertTrue(self.machine.matches_dut_name("host-alpha"))

    def test_matches_dut_name_rejects_unknown_name(self):
        self.assertFalse(self.machine.matches_dut_name("no-such-dut"))

    def test_command_accepts_known_command_case_insensitively(self):
        self.assertTrue(self.machine.command("sleep", seconds="30"))
        self.assertTrue(self.machine.command("SWITCH_BENCHMARK", benchmark="example_cxx"))

    def test_command_rejects_unknown_command_without_raising(self):
        self.assertFalse(self.machine.command("not_a_real_command"))


if __name__ == "__main__":
    unittest.main()
