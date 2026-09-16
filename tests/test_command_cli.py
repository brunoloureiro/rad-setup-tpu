"""
Hermetic tests for command_cli.py: the pure parsing/resolution/help functions (no threads, no
stdin), plus an integration test class that drives a real InteractiveCommandCLI thread through a
fake stdin (an os.pipe(), so select.select() has a real, watchable file descriptor - the same
technique test_dut_connection.py's FakeSerial uses for a background "typist" thread) to exercise
the interactive multi-step prompting, cancel words, help, and stop() behavior end to end.
"""
import os
import sys
import time
import unittest

from server.command_cli import (CommandLineError, InteractiveCommandCLI, ParsedCommand,
                                describe_commands, describe_known_duts, parse_command_line,
                                resolve_machine)
from server.machine_commands import MachineCommand


class _StubMachine:
    """ Duck-types just enough of Machine's public surface (matches_dut_name/command/hostname)
    for resolve_machine() and InteractiveCommandCLI to work against, and records every dispatched
    command instead of actually touching any hardware. """

    def __init__(self, hostname: str):
        self.hostname = hostname
        self.cfg_basename = f"{hostname}.yaml"
        self.commands = []

    def matches_dut_name(self, name: str) -> bool:
        name = name.strip()
        stem = self.cfg_basename.removesuffix(".yaml")
        return name in (self.cfg_basename, stem, self.hostname)

    def command(self, name: str, **params) -> bool:
        if MachineCommand.from_string(name) is None:
            return False
        self.commands.append((name, params))
        return True


def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.02) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class ParseCommandLinePositionalTestCase(unittest.TestCase):
    def test_command_with_one_argument(self):
        result = parse_command_line("dut01 sleep 30")
        self.assertEqual(result, ParsedCommand(dut="dut01", command="sleep", params={"seconds": "30"}))

    def test_command_with_no_arguments(self):
        result = parse_command_line("dut01 power_cycle")
        self.assertEqual(result, ParsedCommand(dut="dut01", command="power_cycle", params={}))

    def test_bare_dut_name_is_a_partial_result_not_an_error(self):
        # A single token is treated as "just the dut name" - InteractiveCommandCLI then prompts
        # for the command interactively, rather than this being rejected outright.
        result = parse_command_line("dut01")
        self.assertEqual(result, ParsedCommand(dut="dut01", command=None, params={}))

    def test_missing_trailing_argument_is_partial_not_an_error(self):
        # "sleep" needs a 'seconds' argument that wasn't given - still not an error at parse time,
        # since InteractiveCommandCLI prompts for whatever required parameter is missing.
        result = parse_command_line("dut01 sleep")
        self.assertEqual(result, ParsedCommand(dut="dut01", command="sleep", params={}))

    def test_unknown_command_is_an_error(self):
        result = parse_command_line("dut01 not_a_real_command")
        self.assertIsInstance(result, CommandLineError)

    def test_too_many_arguments_is_an_error(self):
        result = parse_command_line("dut01 sleep 30 40")
        self.assertIsInstance(result, CommandLineError)


class ParseCommandLineFlagStyleTestCase(unittest.TestCase):
    def test_dut_and_command_and_param(self):
        result = parse_command_line("--dut dut01 --command switch_benchmark --benchmark example_cxx")
        self.assertEqual(result, ParsedCommand(dut="dut01", command="switch_benchmark",
                                               params={"benchmark": "example_cxx"}))

    def test_cmd_alias_accepted(self):
        result = parse_command_line("--dut dut01 --cmd power_cycle")
        self.assertEqual(result, ParsedCommand(dut="dut01", command="power_cycle", params={}))

    def test_missing_command_is_partial_not_an_error(self):
        result = parse_command_line("--dut dut01")
        self.assertEqual(result, ParsedCommand(dut="dut01", command=None, params={}))

    def test_missing_dut_is_partial_not_an_error(self):
        result = parse_command_line("--command power_cycle")
        self.assertEqual(result, ParsedCommand(dut=None, command="power_cycle", params={}))

    def test_unrecognized_flag_becomes_a_param_for_later_validation(self):
        # command_cli.py can't know whether a flag is "wrong" until a command is resolved (params
        # are command-specific) - see machine_commands.validate_command_params for where a typo
        # like this actually gets flagged as an unrecognized/ignored parameter.
        result = parse_command_line("--dutz dut01 --command power_cycle")
        self.assertEqual(result, ParsedCommand(dut=None, command="power_cycle", params={"dutz": "dut01"}))

    def test_flag_missing_value_is_an_error(self):
        result = parse_command_line("--dut dut01 --command")
        self.assertIsInstance(result, CommandLineError)

    def test_empty_flag_name_is_an_error(self):
        result = parse_command_line("-- dut01")
        self.assertIsInstance(result, CommandLineError)


class ParseCommandLineKeyValueStyleTestCase(unittest.TestCase):
    def test_dut_and_command_and_param(self):
        result = parse_command_line("dut=dut01 command=sleep seconds=30")
        self.assertEqual(result, ParsedCommand(dut="dut01", command="sleep", params={"seconds": "30"}))

    def test_cmd_alias_accepted(self):
        result = parse_command_line("dut=dut01 cmd=power_cycle")
        self.assertEqual(result, ParsedCommand(dut="dut01", command="power_cycle", params={}))

    def test_dut_only_is_partial_not_an_error(self):
        result = parse_command_line("dut=dut01")
        self.assertEqual(result, ParsedCommand(dut="dut01", command=None, params={}))

    def test_command_only_is_partial_not_an_error(self):
        result = parse_command_line("command=power_cycle")
        self.assertEqual(result, ParsedCommand(dut=None, command="power_cycle", params={}))


class ParseCommandLineMalformedInputTestCase(unittest.TestCase):
    def test_empty_line_is_an_error(self):
        result = parse_command_line("")
        self.assertIsInstance(result, CommandLineError)

    def test_whitespace_only_line_is_an_error(self):
        result = parse_command_line("   ")
        self.assertIsInstance(result, CommandLineError)

    def test_unbalanced_quotes_is_an_error_not_an_exception(self):
        # shlex.split raises ValueError on unbalanced quotes - must be reported, never propagate
        result = parse_command_line('dut01 sleep "30')
        self.assertIsInstance(result, CommandLineError)


class ResolveMachineTestCase(unittest.TestCase):
    def setUp(self):
        self.machines = [_StubMachine("host-alpha"), _StubMachine("host-beta")]

    def test_resolves_by_config_filename_with_extension(self):
        self.assertIs(resolve_machine("host-alpha.yaml", self.machines), self.machines[0])

    def test_resolves_by_config_filename_without_extension(self):
        self.assertIs(resolve_machine("host-alpha", self.machines), self.machines[0])

    def test_resolves_by_hostname_fallback(self):
        self.assertIs(resolve_machine("host-beta", self.machines), self.machines[1])

    def test_unknown_name_returns_none(self):
        self.assertIsNone(resolve_machine("no_such_dut", self.machines))


class DescribeHelpTextTestCase(unittest.TestCase):
    def test_describe_commands_lists_every_machine_command(self):
        text = describe_commands()
        for command in MachineCommand:
            self.assertIn(command.value, text)

    def test_describe_known_duts_lists_every_hostname(self):
        text = describe_known_duts([_StubMachine("host-alpha"), _StubMachine("host-beta")])
        self.assertIn("host-alpha", text)
        self.assertIn("host-beta", text)

    def test_describe_known_duts_empty_list(self):
        text = describe_known_duts([])
        self.assertIn("No machines", text)


class InteractiveCommandCLIIntegrationTestCase(unittest.TestCase):
    """ Drives a real InteractiveCommandCLI thread end to end through a piped fake stdin. """

    def setUp(self):
        read_fd, write_fd = os.pipe()
        self._write_fd = write_fd
        self._stdin_file = os.fdopen(read_fd, "r")
        self._orig_stdin = sys.stdin
        sys.stdin = self._stdin_file

        self.machine = _StubMachine("host-alpha")
        self.cli = InteractiveCommandCLI(machines=[self.machine], logger_name="TEST_CLI_INTEGRATION")
        self.cli.start()
        self.assertTrue(_wait_until(self.cli.is_alive))

    def tearDown(self):
        self.cli.stop()
        self.cli.join(timeout=2)
        sys.stdin = self._orig_stdin
        try:
            os.close(self._write_fd)
        except OSError:
            pass
        self._stdin_file.close()

    def _send(self, line: str) -> None:
        os.write(self._write_fd, (line + "\n").encode())

    def test_one_line_dispatch(self):
        self._send("host-alpha power_cycle")
        self.assertTrue(_wait_until(lambda: self.machine.commands))
        self.assertEqual(self.machine.commands, [("POWER_CYCLE", {})])

    def test_partial_dut_then_prompted_command_and_param(self):
        self._send("dut=host-alpha")
        self._send("sleep")
        self._send("45")
        self.assertTrue(_wait_until(lambda: self.machine.commands))
        self.assertEqual(self.machine.commands, [("SLEEP", {"seconds": "45"})])

    def test_invalid_param_value_is_reprompted(self):
        self._send("host-alpha sleep not_a_number")
        self._send("45")
        self.assertTrue(_wait_until(lambda: self.machine.commands))
        self.assertEqual(self.machine.commands, [("SLEEP", {"seconds": "45"})])

    def test_cancel_word_mid_command_prompt_aborts_and_cli_stays_usable(self):
        self._send("dut=host-alpha")
        self._send("cancel")
        # give the cancel a moment to be processed, then confirm nothing was dispatched
        time.sleep(0.3)
        self.assertEqual(self.machine.commands, [])
        # the CLI should still be responsive afterwards
        self._send("host-alpha power_cycle")
        self.assertTrue(_wait_until(lambda: self.machine.commands))

    def test_cancel_word_variants_all_abort(self):
        for word in ("q", "quit", "cancel", "exit"):
            self.machine.commands.clear()
            self._send("dut=host-alpha")
            self._send(word)
            time.sleep(0.2)
            self.assertEqual(self.machine.commands, [], f"cancel word {word!r} did not abort")

    def test_unknown_dut_does_not_dispatch_and_cli_stays_usable(self):
        self._send("no_such_dut power_cycle")
        time.sleep(0.3)
        self.assertEqual(self.machine.commands, [])
        self._send("host-alpha power_cycle")
        self.assertTrue(_wait_until(lambda: self.machine.commands))

    def test_malformed_line_does_not_crash_the_cli(self):
        self._send("--dut host-alpha --command")  # dangling flag with no value -> CommandLineError
        time.sleep(0.3)
        self.assertTrue(self.cli.is_alive())
        self._send("host-alpha power_cycle")
        self.assertTrue(_wait_until(lambda: self.machine.commands))

    def test_stop_takes_effect_promptly_even_mid_prompt(self):
        # Put the CLI into a sub-prompt (waiting for a command name), then stop it the same way
        # server.py's Ctrl+C handling would on the first press - it must not stay blocked.
        self._send("dut=host-alpha")
        time.sleep(0.2)
        started_at = time.time()
        self.cli.stop()
        self.cli.join(timeout=2)
        self.assertFalse(self.cli.is_alive())
        self.assertLess(time.time() - started_at, 2)


if __name__ == "__main__":
    unittest.main()
