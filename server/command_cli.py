"""
Interactive CLI for issuing operator commands (see machine_commands.py) at a running Machine, by
typing a line naming a DUT, a command, and the command's parameters - see TODO.md, "Operator ->
Machine command interface".

Three equivalent line syntaxes are accepted, all normalizing to the same (dut, command, params)
triple before dispatch:
    <dut_name> <command> <arg1> [arg2 ...]        (positional)
    --dut <dut_name> --command <command> --<param> <value> ...   (flag-style, --cmd also accepted)
    dut=<dut_name> command=<command> <param>=<value> ...          (key=value, cmd= also accepted)

Any parse failure (unknown syntax, unknown command, wrong argument count, unbalanced quoting, ...)
is reported back as a CommandLineError - it must never raise, since this reads free-form text
typed by an operator (see CLAUDE.md's "the server must never crash" prime directive). Actual
per-command parameter validation (e.g. that SLEEP's 'seconds' is a positive number) happens later,
in the target Machine's own command handler - this module only concerns itself with syntax.
"""
import logging
import shlex
import threading
import typing

from .machine_commands import COMMAND_PARAM_NAMES, MachineCommand


class ParsedCommand(typing.NamedTuple):
    dut: str
    command: str
    params: typing.Dict[str, str]


class CommandLineError(typing.NamedTuple):
    message: str


ParseResult = typing.Union[ParsedCommand, CommandLineError]

# Aliases accepted in place of "command"/"--command" in key=value/flag-style syntax
_COMMAND_KEY_ALIASES = ("command", "cmd")


def parse_command_line(line: str) -> ParseResult:
    """ Parse one operator command line into a (dut, command, params) triple, or a
    CommandLineError describing why it could not be parsed. Never raises. """
    try:
        tokens = shlex.split(line)
    except ValueError as e:
        # e.g. unbalanced quotes
        return CommandLineError(f"could not tokenize command line: {e}")

    if not tokens:
        return CommandLineError("empty command line")

    if any(token.startswith("--") for token in tokens):
        return _parse_flag_style(tokens)
    if any("=" in token for token in tokens):
        return _parse_key_value_style(tokens)
    return _parse_positional_style(tokens)


def _parse_key_value_style(tokens: typing.List[str]) -> ParseResult:
    params: typing.Dict[str, str] = dict()
    for token in tokens:
        if "=" not in token:
            return CommandLineError(f"expected 'key=value', got '{token}'")
        key, _, value = token.partition("=")
        key = key.strip().lower()
        if not key:
            return CommandLineError(f"missing key in '{token}'")
        params[key] = value

    dut = params.pop("dut", None)
    command = None
    for alias in _COMMAND_KEY_ALIASES:
        if alias in params:
            value = params.pop(alias)
            if command is None:
                command = value
    if not dut or not command:
        return CommandLineError("key=value syntax requires 'dut=<name>' and 'command=<cmd>' (or 'cmd=<cmd>')")
    return ParsedCommand(dut=dut, command=command, params=params)


def _parse_flag_style(tokens: typing.List[str]) -> ParseResult:
    params: typing.Dict[str, str] = dict()
    dut = None
    command = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if not token.startswith("--"):
            return CommandLineError(f"expected a '--flag', got '{token}'")
        key = token[2:].strip().lower()
        if not key:
            return CommandLineError(f"empty flag name in '{token}'")
        if i + 1 >= len(tokens):
            return CommandLineError(f"flag '--{key}' is missing its value")
        value = tokens[i + 1]
        i += 2
        if key == "dut":
            dut = value
        elif key in _COMMAND_KEY_ALIASES:
            command = value
        else:
            params[key] = value

    if not dut or not command:
        return CommandLineError("flag syntax requires '--dut <name>' and '--command <cmd>' (or '--cmd <cmd>')")
    return ParsedCommand(dut=dut, command=command, params=params)


def _parse_positional_style(tokens: typing.List[str]) -> ParseResult:
    if len(tokens) < 2:
        return CommandLineError("positional syntax requires at least '<dut_name> <command>'")
    dut, command, *rest = tokens

    command_enum = MachineCommand.from_string(command)
    if command_enum is None:
        return CommandLineError(f"unknown command '{command}'")

    expected_params = COMMAND_PARAM_NAMES[command_enum]
    if len(rest) > len(expected_params):
        return CommandLineError(
            f"command '{command}' takes at most {len(expected_params)} argument(s) "
            f"({', '.join(expected_params) or 'none'}), got {len(rest)}")
    return ParsedCommand(dut=dut, command=command, params=dict(zip(expected_params, rest)))


def resolve_machine(dut_name: str, machines: typing.Iterable[typing.Any]) -> typing.Optional[typing.Any]:
    """ Find the Machine in `machines` identified by `dut_name`, per each Machine's own
    matches_dut_name() (config filename first, hostname fallback - see machine.py). Returns None,
    never raises, if no/multiple ambiguous machines match; ambiguity is intentionally not
    distinguished from "no match" here since either way there is no single machine to target. """
    matches = [m for m in machines if m.matches_dut_name(dut_name)]
    if len(matches) != 1:
        return None
    return matches[0]


class InteractiveCommandCLI(threading.Thread):
    """ Reads operator command lines from stdin, one per line, parses them (see
    parse_command_line above), resolves the target DUT (see resolve_machine above), and hands the
    command off to that Machine's own Machine.command(...) - see TODO.md, "Operator -> Machine
    command interface".

    Only meaningful in plain (non-curses) mode: curses.initscr() takes over the terminal display,
    which is not compatible with a concurrent blocking input() loop reading the same terminal (the
    same "only one reader" problem already documented for serial ports in serial_tee.py) - so
    --enable_curses runs do not start this thread at all (see server.py). A curses-integrated
    input line is a possible follow-up, not implemented here.

    This is a daemon thread with no graceful stop: input() blocks on stdin and cannot be
    interrupted by a threading.Event the way Machine's own loops are, so - like
    ConsoleCursesManager's underlying curses loop - it is simply abandoned at process exit rather
    than joined. It never raises out of run(): a malformed line, an unknown DUT, or an unknown
    command are all just logged as a warning and dropped (see CLAUDE.md's prime directive).
    """

    def __init__(self, machines: typing.List[typing.Any], logger_name: str, *args, **kwargs):
        self.__machines = machines
        self.__logger = logging.getLogger(f"{logger_name}.{__name__}")
        kwargs.setdefault("daemon", True)
        super().__init__(*args, **kwargs)

    def run(self) -> None:
        self.__logger.info("Interactive operator command CLI ready (dut=<name> command=<cmd> ...)")
        while True:
            try:
                line = input()
            except EOFError:
                # stdin closed (e.g. no attached tty) - nothing left for this thread to do
                return
            except Exception as e:
                self.__logger.exception(f"Unexpected error reading operator command input: {e}")
                continue
            self.__handle_line(line)

    def __handle_line(self, line: str) -> None:
        if not line.strip():
            return

        result = parse_command_line(line)
        if isinstance(result, CommandLineError):
            self.__logger.warning(f"Could not parse operator command '{line}': {result.message}")
            return

        machine = resolve_machine(result.dut, self.__machines)
        if machine is None:
            self.__logger.warning(f"Operator command '{line}' references unknown/ambiguous dut "
                                  f"'{result.dut}' - ignoring")
            return

        machine.command(result.command, **result.params)
