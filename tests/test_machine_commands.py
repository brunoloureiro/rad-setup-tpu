"""
Hermetic tests for machine_commands.py - pure dispatcher logic, no I/O, no threads. Mirrors
test_dut_commands.py's role for the reverse-direction (operator -> Machine) command channel.
"""
import unittest

from server.machine_commands import COMMAND_PARAM_NAMES, MachineCommand, MachineCommandDispatcher


class MachineCommandTestCase(unittest.TestCase):
    def test_from_string_is_case_insensitive(self):
        self.assertEqual(MachineCommand.from_string("sleep"), MachineCommand.SLEEP)
        self.assertEqual(MachineCommand.from_string("SLEEP"), MachineCommand.SLEEP)
        self.assertEqual(MachineCommand.from_string("  sleep  "), MachineCommand.SLEEP)

    def test_from_string_recognizes_soft_and_hard_reboot(self):
        self.assertEqual(MachineCommand.from_string("soft_reboot"), MachineCommand.SOFT_REBOOT)
        self.assertEqual(MachineCommand.from_string("power_cycle"), MachineCommand.POWER_CYCLE)

    def test_from_string_unknown_returns_none(self):
        self.assertIsNone(MachineCommand.from_string("not_a_real_command"))
        self.assertIsNone(MachineCommand.from_string(""))

    def test_every_command_has_param_names_entry(self):
        for command in MachineCommand:
            self.assertIn(command, COMMAND_PARAM_NAMES)


class MachineCommandDispatcherTestCase(unittest.TestCase):
    def setUp(self):
        self.dispatcher = MachineCommandDispatcher(logger_name="TEST_MACHINE_COMMAND_DISPATCHER")

    def test_dispatch_runs_registered_handler_with_params(self):
        received = []
        self.dispatcher.register(MachineCommand.SLEEP, lambda params: received.append(params))

        result = self.dispatcher.dispatch(MachineCommand.SLEEP, {"seconds": "5"})

        self.assertTrue(result)
        self.assertEqual(received, [{"seconds": "5"}])

    def test_dispatch_unregistered_command_returns_false_without_raising(self):
        result = self.dispatcher.dispatch(MachineCommand.POWER_CYCLE, {})
        self.assertFalse(result)

    def test_dispatch_swallows_handler_exception(self):
        def raising_handler(params):
            raise RuntimeError("boom")

        self.dispatcher.register(MachineCommand.POWER_CYCLE, raising_handler)

        # Must never raise out of dispatch() - a handler bug must not be able to escape into the
        # Machine thread and trip threading.excepthook (see CLAUDE.md's prime directive).
        result = self.dispatcher.dispatch(MachineCommand.POWER_CYCLE, {})
        self.assertFalse(result)

    def test_register_replaces_existing_handler(self):
        calls = []
        self.dispatcher.register(MachineCommand.POWER_CYCLE, lambda params: calls.append("first"))
        self.dispatcher.register(MachineCommand.POWER_CYCLE, lambda params: calls.append("second"))

        self.dispatcher.dispatch(MachineCommand.POWER_CYCLE, {})

        self.assertEqual(calls, ["second"])


if __name__ == "__main__":
    unittest.main()
