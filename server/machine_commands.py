"""
Operator-initiated commands directed at one specific Machine - the reverse direction of
dut_commands.py's DUT -> server '#CMD' channel: an operator (via the interactive CLI in
command_cli.py, or eventually a per-machine Monitor thread - see TODO.md, "Operator -> Machine
command interface") tells one running Machine to do something on demand, instead of only reacting
to what the DUT itself sends.

Kept deliberately as a closed, static enum + registered-handler dispatcher, never an arbitrary
shell/eval, so that operator input - free-form CLI text, or eventually a third-party Monitor
implementation - can never reach further than a fixed, known set of actions (see CLAUDE.md's
"the server must never crash" prime directive). Adding a new command is meant to stay an
additive, two-step change: add a MachineCommand member (plus its expected parameter names in
COMMAND_PARAM_NAMES below), then dispatcher.register(...) a handler in Machine.__init__ - nothing
else needs to change.
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


# Ordered parameter names expected by each command, used only by command_cli.py's positional
# syntax to map "<dut> <command> <arg1> [arg2 ...]" onto named params (e.g. "dut01 sleep 30"
# becomes {"seconds": "30"}). The flag-style (--seconds 30) and key=value (seconds=30) CLI
# syntaxes name their parameters explicitly and don't consult this table - it also just documents
# what each command expects. Actual type/range validation of parameter values happens in each
# command's handler (see Machine's __on_operator_* methods), not here.
COMMAND_PARAM_NAMES: typing.Dict[MachineCommand, typing.Tuple[str, ...]] = {
    MachineCommand.SOFT_REBOOT: (),
    MachineCommand.POWER_CYCLE: (),
    MachineCommand.SLEEP: ("seconds",),
    MachineCommand.SWITCH_BENCHMARK: ("benchmark",),
}


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
