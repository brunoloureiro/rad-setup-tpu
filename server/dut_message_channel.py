"""
Abstraction over the transport used to receive DUT status/log messages (#IT, #LOGFILE, #HEADER,
#BEGIN, #END, #INF, #ERR, #SDC, #ABORT, #CMD, ...) sent by libLogHelper.

This is the "ethernet vs jtag" axis (see CLAUDE.md), independent of a DUT's dut_mode
(active/passive, see dut_deployment.py): it only controls how the server listens for messages,
not how it (re)starts the DUT's app.

Two transports:
- EthernetMessageChannel: a UDP socket bound to server_ip:receive_port, the original behavior.
  Used when the DUT has a working network stack and libLogHelper sends its messages over UDP.
- JTAGMessageChannel: the JTAG probe's serial/UART bridge (jtag_port, or a stable jtag_id resolved
  to a device path automatically - see jtag_port.py), for DUTs with no network stack at all (e.g. a
  bare-metal board driven purely over JTAG). Messages are framed by newlines: each line is treated
  as one ASCII-text message - i.e. the DUT is expected to write one message per line to its UART
  (ending in '\\n'). Every raw byte read off the port is also mirrored to a plain file via
  serial_tee.SerialTee, so another process/human can watch the traffic without opening the port
  itself (see serial_tee.py for why that matters).

Both raise TimeoutError if no message arrives within the configured timeout, so Machine.run()'s
receive loop can treat them identically regardless of which transport is configured.
"""
import abc
import logging
import os
import socket
import threading
import time
import typing

from .jtag_port import find_serial_port_by_id
from .serial_tee import SerialTee


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

    # Hard-coded number of reconnect attempts made after noticing the JTAG serial port has
    # disconnected (failing to open it, or an error while reading), before giving up and letting
    # Machine.run()'s regular timeout-escalation logic (redeploy/reboot) take over. Not
    # configurable per-DUT, similar to e.g. Machine's __MAX_LOGIN_TRIES.
    MAX_JTAG_RECONNECT_ATTEMPTS = 5

    def __init__(self, port: typing.Optional[str], baudrate: int, timeout: float, logger_name: str,
                jtag_id: typing.Optional[str] = None, redeploy_on_disconnect_delay: float = 1.0,
                stop_event: typing.Optional[threading.Event] = None,
                raw_log_path: typing.Optional[str] = None):
        super().__init__(timeout=timeout, logger_name=logger_name)
        # __configured_port: the literal device path from config, if that's how this DUT is
        # configured (may be None when jtag_id is used instead - see __resolve_port). __port: the
        # device path this channel is actually using right now, i.e. what __configured_port
        # resolves to, or what jtag_id last resolved to - only meaningful once a serial.Serial has
        # actually been opened at least once, purely for logging/__str__.
        self.__configured_port = port
        self.__jtag_id = jtag_id
        self.__port = port
        self.__baudrate = baudrate
        self.__serial = None
        # Bytes already read from the port that have not yet been split into a complete message
        self.__buffer = b""
        # Avoids re-logging the same "port missing" error on every reconnect attempt while the
        # probe stays disconnected
        self.__port_missing_logged = False
        # Total time budget (seconds) spent retrying a reconnect after a disconnect is noticed,
        # spread evenly across MAX_JTAG_RECONNECT_ATTEMPTS attempts - see __reconnect_with_retries.
        self.__redeploy_on_disconnect_delay = redeploy_on_disconnect_delay
        # Used for an interruptible wait between reconnect attempts (see Machine's convention of
        # never time.sleep()-ing where a stop_event.wait() can be interrupted on shutdown instead)
        self.__stop_event = stop_event
        # Mirrors every raw byte read off the port to a plain file - see serial_tee.py. A no-op
        # when raw_log_path is None/"".
        self.__tee = SerialTee(raw_log_path, self._logger)

    def __resolve_port(self) -> typing.Optional[str]:
        """ Re-resolve the device path to open/reopen, fresh on every call - a jtag_id can resolve
        to a different device path than last time (e.g. after USB re-enumeration), so this must
        never be cached across (re)connect attempts. """
        if self.__jtag_id:
            return find_serial_port_by_id(self.__jtag_id, self._logger)
        return self.__configured_port

    def __port_label(self) -> str:
        """ Human-readable description of what this channel is configured to open, for log lines
        emitted before/without a resolved device path (see __attempt_reopen). """
        if self.__jtag_id:
            return f"JTAG id '{self.__jtag_id}'"
        return f"port {self.__configured_port}"

    def open(self) -> None:
        self._logger.info(f"Opening JTAG serial connection for DUT messages ({self.__port_label()}) "
                          f"@ {self.__baudrate} baud")
        self.__buffer = b""
        self.__tee.open()
        # Deliberately does not raise if the port/id cannot be resolved or opened right now (unlike
        # a literal, immediately-checked jtag_port used to): a JTAG probe/UART adapter not being
        # plugged in *yet* at server startup must not prevent the whole server (all Machine
        # threads, including unrelated DUTs) from starting. __attempt_reopen already logs a clear,
        # de-duplicated error in that case; receive() below transparently keeps retrying via
        # __reconnect_with_retries(), exactly like a mid-run disconnect.
        self.__attempt_reopen()
        if self.__serial is not None:
            self._logger.info(f"Listening for DUT messages over JTAG serial port {self.__port}")

    def receive(self) -> bytes:
        import serial

        # The port was closed by a previous disconnect (see except clause below) - try to reopen
        # it before reading. A hard/soft reboot may have re-enumerated the USB adapter by now (see
        # DEBUG_PROGRESS.md: a board reset can briefly drop power to the onboard FTDI chip and
        # make it disappear/reappear as a device node). If it's still not there after
        # MAX_JTAG_RECONNECT_ATTEMPTS retries, treat this like a regular receive timeout so
        # Machine.run()'s existing timeout-escalation logic (soft app reboot / redeploy -> soft OS
        # reboot -> hard power cycle) kicks in instead of crashing the Machine thread.
        if self.__serial is None:
            if not self.__reconnect_with_retries():
                raise TimeoutError(
                    f"JTAG serial {self.__desc()} is unavailable after "
                    f"{self.MAX_JTAG_RECONNECT_ATTEMPTS} reconnect attempt(s)")

        deadline = time.time() + self._timeout
        while b"\n" not in self.__buffer:
            if time.time() >= deadline:
                raise TimeoutError(f"No DUT message received on {self.__desc()} within {self._timeout}s")
            try:
                waiting = self.__serial.in_waiting
                chunk = self.__serial.read(waiting if waiting else 1)
            except (serial.SerialException, OSError) as e:
                self._logger.error(
                    f"JTAG serial {self.__desc()} disconnected while reading ({e}) - closing it "
                    f"and attempting to reconnect")
                self.__close_serial()
                if not self.__reconnect_with_retries():
                    raise TimeoutError(
                        f"JTAG serial {self.__desc()} disconnected and did not come back after "
                        f"{self.MAX_JTAG_RECONNECT_ATTEMPTS} reconnect attempt(s): {e}") from e
                continue
            self.__tee.write(chunk)
            self.__buffer += chunk

        line, self.__buffer = self.__buffer.split(b"\n", 1)
        return line.rstrip(b"\r")

    def __desc(self) -> str:
        """ Best available description of this channel's serial port for log/error messages: the
        last actually-opened device path if there is one, otherwise the configured port/jtag_id
        (see __port_label) for when nothing has ever been resolved/opened yet. """
        return f"port {self.__port}" if self.__port else self.__port_label()

    def __reconnect_with_retries(self) -> bool:
        """ Try to reopen the JTAG serial port, retrying up to MAX_JTAG_RECONNECT_ATTEMPTS times.
        The redeploy_on_disconnect_delay budget (config field 'redeploy_on_disconnect_delay',
        default 1s) is spread evenly across those attempts - i.e. each retry waits
        redeploy_on_disconnect_delay / MAX_JTAG_RECONNECT_ATTEMPTS seconds - so brief adapter
        hiccups (see DEBUG_PROGRESS.md) can be absorbed here without escalating all the way to
        Machine.run()'s redeploy/reboot logic.
        :return: True if the port was reopened, False if it is still unavailable after all attempts
        """
        retry_delay = self.__redeploy_on_disconnect_delay / self.MAX_JTAG_RECONNECT_ATTEMPTS
        for attempt in range(1, self.MAX_JTAG_RECONNECT_ATTEMPTS + 1):
            self.__attempt_reopen()
            if self.__serial is not None:
                if attempt > 1:
                    self._logger.info(f"Reconnected to JTAG serial port {self.__port} on attempt {attempt}")
                return True
            if attempt == self.MAX_JTAG_RECONNECT_ATTEMPTS:
                break
            if self.__stop_event is not None and self.__stop_event.is_set():
                break
            if self.__stop_event is not None:
                self.__stop_event.wait(retry_delay)
            else:
                time.sleep(retry_delay)
        return False

    def __close_serial(self) -> None:
        if self.__serial is not None:
            try:
                self.__serial.close()
            except Exception as e:
                self._logger.warning(f"Error closing already-broken JTAG serial {self.__desc()}: {e}")
            self.__serial = None
        self.__buffer = b""

    def __attempt_reopen(self) -> None:
        import serial

        port = self.__resolve_port()
        if port is None:
            if not self.__port_missing_logged:
                if self.__jtag_id:
                    self._logger.error(
                        f"No serial port currently matches JTAG id '{self.__jtag_id}' - waiting for "
                        f"the probe to be plugged in/enumerated (e.g. after a power cycle "
                        f"re-enumerates the USB/JTAG-UART adapter). This is not fatal: the server "
                        f"keeps running and will start using it automatically once it appears.")
                else:
                    self._logger.error(
                        f"JTAG serial port {self.__configured_port} not present - waiting for it to "
                        f"reappear (e.g. after a power cycle re-enumerates the USB/JTAG-UART "
                        f"adapter). This is not fatal: the server keeps running and will start "
                        f"using it automatically once it appears.")
                self.__port_missing_logged = True
            return

        if not os.path.exists(port):
            # Only reachable for a literal 'jtag_port' - find_serial_port_by_id only ever returns
            # a device path pyserial just enumerated, so this is a defensive check kept for parity
            # with that case (and the rare TOCTOU race where a resolved port disappears again
            # between the id lookup above and here).
            if not self.__port_missing_logged:
                self._logger.error(
                    f"JTAG serial port {port} not present - waiting for it to reappear (e.g. after "
                    f"a power cycle re-enumerates the USB/JTAG-UART adapter). This is not fatal: "
                    f"the server keeps running and will start using it automatically once it "
                    f"appears.")
                self.__port_missing_logged = True
            return

        self.__port_missing_logged = False
        try:
            self.__serial = serial.Serial(port=port, baudrate=self.__baudrate, timeout=0.5)
        except serial.SerialException as e:
            self._logger.error(f"Failed to open JTAG serial port {port}: {e}")
            self.__serial = None
            return

        if self.__jtag_id and port != self.__port:
            self._logger.info(f"Resolved JTAG id '{self.__jtag_id}' to serial port {port}")
        self.__port = port
        self._logger.info(f"Opened JTAG serial port {port} for DUT messages")

    def close(self) -> None:
        self.__close_serial()
        self.__tee.close()


def create_message_channel(connection_type: str, timeout: float, logger_name: str,
                           **transport_kwargs) -> MessageChannel:
    """ Build a fresh (not-yet-opened) MessageChannel for the given transport
    :param connection_type: "ethernet" or "jtag"
    :param transport_kwargs: for "ethernet": server_ip, receive_port. For "jtag": jtag_port and/or
        jtag_id, jtag_baudrate, and optionally redeploy_on_disconnect_delay, stop_event, raw_log_path.
    :raises ValueError: if connection_type is not supported
    """
    connection_type = connection_type.lower()
    if connection_type == "ethernet":
        return EthernetMessageChannel(server_ip=transport_kwargs["server_ip"],
                                      receive_port=transport_kwargs["receive_port"],
                                      timeout=timeout, logger_name=logger_name)
    if connection_type == "jtag":
        return JTAGMessageChannel(
            port=transport_kwargs.get("jtag_port"), jtag_id=transport_kwargs.get("jtag_id"),
            baudrate=transport_kwargs["jtag_baudrate"], timeout=timeout, logger_name=logger_name,
            redeploy_on_disconnect_delay=transport_kwargs.get("redeploy_on_disconnect_delay", 1.0),
            stop_event=transport_kwargs.get("stop_event"),
            raw_log_path=transport_kwargs.get("raw_log_path"))
    raise ValueError(f"Unsupported connection_type '{connection_type}', expected 'ethernet' or 'jtag'")
