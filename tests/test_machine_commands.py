"""
Hermetic tests for machine_commands.py - pure dispatcher logic, no I/O, no threads. Mirrors
test_dut_commands.py's role for the reverse-direction (operator -> Machine) command channel.
"""
import unittest

from server.machine_commands import (COMMAND_HELP, COMMAND_PARAM_NAMES, COMMAND_PARAMS,
                                     MachineCommand, MachineCommandDispatcher,
                                     validate_command_params)


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

    def test_every_command_has_a_help_entry(self):
        for command in MachineCommand:
            self.assertIn(command, COMMAND_HELP)
            self.assertTrue(COMMAND_HELP[command])

    def test_command_param_names_matches_command_params(self):
        for command, specs in COMMAND_PARAMS.items():
            self.assertEqual(COMMAND_PARAM_NAMES[command], tuple(spec.name for spec in specs))


class ValidateCommandParamsTestCase(unittest.TestCase):
    def test_no_params_expected_and_none_given_is_fully_valid(self):
        result = validate_command_params(MachineCommand.POWER_CYCLE, {})
        self.assertEqual(result.values, {})
        self.assertEqual(result.missing_or_invalid, {})
        self.assertEqual(result.warnings, [])

    def test_missing_required_param_is_reported(self):
        result = validate_command_params(MachineCommand.SLEEP, {})
        self.assertEqual(result.missing_or_invalid, {"seconds": "missing"})
        self.assertEqual(result.values, {})

    def test_valid_param_is_normalized_into_values(self):
        result = validate_command_params(MachineCommand.SLEEP, {"seconds": "30"})
        self.assertEqual(result.values, {"seconds": 30.0})
        self.assertEqual(result.missing_or_invalid, {})

    def test_non_numeric_seconds_is_invalid_not_missing(self):
        result = validate_command_params(MachineCommand.SLEEP, {"seconds": "not_a_number"})
        self.assertIn("seconds", result.missing_or_invalid)
        self.assertNotEqual(result.missing_or_invalid["seconds"], "missing")

    def test_negative_seconds_is_invalid(self):
        result = validate_command_params(MachineCommand.SLEEP, {"seconds": "-5"})
        self.assertIn("seconds", result.missing_or_invalid)

    def test_empty_benchmark_is_invalid(self):
        result = validate_command_params(MachineCommand.SWITCH_BENCHMARK, {"benchmark": "   "})
        self.assertIn("benchmark", result.missing_or_invalid)

    def test_unrecognized_param_produces_a_warning_and_is_excluded_from_values(self):
        result = validate_command_params(MachineCommand.SLEEP, {"seconds": "30", "bogus": "1"})
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("bogus", result.warnings[0])
        self.assertNotIn("bogus", result.values)

    def test_never_raises_on_command_with_no_params_table_entry(self):
        # Defensive: even a command somehow missing from COMMAND_PARAMS must not raise
        result = validate_command_params(MachineCommand.SOFT_REBOOT, {"unexpected": "1"})
        self.assertEqual(result.missing_or_invalid, {})
        self.assertEqual(len(result.warnings), 1)


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
