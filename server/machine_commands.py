"""
Operator-initiated commands directed at one specific Machine - the reverse direction of
dut_commands.py's DUT -> server '#CMD' channel: an operator (via the interactive CLI in
command_cli.py, or a per-machine Monitor thread - see OPERATOR_COMMANDS.md) tells one running
Machine to do something on demand, instead of only reacting to what the DUT itself sends.

Kept deliberately as a closed, static enum + registered-handler dispatcher, never an arbitrary
shell/eval, so that operator input - free-form CLI text, or a third-party Monitor implementation -
can never reach further than a fixed, known set of actions (see CLAUDE.md's "the server must
never crash" prime directive). Adding a new command is meant to stay an additive, two-step
change: add a MachineCommand member (plus its ParamSpecs in COMMAND_PARAMS below, if it takes
any), then dispatcher.register(...) a handler in Machine.__init__ - nothing else needs to change.

COMMAND_PARAMS/validate_command_params below are the single source of truth for each command's
*generic* parameter syntax (names, and simple format checks like "is this a positive number") -
shared by command_cli.py, so an operator gets immediate, specific feedback ("missing", "invalid",
"ignoring an unrecognized parameter") while still typing, instead of only finding out from a
warning buried in the server log after the fact. This is deliberately separate from *semantic*,
DUT-specific validation (e.g. "is this actually one of this DUT's configured benchmark
codenames"), which has no meaning outside of one specific Machine's own state and so stays in
that Machine's own handler (see machine.py's __on_operator_switch_benchmark).
"""
import enum
import logging
import typing


class MachineCommand(enum.Enum):
    # Restart the app without power cycling (console kill+run for active DUTs, redeploy_cmd for
    # passive ones) - same underlying action as DUTCommand.SOFT_REBOOT, just operator-triggered.
    # No parameters. Not every DUT can actually complete one on request (e.g. the console is
    # unreachable, or this machine already hit its MAX_SEQUENTIALLY_SOFT_APP_REBOOTS ceiling) -
    # the handler logs a warning and otherwise does nothing in that case; it never raises.
    SOFT_REBOOT = "SOFT_REBOOT"
    # Force an immediate hard power cycle + app restart, bypassing normal timeout escalation.
    # No parameters. ("now" is implied - there is no delayed/scheduled variant.)
    POWER_CYCLE = "POWER_CYCLE"
    # Pause this machine's timeout-based reboot escalation for a given duration. Does not touch
    # the DUT itself, and does not stop message logging - only suppresses the soft/hard reboot
    # escalation that would otherwise trigger on a receive() timeout while paused.
    # Parameters: seconds (positive number).
    SLEEP = "SLEEP"
    # Switch the currently-running benchmark to the one matching this codename (one of the
    # 'codename' entries across this DUT's configured json_files), then restart the app to apply
    # it. Only meaningful for a DUT configured with json_files (CommandFactory).
    # Parameters: benchmark (a codename string).
    SWITCH_BENCHMARK = "SWITCH_BENCHMARK"

    @classmethod
    def from_string(cls, name: str) -> typing.Optional["MachineCommand"]:
        try:
            return cls(name.strip().upper())
        except (ValueError, AttributeError):
            return None

    def __str__(self) -> str:
        return self.value


# One-line descriptions shown by the CLI's help/list-commands output (see command_cli.py's
# describe_commands()).
COMMAND_HELP: typing.Dict[MachineCommand, str] = {
    MachineCommand.SOFT_REBOOT: "Restart the app without power cycling (console kill+run, or "
                                "redeploy_cmd for passive DUTs).",
    MachineCommand.POWER_CYCLE: "Immediately hard power-cycle the DUT and restart the app.",
    MachineCommand.SLEEP: "Pause this DUT's timeout-based reboot escalation for a duration.",
    MachineCommand.SWITCH_BENCHMARK: "Switch to a different benchmark (by codename) and restart "
                                     "the app to apply it.",
}


class ParamValidationError(ValueError):
    """ Raised by a ParamSpec.validate function to reject a parameter's raw string value; the
    message is shown directly to the operator (CLI) or logged as-is (a handler), so it should be
    a short, human-readable reason - e.g. "must be a positive number", not a stack trace. """


def _validate_positive_number(raw_value: str) -> float:
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        raise ParamValidationError(f"must be a number, got {raw_value!r}")
    if value <= 0:
        raise ParamValidationError(f"must be positive, got {raw_value!r}")
    return value


def _validate_nonempty_string(raw_value: str) -> str:
    if not raw_value or not raw_value.strip():
        raise ParamValidationError("must not be empty")
    return raw_value


class ParamSpec(typing.NamedTuple):
    name: str
    # Parses/checks the raw string value, returning a normalized value or raising
    # ParamValidationError - see _validate_positive_number/_validate_nonempty_string above.
    validate: typing.Callable[[str], typing.Any]
    # One-line, human-readable description of what's expected, e.g. "a positive number of
    # seconds" - shown by the CLI when prompting for this parameter.
    hint: str


# Every command's expected parameters, in the order the CLI's positional syntax maps them (e.g.
# "dut01 sleep 30" becomes {"seconds": "30"}) - see validate_command_params below for how these
# are actually checked. This is generic, DUT-agnostic *syntax* validation only (is this even a
# well-formed value at all) - see this module's docstring for why semantic/DUT-specific checks
# (e.g. "is this a benchmark codename this DUT actually has") live in Machine's own handlers
# instead.
COMMAND_PARAMS: typing.Dict[MachineCommand, typing.Tuple[ParamSpec, ...]] = {
    MachineCommand.SOFT_REBOOT: (),
    MachineCommand.POWER_CYCLE: (),
    MachineCommand.SLEEP: (
        ParamSpec("seconds", _validate_positive_number, "a positive number of seconds"),
    ),
    MachineCommand.SWITCH_BENCHMARK: (
        ParamSpec("benchmark", _validate_nonempty_string, "a benchmark codename (non-empty)"),
    ),
}

# Just the ordered names from COMMAND_PARAMS above - kept as its own table since it's what
# command_cli.py's positional syntax and tests reach for most often.
COMMAND_PARAM_NAMES: typing.Dict[MachineCommand, typing.Tuple[str, ...]] = {
    command: tuple(spec.name for spec in specs) for command, specs in COMMAND_PARAMS.items()
}


class ParamValidationResult(typing.NamedTuple):
    # Recognized parameters that validated successfully, normalized (e.g. "30" -> 30.0) - mostly
    # useful for callers that want the parsed value; command_cli.py itself still forwards the
    # original raw strings to Machine.command(), since that is what every handler already expects.
    values: typing.Dict[str, typing.Any]
    # name -> reason, for every expected parameter that is either absent from `params` or present
    # but failed its ParamSpec.validate - the caller should prompt for/report each of these.
    missing_or_invalid: typing.Dict[str, str]
    # Human-readable warnings about parameters in `params` that this command doesn't expect at
    # all - informational only, never blocks anything.
    warnings: typing.List[str]


def validate_command_params(command: MachineCommand, params: typing.Dict[str, str]) -> ParamValidationResult:
    """ Check `params` against `command`'s ParamSpecs (see COMMAND_PARAMS above). Never raises -
    every problem is reported through the returned ParamValidationResult instead. """
    specs = COMMAND_PARAMS.get(command, ())
    expected_names = {spec.name for spec in specs}
    values: typing.Dict[str, typing.Any] = dict()
    missing_or_invalid: typing.Dict[str, str] = dict()

    for spec in specs:
        if spec.name not in params or params[spec.name] == "":
            missing_or_invalid[spec.name] = "missing"
            continue
        try:
            values[spec.name] = spec.validate(params[spec.name])
        except ParamValidationError as e:
            missing_or_invalid[spec.name] = str(e)

    warnings = [f"ignoring unrecognized parameter '{name}={value}'"
               for name, value in params.items() if name not in expected_names]

    return ParamValidationResult(values=values, missing_or_invalid=missing_or_invalid, warnings=warnings)


# A handler receives this command's parameters (raw strings, as parsed off the CLI/monitor - e.g.
# {"seconds": "30"}) and performs the requested action; like DUTCommandHandler in dut_commands.py,
# it is expected to validate its own parameters and do its own error handling/logging.
MachineCommandHandler = typing.Callable[[typing.Dict[str, str]], None]


class MachineCommandDispatcher:
    """ Registry mapping MachineCommand members to handlers, used by Machine.command().

    Always invoked from the owning Machine's own thread (see Machine.__drain_operator_commands) -
    never directly from whichever thread called Machine.command() (the CLI's input thread, or
    eventually a Monitor thread) - so handlers can safely touch this Machine's own state the same
    way run() itself does, without any extra locking.
    """

    def __init__(self, logger_name: str):
        self.__logger = logging.getLogger(f"{logger_name}.{__name__}")
        self.__handlers: typing.Dict[MachineCommand, MachineCommandHandler] = dict()

    def register(self, command: MachineCommand, handler: MachineCommandHandler) -> None:
        """ Register (or replace) the handler executed when `command` is requested """
        self.__handlers[command] = handler

    def dispatch(self, command: MachineCommand, params: typing.Dict[str, str]) -> bool:
        """ Execute the registered handler for `command`, if any.
        :param command: the command to execute
        :param params: command-specific parameters, e.g. {"seconds": "30"}
        :return: True if a registered handler was executed, False otherwise
        """
        if command not in self.__handlers:
            self.__logger.warning(f"No handler registered for operator command {command} - ignoring")
            return False

        self.__logger.info(f"Executing operator-requested command {command} params={params}")
        try:
            self.__handlers[command](params)
        except Exception as e:
            # Operator commands are less-trusted input (parsed from free-form CLI text, or
            # eventually a third-party Monitor implementation) than the rest of this codebase's
            # internal call paths - this is a deliberate extra backstop, on top of each handler
            # doing its own validation, so a handler bug can never escape into the Machine thread
            # and trip threading.excepthook (see CLAUDE.md's prime directive).
            self.__logger.exception(f"Operator command {command} handler raised an exception - ignoring: {e}")
            return False
        return True
