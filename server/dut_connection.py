"""
Abstraction over the console connection used to log into a DUT and issue commands to it
(start/kill a benchmark, trigger an OS reboot, ...).

Active DUTs (dut_mode: active, see machine.py) always use a network Telnet connection for this -
console access is independent of the "ethernet vs jtag" axis, which only controls how the server
listens for DUT status messages (see dut_message_channel.py). There is currently only one
transport, TelnetDUTConnection; the abstraction exists so a future transport (e.g. SSH) only needs
to implement the four raw I/O primitives below (open/write/read_until/read_very_eager/close) - the
login handshake (wait for a login/password prompt, authenticate, wait for a shell prompt) is
transport-agnostic and lives once in DUTConnection.login().
"""
import abc
import logging
import typing


class DUTConnection(abc.ABC):
    """ Base class for a DUT console connection """

    def __init__(self, username: str, password: str, timeout: float, logger_name: str):
        self._username = username
        self._password = password
        self._timeout = timeout
        self._logger = logging.getLogger(f"{logger_name}.{__name__}")

    @abc.abstractmethod
    def open(self) -> None:
        """ Open the underlying transport (socket, serial port, ...) """

    @abc.abstractmethod
    def write(self, data: bytes) -> None:
        """ Write raw bytes to the DUT console """

    @abc.abstractmethod
    def read_until(self, expected: bytes, timeout: typing.Optional[float] = None) -> bytes:
        """ Block up to `timeout` seconds until `expected` is seen; return everything read up to
        and including `expected`, or whatever was read if the timeout is hit first (possibly b"") """

    @abc.abstractmethod
    def read_very_eager(self) -> bytes:
        """ Non-blocking read of everything currently available """

    @abc.abstractmethod
    def close(self) -> None:
        """ Close the underlying transport """

    def login(self) -> "DUTConnection":
        """ Open the transport and perform the console login handshake
        :raises RuntimeError: if an expected prompt is not seen within the timeout
        """
        self.open()
        transport = type(self).__name__

        if not self.read_until(b'ogin: ', timeout=self._timeout):
            raise RuntimeError(f"{transport} error: Failed to login. Could not input username.")
        self.write(self._username.encode('ascii') + b'\n')
        self.read_very_eager()

        if not self.read_until(b'assword: ', timeout=self._timeout):
            raise RuntimeError(f"{transport} error: Could not login. Could not input password.")
        self.write(self._password.encode('ascii') + b'\n')

        if not self.read_until(b'$ ', timeout=self._timeout):
            raise RuntimeError(f"{transport} error: Could not login. Failed after entering inputs.")

        self._logger.debug(f"Successfully logged in over {transport}.")
        return self

    def __enter__(self) -> "DUTConnection":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


class TelnetDUTConnection(DUTConnection):
    """ Network Telnet console connection """

    def __init__(self, ip: str, username: str, password: str, timeout: float, logger_name: str):
        super().__init__(username=username, password=password, timeout=timeout, logger_name=logger_name)
        self.__ip = ip
        self.__telnet = None

    def open(self) -> None:
        import telnetlib
        self._logger.info(f"Opening Telnet connection to {self.__ip} (timeout={self._timeout}s)")
        try:
            self.__telnet = telnetlib.Telnet(self.__ip, timeout=self._timeout)
        except OSError as e:
            self._logger.error(f"Failed to open Telnet connection to {self.__ip}: {e}")
            raise
        self._logger.debug(f"Telnet connection to {self.__ip} opened")

    def write(self, data: bytes) -> None:
        self.__telnet.write(data)

    def read_until(self, expected: bytes, timeout: typing.Optional[float] = None) -> bytes:
        return self.__telnet.read_until(expected, timeout=timeout if timeout is not None else self._timeout)

    def read_very_eager(self) -> bytes:
        return self.__telnet.read_very_eager()

    def close(self) -> None:
        if self.__telnet is not None:
            self.__telnet.close()


def create_dut_connection(ip: str, username: str, password: str, timeout: float,
                          logger_name: str) -> DUTConnection:
    """ Build a fresh (not-yet-opened) DUTConnection for an active DUT's console (always Telnet) """
    return TelnetDUTConnection(ip=ip, username=username, password=password, timeout=timeout,
                               logger_name=logger_name)
