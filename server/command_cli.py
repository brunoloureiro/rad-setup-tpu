"""
Interactive CLI for issuing operator commands (see machine_commands.py) at a running Machine, by
typing a line naming a DUT, a command, and the command's parameters - see OPERATOR_COMMANDS.md,
"Operator -> Machine command interface".

Three equivalent line syntaxes are accepted, all normalizing to the same (dut, command, params)
triple before dispatch:
    <dut_name> <command> <arg1> [arg2 ...]        (positional)
    --dut <dut_name> --command <command> --<param> <value> ...   (flag-style, --cmd also accepted)
    dut=<dut_name> command=<command> <param>=<value> ...          (key=value, cmd= also accepted)

Any of dut/command/a required parameter may be left out of the line entirely - e.g. just typing
'dut=dut01' - in which case InteractiveCommandCLI interactively prompts for whatever is still
missing (showing the available commands/DUTs/a parameter's expected format as it goes), rather
than rejecting the line outright. A CommandLineError is only returned for an actual *syntax*
problem (unbalanced quoting, an explicitly-given but unrecognized command, too many positional
arguments, ...) - never merely for something being absent. It must never raise, since this reads
free-form text typed by an operator (see CLAUDE.md's "the server must never crash" prime
directive).

At any prompt (the initial line, or a dut/command/parameter follow-up prompt), typing one of
'q'/'quit'/'cancel'/'exit' (case-insensitive) abandons whatever command entry is currently in
progress and returns to a fresh prompt - these words are reserved and always take that meaning,
even if they happen to collide with a DUT's own name. 'help'/'?' shows context-appropriate help
(the full command list, the current parameter's expected format, or the list of known DUTs)
without cancelling anything.
"""
import logging
import os
import select
import shlex
import sys
import threading
import typing

from .machine_commands import (COMMAND_HELP, COMMAND_PARAM_NAMES, COMMAND_PARAMS, MachineCommand,
                               ParamSpec, ParamValidationError, validate_command_params)


class ParsedCommand(typing.NamedTuple):
    # dut/command come back as None when the line simply didn't supply them - see this module's
    # docstring; InteractiveCommandCLI is what fills those in interactively.
    dut: typing.Optional[str]
    command: typing.Optional[str]
    params: typing.Dict[str, str]


class CommandLineError(typing.NamedTuple):
    message: str


ParseResult = typing.Union[ParsedCommand, CommandLineError]

# Aliases accepted in place of "command"/"--command" in key=value/flag-style syntax
_COMMAND_KEY_ALIASES = ("command", "cmd")

# Reserved words recognized at every prompt - see this module's docstring. Checked
# case-insensitively, always before any DUT/command name lookup, so they take precedence over a
# same-named DUT or command (there is currently no command actually named any of these).
_CANCEL_WORDS = {"q", "quit", "cancel", "exit"}
_HELP_WORDS = {"help", "?"}

# How often InteractiveCommandCLI's input-polling loop re-checks its stop flag - this is the
# upper bound on how long stop() takes to actually end run() (e.g. after the first Ctrl+C - see
# server.py), since a plain blocking input()/readline() call could otherwise block indefinitely.
_READ_POLL_INTERVAL_SECONDS = 0.2


def parse_command_line(line: str) -> ParseResult:
    """ Parse one operator command line into a (dut, command, params) triple - dut and/or command
    come back as None if the line didn't supply them (see this module's docstring). Never raises. """
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

    return ParsedCommand(dut=dut, command=command, params=params)


def _parse_positional_style(tokens: typing.List[str]) -> ParseResult:
    dut = tokens[0]
    command = tokens[1] if len(tokens) > 1 else None
    rest = tokens[2:]
    params: typing.Dict[str, str] = dict()

    if command is not None:
        command_enum = MachineCommand.from_string(command)
        if command_enum is None:
            return CommandLineError(f"unknown command '{command}'")
        expected_params = COMMAND_PARAM_NAMES[command_enum]
        if len(rest) > len(expected_params):
            return CommandLineError(
                f"command '{command}' takes at most {len(expected_params)} argument(s) "
                f"({', '.join(expected_params) or 'none'}), got {len(rest)}")
        # Fewer args than expected is fine - InteractiveCommandCLI prompts for whatever is
        # missing, same as an omitted key=value/--flag pair.
        params = dict(zip(expected_params, rest))

    return ParsedCommand(dut=dut, command=command, params=params)


def resolve_machine(dut_name: str, machines: typing.Iterable[typing.Any]) -> typing.Optional[typing.Any]:
    """ Find the Machine in `machines` identified by `dut_name`, per each Machine's own
    matches_dut_name() (config filename first, hostname fallback - see machine.py). Returns None,
    never raises, if no/multiple ambiguous machines match; ambiguity is intentionally not
    distinguished from "no match" here since either way there is no single machine to target. """
    matches = [m for m in machines if m.matches_dut_name(dut_name)]
    if len(matches) != 1:
        return None
    return matches[0]


def describe_commands() -> str:
    """ One line per MachineCommand: its name, expected parameters, and a short description -
    shown by the CLI's 'help'/'?' and whenever it prompts for a command. """
    lines = ["Available commands:"]
    for command in MachineCommand:
        param_names = COMMAND_PARAM_NAMES[command]
        param_str = " ".join(f"<{name}>" for name in param_names) if param_names else "(no parameters)"
        lines.append(f"  {command.value:<16} {param_str:<24} {COMMAND_HELP.get(command, '')}")
    return "\n".join(lines)


def describe_known_duts(machines: typing.Iterable[typing.Any]) -> str:
    """ Comma-separated list of every known DUT's hostname - shown while prompting for a dut. """
    names = sorted(getattr(machine, "hostname", str(machine)) for machine in machines)
    if not names:
        return "No machines are configured."
    return "Known DUTs: " + ", ".join(names)


class InteractiveCommandCLI(threading.Thread):
    """ Reads operator command lines from stdin, one per line, parses them (see
    parse_command_line above), interactively prompts for anything the line left out, resolves
    the target DUT (see resolve_machine above), and hands the command off to that Machine's own
    Machine.command(...) - see OPERATOR_COMMANDS.md, "Operator -> Machine command interface".

    Only meaningful in plain (non-curses) mode: curses.initscr() takes over the terminal display,
    which is not compatible with this CLI's own stdin reading (the same "only one reader" problem
    already documented for serial ports in serial_tee.py) - so --enable_curses runs do not start
    this thread at all (see server.py). A curses-integrated input line is a possible follow-up,
    not implemented here.

    Reads stdin via __read_line's short-poll loop rather than a plain blocking input(), so stop()
    (e.g. called from server.py's Ctrl+C handling, on the first press - see the module docstring
    for the reserved cancel/help words a *typed* line can also use) takes effect within about
    _READ_POLL_INTERVAL_SECONDS instead of only after the operator's next keystroke. This thread
    never raises out of run(): every step (parsing, prompting, validation, dispatch) is wrapped so
    a bug in any of it stays contained to a log line, exactly like MachineCommandDispatcher's own
    backstop - see CLAUDE.md's prime directive.
    """

    def __init__(self, machines: typing.List[typing.Any], logger_name: str, *args, **kwargs):
        self.__machines = machines
        self.__logger = logging.getLogger(f"{logger_name}.{__name__}")
        self.__stop_event = threading.Event()
        # Raw bytes already pulled off stdin but not yet split into a complete line - see
        # __read_line's docstring for why this can't just be sys.stdin.readline().
        self.__stdin_buffer = b""
        kwargs.setdefault("daemon", True)
        super().__init__(*args, **kwargs)

    def stop(self) -> None:
        """ Ask this CLI to exit run() at the next opportunity (within _READ_POLL_INTERVAL_SECONDS)
        - affects only this thread, never the server or any Machine. """
        self.__stop_event.set()

    def run(self) -> None:
        self.__write(f"Interactive operator command CLI ready. Type 'help' for the command list, "
                    f"or {'/'.join(sorted(_CANCEL_WORDS))} to cancel mid-entry.")
        while not self.__stop_event.is_set():
            try:
                self.__run_one_iteration()
            except Exception as e:
                # Any bug in this thread's own parsing/prompting/validation logic must stay
                # contained here, never propagate out of run() and trip threading.excepthook -
                # see CLAUDE.md's prime directive.
                self.__logger.exception(f"Unexpected error in the interactive CLI - ignoring: {e}")
        self.__write("Interactive CLI stopped (server keeps running).")

    def __run_one_iteration(self) -> None:
        line = self.__read_line("> ")
        if line is None:
            self.__stop_event.set()  # EOF/unreadable stdin - nothing left for this thread to do
            return
        stripped = line.strip()
        if not stripped:
            return
        lowered = stripped.lower()
        if lowered in _HELP_WORDS:
            self.__write(describe_commands())
            return
        if lowered in _CANCEL_WORDS:
            self.__write("Nothing to cancel.")
            return
        self.__handle_line(line)

    def __handle_line(self, line: str) -> None:
        result = parse_command_line(line)
        if isinstance(result, CommandLineError):
            self.__write(f"[!] {result.message}")
            return

        dut_name = result.dut
        if dut_name is None:
            dut_name = self.__prompt_for_dut()
            if dut_name is None:
                return

        machine = resolve_machine(dut_name, self.__machines)
        if machine is None:
            self.__write(f"[!] Unknown/ambiguous dut '{dut_name}'. {describe_known_duts(self.__machines)}")
            return

        command_name = result.command
        if command_name is None:
            self.__write(describe_commands())
            command_name = self.__prompt_for_command()
            if command_name is None:
                return

        command = MachineCommand.from_string(command_name)
        if command is None:
            self.__write(f"[!] Unknown command '{command_name}'.")
            return

        params = self.__collect_params(command, result.params)
        if params is None:
            return

        machine.command(command.value, **params)
        self.__write(f"Queued {command.value} for '{dut_name}'.")

    def __collect_params(self, command: MachineCommand,
                         params: typing.Dict[str, str]) -> typing.Optional[typing.Dict[str, str]]:
        """ Warn about any unrecognized parameter already in `params`, then interactively prompt
        for whichever expected parameter is missing or was given an invalid value, until every
        one is satisfied or the operator cancels. Returns the final raw-string params to forward
        to Machine.command(), or None if cancelled. """
        validation = validate_command_params(command, params)
        for warning in validation.warnings:
            self.__write(f"[!] {warning}")

        collected = {name: params[name] for name in COMMAND_PARAM_NAMES[command]
                    if name not in validation.missing_or_invalid}

        for spec in COMMAND_PARAMS.get(command, ()):
            if spec.name not in validation.missing_or_invalid:
                continue
            reason = validation.missing_or_invalid[spec.name]
            if reason != "missing":
                self.__write(f"[!] parameter '{spec.name}' is invalid: {reason}")
            value = self.__prompt_for_param(command, spec)
            if value is None:
                return None
            collected[spec.name] = value

        return collected

    def __prompt_for_dut(self) -> typing.Optional[str]:
        while True:
            line = self.__read_line("dut> ")
            if line is None:
                return None
            stripped = line.strip()
            lowered = stripped.lower()
            if lowered in _CANCEL_WORDS:
                self.__write("Cancelled.")
                return None
            if lowered in _HELP_WORDS:
                self.__write(describe_known_duts(self.__machines))
                continue
            if not stripped:
                continue
            return stripped

    def __prompt_for_command(self) -> typing.Optional[str]:
        while True:
            line = self.__read_line("command> ")
            if line is None:
                return None
            stripped = line.strip()
            lowered = stripped.lower()
            if lowered in _CANCEL_WORDS:
                self.__write("Cancelled.")
                return None
            if lowered in _HELP_WORDS:
                self.__write(describe_commands())
                continue
            if not stripped:
                continue
            if MachineCommand.from_string(stripped) is None:
                self.__write(f"[!] Unknown command '{stripped}'.")
                self.__write(describe_commands())
                continue
            return stripped

    def __prompt_for_param(self, command: MachineCommand, spec: ParamSpec) -> typing.Optional[str]:
        while True:
            line = self.__read_line(f"{command.value} {spec.name}> ")
            if line is None:
                return None
            stripped = line.strip()
            lowered = stripped.lower()
            if lowered in _CANCEL_WORDS:
                self.__write("Cancelled.")
                return None
            if lowered in _HELP_WORDS:
                self.__write(f"{spec.name}: {spec.hint}")
                continue
            if not stripped:
                continue
            try:
                spec.validate(stripped)
            except ParamValidationError as e:
                self.__write(f"[!] invalid value for '{spec.name}': {e}")
                continue
            return stripped

    def __read_line(self, prompt: str) -> typing.Optional[str]:
        """ Print `prompt` once, then poll stdin for a line, checking self.__stop_event between
        polls instead of blocking on it indefinitely - see _READ_POLL_INTERVAL_SECONDS. Returns
        None on stop()/EOF/an unreadable stdin - every caller treats all three the same way
        (abandon whatever prompt is in progress).

        Deliberately reads the raw fd via os.read() into self.__stdin_buffer and splits lines
        off that buffer itself, rather than calling sys.stdin.readline() once select() reports
        the fd ready: a buffered TextIOWrapper's readline() can silently pull every byte
        currently sitting in the OS pipe/tty buffer into its own internal buffer on a single
        call (e.g. several lines typed/piped in close together) - after that, select() on the
        raw fd correctly reports "nothing new", even though readline() would still happily return
        the next already-buffered line without blocking at all. Managing the buffer here avoids
        that mismatch entirely. """
        print(prompt, end="", flush=True)
        try:
            fd = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            # e.g. stdin has no usable fileno for select() - fall back to one plain blocking read
            # rather than looping forever; this CLI is best-effort input handling and must never
            # crash the server over an input quirk (see CLAUDE.md's prime directive).
            try:
                raw_line = sys.stdin.readline()
            except Exception:
                return None
            return raw_line.rstrip("\n") if raw_line else None

        while not self.__stop_event.is_set():
            newline_index = self.__stdin_buffer.find(b"\n")
            if newline_index != -1:
                line = self.__stdin_buffer[:newline_index]
                self.__stdin_buffer = self.__stdin_buffer[newline_index + 1:]
                return line.decode(errors="replace")
            try:
                ready, _, _ = select.select([fd], [], [], _READ_POLL_INTERVAL_SECONDS)
                if not ready:
                    continue
                chunk = os.read(fd, 4096)
            except OSError:
                return None
            if chunk == b"":
                return None  # EOF
            self.__stdin_buffer += chunk
        return None

    def __write(self, text: str) -> None:
        print(text)
        self.__logger.info(text)
