"""
Abstraction over the transport used to receive DUT status/log messages (#IT, #LOGFILE, #HEADER,
#BEGIN, #END, #INF, #ERR, #SDC, #ABORT, #CMD, ...) sent by libLogHelper.

This is the "ethernet vs jtag" axis (see CLAUDE.md), independent of a DUT's dut_mode
(active/passive, see dut_deployment.py): it only controls how the server listens for messages,
not how it (re)starts the DUT's app.

Two transports:
- EthernetMessageChannel: a UDP socket bound to server_ip:receive_port, the original behavior.
  Used when the DUT has a working network stack and libLogHelper sends its messages over UDP.
- JTAGMessageChannel: the JTAG probe's serial/UART bridge (jtag_port), for DUTs with no network
  stack at all (e.g. a bare-metal board driven purely over JTAG). Messages are framed by
  newlines: each line is treated as one '<ecc status byte><ascii text>' message, the same wire
  format libLogHelper uses per UDP datagram (see dut_logging.py) - i.e. the DUT is expected to
  write one message per line to its UART (ending in '\\n'), with the ECC status byte as the first
  byte of that line.

Both raise TimeoutError if no message arrives within the configured timeout, so Machine.run()'s
receive loop can treat them identically regardless of which transport is configured.
"""
import abc
import logging
import os
import socket
import time
import typing


class MessageChannel(abc.ABC):
    """ Base class for a DUT message-receiving channel """

    def __init__(self, timeout: float, logger_name: str):
        self._timeout = timeout
        self._logger = logging.getLogger(f"{logger_name}.{__name__}")

    @abc.abstractmethod
    def open(self) -> None:
        """ Open the underlying transport (socket, serial port, ...) """

    @abc.abstractmethod
    def receive(self) -> bytes:
        """ Block up to the configured timeout for one message
        :raises TimeoutError: if no message arrives within the timeout
        """

    @abc.abstractmethod
    def close(self) -> None:
        """ Close the underlying transport """


class EthernetMessageChannel(MessageChannel):
    """ Receives DUT messages over a UDP socket bound to server_ip:receive_port """

    __DATA_SIZE = 4096

    def __init__(self, server_ip: str, receive_port: int, timeout: float, logger_name: str):
        super().__init__(timeout=timeout, logger_name=logger_name)
        self.__server_ip = server_ip
        self.__receive_port = receive_port
        self.__socket = None

    def open(self) -> None:
        self.__socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.__socket.bind((self.__server_ip, self.__receive_port))
        # If receive_port was omitted/0, record the actual OS-assigned port (used for __str__ and
        # so the caller can log/display which port ended up bound).
        self.__receive_port = self.__socket.getsockname()[1]
        self.__socket.settimeout(self._timeout)
        self._logger.info(f"Listening for DUT messages over UDP on {self.__server_ip}:{self.__receive_port}")

    @property
    def receive_port(self) -> int:
        return self.__receive_port

    def receive(self) -> bytes:
        data, _address = self.__socket.recvfrom(self.__DATA_SIZE)
        return data

    def close(self) -> None:
        if self.__socket is not None:
            self.__socket.close()


class JTAGMessageChannel(MessageChannel):
    """ Receives DUT messages over a JTAG probe's serial/UART bridge, using pyserial """

    def __init__(self, port: str, baudrate: int, timeout: float, logger_name: str):
        super().__init__(timeout=timeout, logger_name=logger_name)
        self.__port = port
        self.__baudrate = baudrate
        self.__serial = None
        # Bytes already read from the port that have not yet been split into a complete message
        self.__buffer = b""

    def open(self) -> None:
        import serial
        self._logger.info(f"Opening JTAG serial port {self.__port} @ {self.__baudrate} baud for DUT messages")

        # Check up front so a wrong/unplugged jtag_port produces one unmistakable log line
        # instead of the receive loop just timing out silently forever.
        if not os.path.exists(self.__port):
            self._logger.error(
                f"JTAG serial port {self.__port} does not exist. Check that the JTAG probe/UART "
                f"adapter is plugged in, that 'jtag_port' in the machine config matches the actual "
                f"device (see 'ls /dev/ttyUSB*' or 'ls /dev/ttyACM*' on the server host), and that "
                f"the server has permission to access it (e.g. dialout group).")
            raise serial.SerialException(f"JTAG serial port {self.__port} not found")

        try:
            # A short internal read timeout lets receive()'s polling loop check its own overall
            # deadline regularly instead of blocking in a single long serial.read() call.
            self.__serial = serial.Serial(port=self.__port, baudrate=self.__baudrate, timeout=0.5)
        except serial.SerialException as e:
            self._logger.error(f"Failed to open JTAG serial port {self.__port}: {e}")
            raise
        self.__buffer = b""
        self._logger.info(f"Listening for DUT messages over JTAG serial port {self.__port}")

    def receive(self) -> bytes:
        deadline = time.time() + self._timeout
        while b"\n" not in self.__buffer:
            if time.time() >= deadline:
                raise TimeoutError(f"No DUT message received on {self.__port} within {self._timeout}s")
            waiting = self.__serial.in_waiting
            chunk = self.__serial.read(waiting if waiting else 1)
            self.__buffer += chunk

        line, self.__buffer = self.__buffer.split(b"\n", 1)
        return line.rstrip(b"\r")

    def close(self) -> None:
        if self.__serial is not None:
            self.__serial.close()


def create_message_channel(connection_type: str, timeout: float, logger_name: str,
                           **transport_kwargs) -> MessageChannel:
    """ Build a fresh (not-yet-opened) MessageChannel for the given transport
    :param connection_type: "ethernet" or "jtag"
    :param transport_kwargs: for "ethernet": server_ip, receive_port. For "jtag": jtag_port,
        jtag_baudrate.
    :raises ValueError: if connection_type is not supported
    """
    connection_type = connection_type.lower()
    if connection_type == "ethernet":
        return EthernetMessageChannel(server_ip=transport_kwargs["server_ip"],
                                      receive_port=transport_kwargs["receive_port"],
                                      timeout=timeout, logger_name=logger_name)
    if connection_type == "jtag":
        return JTAGMessageChannel(port=transport_kwargs["jtag_port"],
                                  baudrate=transport_kwargs["jtag_baudrate"],
                                  timeout=timeout, logger_name=logger_name)
    raise ValueError(f"Unsupported connection_type '{connection_type}', expected 'ethernet' or 'jtag'")
