import unittest

from server.logger_formatter import logging_setup
from server.reboot_machine import reboot_machine, turn_machine_on, turn_machine_off
from server.error_codes import ErrorCodes


class RebootMachineTestCase(unittest.TestCase):
    def test_reboot_machine(self):
        import threading
        logger = logging_setup(logger_name="REBOOT_MACHINE_LOG", log_file="unit_test_log_RebootMachine.log")
        logger.debug("Debugging reboot machine")

        reboot = reboot_machine(address="192.168.1.42", switch_model="lindy", switch_port=1,
                                switch_ip="192.168.1.120", rebooting_sleep=10, logger_name="REBOOT_MACHINE_LOG",
                                thread_event=threading.Event())
        logger.debug(f"Reboot status OFF={reboot[0]} ON={reboot[1]}")

        off_status = turn_machine_off(address="192.168.1.42", switch_model="lindy", switch_port=1,
                                      switch_ip="192.168.1.120", logger_name="REBOOT_MACHINE_LOG")

        self.assertEqual(reboot[0], ErrorCodes.SUCCESS)
        self.assertEqual(reboot[1], ErrorCodes.SUCCESS)
        self.assertEqual(off_status, ErrorCodes.SUCCESS)


if __name__ == '__main__':
    unittest.main()
