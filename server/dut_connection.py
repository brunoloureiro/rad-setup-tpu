"""
Abstraction over the console connection used to log into a DUT and issue commands to it
(start/kill a benchmark, trigger an OS reboot, ...).

Only DUTs with dut_mode: active (see machine.py) ever open a console - dut_mode: passive DUTs have
no OS/shell to log into. Which transport that console uses is selected per-DUT by the console_type
field ("telnet", the default, or "jtag"), a third independent axis alongside dut_mode and
connection_type (see CLAUDE.md "What this is"): connection_type only controls how the server
*listens* for DUT status messages (see dut_message_channel.py) and is irrelevant here - e.g. an
active DUT can use a JTAG console (console_type: jtag) while still reporting status over Ethernet
(connection_type: ethernet), if its JTAG probe's UART bridge only carries the console and the
board's own network stack carries status messages.

Two transports are provided:
- TelnetDUTConnection: a network Telnet connection.
- JTAGDUTConnection: a serial console reached through a JTAG probe's UART bridge (e.g. an
  FTDI-based adapter exposing a virtual COM port for the target's console), using pyserial.

The login handshake (wait for a login/password prompt, authenticate, wait for a shell prompt) is
identical across transports, so it lives once in DUTConnection.login() built on top of four raw
I/O primitives (open/write/read_until/read_very_eager/close) that each subclass implements. Adding
a new transport (e.g. SSH) means implementing those primitives only; Machine and the login
handshake do not need to change.
"""
import abc
import logging
import os
import time
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


class JTAGDUTConnection(DUTConnection):
    """ Console connection reached through a JTAG probe's UART bridge, using pyserial """

    def __init__(self, port: str, baudrate: int, username: str, password: str, timeout: float, logger_name: str):
        super().__init__(username=username, password=password, timeout=timeout, logger_name=logger_name)
        self.__port = port
        self.__baudrate = baudrate
        self.__serial = None
        # Bytes already read from the port that have not been consumed by read_until/read_very_eager yet
        self.__buffer = b""

    def open(self) -> None:
        import serial
        self._logger.info(f"Opening JTAG serial console on port={self.__port} baudrate={self.__baudrate}")

        # Check up front so a wrong/unplugged console_jtag_port produces one unmistakable log line
        # instead of a bare, easy-to-miss stack trace deep inside pyserial (same pattern as
        # JTAGMessageChannel.open() in dut_message_channel.py).
        if not os.path.exists(self.__port):
            self._logger.error(
                f"JTAG console serial port {self.__port} does not exist. Check that the JTAG "
                f"probe/UART adapter is plugged in, that 'console_jtag_port' in the machine config "
                f"matches the actual device (see 'ls /dev/ttyUSB*' or 'ls /dev/ttyACM*' on the "
                f"server host), and that the server has permission to access it (e.g. dialout group).")
            raise serial.SerialException(f"JTAG console serial port {self.__port} not found")

        try:
            self.__serial = serial.Serial(port=self.__port, baudrate=self.__baudrate, timeout=self._timeout)
        except serial.SerialException as e:
            self._logger.error(f"Failed to open JTAG console serial port {self.__port}: {e}")
            raise
        self.__buffer = b""
        self._logger.debug(f"JTAG console serial connection opened on {self.__port}")

    def write(self, data: bytes) -> None:
        self.__serial.write(data)

    def read_until(self, expected: bytes, timeout: typing.Optional[float] = None) -> bytes:
        deadline = time.time() + (timeout if timeout is not None else self._timeout)
        while expected not in self.__buffer and time.time() < deadline:
            waiting = self.__serial.in_waiting
            chunk = self.__serial.read(waiting if waiting else 1)
            self.__buffer += chunk

        if expected not in self.__buffer:
            return b""

        split_at = self.__buffer.index(expected) + len(expected)
        result, self.__buffer = self.__buffer[:split_at], self.__buffer[split_at:]
        return result

    def read_very_eager(self) -> bytes:
        waiting = self.__serial.in_waiting
        result, self.__buffer = self.__buffer + self.__serial.read(waiting), b""
        return result

    def close(self) -> None:
        if self.__serial is not None:
            self.__serial.close()


def create_dut_connection(console_type: str, username: str, password: str, timeout: float, logger_name: str,
                          **transport_kwargs) -> DUTConnection:
    """ Build a fresh (not-yet-opened) DUTConnection for an active DUT's console
    :param console_type: "telnet" or "jtag"
    :param transport_kwargs: for "telnet": ip. For "jtag": jtag_port, jtag_baudrate.
    :raises ValueError: if console_type is not supported
    """
    console_type = console_type.lower()
    if console_type == "telnet":
        return TelnetDUTConnection(ip=transport_kwargs["ip"], username=username, password=password,
                                   timeout=timeout, logger_name=logger_name)
    if console_type == "jtag":
        return JTAGDUTConnection(port=transport_kwargs["jtag_port"], baudrate=transport_kwargs["jtag_baudrate"],
                                 username=username, password=password, timeout=timeout, logger_name=logger_name)
    raise ValueError(f"Unsupported console_type '{console_type}', expected 'telnet' or 'jtag'")
