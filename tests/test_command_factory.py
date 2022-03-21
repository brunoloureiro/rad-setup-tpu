import time
import unittest

from server.command_factory import CommandFactory
from server.logger_formatter import logging_setup


class CommandFactoryTestCase(unittest.TestCase):
    def test_command_factory(self):
        logger = logging_setup(logger_name="COMMAND_FACTORY", log_file="unit_test_log_CommandFactory.log")
        logger.debug("DEBUGGING THE COMMAND FACTORY")
        logger.debug("CREATING THE MACHINE")
        command_factory = CommandFactory(json_files_list=["machines_cfgs/cuda_micro.json"],
                                         logger_name="COMMAND_FACTORY",
                                         command_window=5)
        logger.debug("Executing command factory")
        first = command_factory.get_commands_and_test_info()[0]
        sec = first
        for it in range(20):
            time.sleep(2)
            sec = command_factory.get_commands_and_test_info()[0]
            if first == sec:
                logger.debug(f"-------- IT {it} EQUAL AGAIN ----------------")
        time.sleep(10)
        self.assertEqual(True, first != sec and command_factory.is_command_window_timed_out)  # add assertion here


if __name__ == '__main__':
    unittest.main()
