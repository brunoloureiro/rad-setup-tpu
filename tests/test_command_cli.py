"""
Hermetic tests for command_cli.py's parsing/resolution logic - no threads, no stdin, no real
Machine objects (resolve_machine only needs something with a matches_dut_name() method, so a
tiny stub stands in for Machine here).
"""
import unittest

from server.command_cli import CommandLineError, ParsedCommand, parse_command_line, resolve_machine


class _StubMachine:
    def __init__(self, cfg_basename: str, hostname: str):
        self.cfg_basename = cfg_basename
        self.hostname = hostname

    def matches_dut_name(self, name: str) -> bool:
        name = name.strip()
        stem = self.cfg_basename.removesuffix(".yaml")
        if name in (self.cfg_basename, stem):
            return True
        return name == self.hostname


class ParseCommandLinePositionalTestCase(unittest.TestCase):
    def test_command_with_one_argument(self):
        result = parse_command_line("dut01 sleep 30")
        self.assertEqual(result, ParsedCommand(dut="dut01", command="sleep", params={"seconds": "30"}))

    def test_command_with_no_arguments(self):
        result = parse_command_line("dut01 power_cycle")
        self.assertEqual(result, ParsedCommand(dut="dut01", command="power_cycle", params={}))

    def test_too_few_tokens_is_an_error(self):
        result = parse_command_line("justoneword")
        self.assertIsInstance(result, CommandLineError)

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

    def test_missing_command_is_an_error(self):
        result = parse_command_line("--dut dut01")
        self.assertIsInstance(result, CommandLineError)

    def test_flag_missing_value_is_an_error(self):
        result = parse_command_line("--dut dut01 --command")
        self.assertIsInstance(result, CommandLineError)


class ParseCommandLineKeyValueStyleTestCase(unittest.TestCase):
    def test_dut_and_command_and_param(self):
        result = parse_command_line("dut=dut01 command=sleep seconds=30")
        self.assertEqual(result, ParsedCommand(dut="dut01", command="sleep", params={"seconds": "30"}))

    def test_cmd_alias_accepted(self):
        result = parse_command_line("dut=dut01 cmd=power_cycle")
        self.assertEqual(result, ParsedCommand(dut="dut01", command="power_cycle", params={}))

    def test_missing_dut_is_an_error(self):
        result = parse_command_line("command=power_cycle")
        self.assertIsInstance(result, CommandLineError)


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
        self.machines = [
            _StubMachine(cfg_basename="dut01.yaml", hostname="host-alpha"),
            _StubMachine(cfg_basename="dut02.yaml", hostname="host-beta"),
        ]

    def test_resolves_by_config_filename_with_extension(self):
        self.assertIs(resolve_machine("dut01.yaml", self.machines), self.machines[0])

    def test_resolves_by_config_filename_without_extension(self):
        self.assertIs(resolve_machine("dut01", self.machines), self.machines[0])

    def test_resolves_by_hostname_fallback(self):
        self.assertIs(resolve_machine("host-beta", self.machines), self.machines[1])

    def test_unknown_name_returns_none(self):
        self.assertIsNone(resolve_machine("no_such_dut", self.machines))


if __name__ == "__main__":
    unittest.main()
