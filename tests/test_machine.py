import os
import time
import unittest

from server.logger_formatter import logging_setup
from server.machine import Machine


class MachineTestCase(unittest.TestCase):
    def test_machine(self):
        logger = logging_setup(logger_name="MACHINE_LOG", log_file="unit_test_log_Machine.log")
        logger.debug("DEBUGGING THE MACHINE")
        server_log_path = "logs"
        if os.path.isdir(server_log_path) is False:
            os.mkdir(server_log_path)
        machine = Machine(
            configuration_file="machines_cfgs/carolk401.yaml",
            server_ip="131.254.160.174",
            logger_name="MACHINE_LOG",
            server_log_path=server_log_path
        )

        logger.debug("EXECUTING THE MACHINE")
        machine.start()
        logger.debug(f"SLEEPING THE MACHINE FOR {200}s")
        time.sleep(500)

        logger.debug("JOINING THE MACHINE")
        machine.stop()
        machine.join()
        logger.debug("RAGE AGAINST THE MACHINE")
        self.assertEqual(machine.is_alive(), False)  # add assertion here


if __name__ == '__main__':
    unittest.main()
