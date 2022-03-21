import unittest
import os
import time

from server.logger_formatter import logging_setup
from server.machine import reboot_machine

class RebootMachineTestCase(unittest.TestCase):
    def test_reboot_machine(self):
        logger = logging_setup(logger_name="REBOOT_MACHINE_LOG", log_file="unit_test_log_RebootMachine.log")
        logger.debug("Debugging reboot machine")

        reboot = reboot_machine(address="192.168.1.11", switch_model="lindy", switch_port=1,
                                switch_ip="192.168.1.100", rebooting_sleep=10, logger_name="REBOOT_MACHINE_LOG")
        logger.debug(f"Reboot status OFF={reboot[0]} ON={reboot[1]}")

        turn_machine_on(address="192.168.1.11", switch_model="default", switch_port=1, switch_ip="192.168.1.100",
                        logger_name="REBOOT_MACHINE_LOG")

        self.assertEqual(reboot[0], ErrorCodes.SUCCESS)
        self.assertEqual(reboot[1], ErrorCodes.SUCCESS)


if __name__ == '__main__':
    unittest.main()
