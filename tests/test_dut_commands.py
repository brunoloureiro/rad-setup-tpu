import unittest

from server.dut_commands import DUTCommand, DUTCommandDispatcher
from server.logger_formatter import logging_setup


class DUTCommandsTestCase(unittest.TestCase):
    def setUp(self):
        logging_setup(logger_name="DUT_COMMANDS", log_file="unit_test_log_DUTCommands.log", enable_curses=False)
        self.dispatcher = DUTCommandDispatcher(logger_name="DUT_COMMANDS")
        self.received = list()
        self.dispatcher.register(DUTCommand.HARD_REBOOT, lambda args: self.received.append(("HARD_REBOOT", args)))
        self.dispatcher.register(DUTCommand.SOFT_REBOOT, lambda args: self.received.append(("SOFT_REBOOT", args)))

    def test_known_command_is_dispatched(self):
        handled = self.dispatcher.dispatch("HARD_REBOOT")
        self.assertTrue(handled)
        self.assertEqual([("HARD_REBOOT", "")], self.received)

    def test_command_with_trailing_args_is_dispatched(self):
        handled = self.dispatcher.dispatch("SOFT_REBOOT now please")
        self.assertTrue(handled)
        self.assertEqual([("SOFT_REBOOT", "now please")], self.received)

    def test_unknown_command_is_not_dispatched(self):
        handled = self.dispatcher.dispatch("REFORMAT_DISK")
        self.assertFalse(handled)
        self.assertEqual([], self.received)

    def test_registered_command_without_handler_is_not_dispatched(self):
        handled = DUTCommandDispatcher(logger_name="DUT_COMMANDS").dispatch("HARD_REBOOT")
        self.assertFalse(handled)


if __name__ == '__main__':
    unittest.main()
