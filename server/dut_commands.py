"""
DUT-initiated remote commands.

The DUT can ask the server to perform an action by sending a UDP message of the form:
    #CMD <COMMAND_NAME> [args...]
e.g. b'#CMD HARD_REBOOT'.

Handlers are registered by name in a DUTCommandDispatcher, so adding a new remote command is a
two-step change: add a member to DUTCommand, then call dispatcher.register(...) with a handler
in Machine.__init__. Nothing else in the receive loop needs to change.
"""
import enum
import logging
import typing


class DUTCommand(enum.Enum):
    # Power cycle the DUT through its network power switch
    HARD_REBOOT = "HARD_REBOOT"
    # Kill and re-run the current benchmark on the DUT, without power cycling it
    SOFT_REBOOT = "SOFT_REBOOT"
    # Beam status notifications sent by some DUT firmwares (e.g. the Versal bare-metal app) around
    # a beam-on/beam-off window. Handlers are currently stubs (log-only) - see README.md, "DUT-requested commands".
    OPEN_BEAM = "OPEN_BEAM"
    CLOSE_BEAM = "CLOSE_BEAM"

    @classmethod
    def from_string(cls, name: str) -> typing.Optional["DUTCommand"]:
        try:
            return cls(name.strip())
        except ValueError:
            return None

    def __str__(self) -> str:
        return self.value


# A handler receives whatever text followed the command name (possibly empty) and performs
# the requested action; it is expected to do its own error handling/logging.
DUTCommandHandler = typing.Callable[[str], None]


class DUTCommandDispatcher:
    """ Registry mapping DUTCommand members to handlers, and the parser for '#CMD ...' payloads """

    def __init__(self, logger_name: str):
        self.__logger = logging.getLogger(f"{logger_name}.{__name__}")
        self.__handlers: typing.Dict[DUTCommand, DUTCommandHandler] = dict()

    def register(self, command: DUTCommand, handler: DUTCommandHandler) -> None:
        """ Register (or replace) the handler executed when `command` is requested by a DUT """
        self.__handlers[command] = handler

    def dispatch(self, raw_message: str) -> bool:
        """ Parse a raw '#CMD' payload (with the '#CMD' prefix already stripped) and execute the
        registered handler for it, if any.
        :param raw_message: e.g. "HARD_REBOOT" or "SOFT_REBOOT"
        :return: True if a registered handler was executed, False otherwise
        """
        raw_message = raw_message.strip()
        command_name, _, args = raw_message.partition(" ")
        command = DUTCommand.from_string(command_name)
        if command is None or command not in self.__handlers:
            self.__logger.error(f"Received unknown or unregistered DUT command: '{raw_message}'")
            return False

        self.__logger.info(f"Executing DUT-requested command {command} args='{args}'")
        self.__handlers[command](args)
        return True
