"""
Mirrors raw bytes read from a JTAG probe's serial/UART bridge into a plain file, independent of
however dut_message_channel.py / dut_connection.py subsequently frame/decode those bytes into
discrete DUT messages or console prompts.

Motivation: a serial device only has one reader at a time - the OS hands each chunk of incoming
bytes to whichever process's read() call happens to be pending, so if this server and some other
process (e.g. a human's `cat`/`minicom`/`tail` session opened directly on the same /dev/ttyUSB<n>
for a look at the raw traffic) both try to read the same port concurrently, each of them only ever
sees an arbitrary, non-deterministically split subset of the bytes - corrupting both views. The fix
is that this server must be the only process that ever opens the port directly; anyone else who
wants to watch the traffic instead tails the mirror file a SerialTee writes here, which is always a
faithful copy of exactly what this server itself read from the wire.
"""
import logging
import os
import threading
import typing


class SerialTee:
    """ Appends every chunk of raw bytes read from a serial port to a plain file, flushing
    immediately (no buffering) so a `tail -f` reader sees data as soon as this process reads it off
    the wire. A no-op (write() does nothing) when constructed with path=None/"" - callers do not
    need to special-case a disabled tee. """

    def __init__(self, path: typing.Optional[str], logger: logging.Logger):
        self.__path = path
        self.__logger = logger
        self.__fp: typing.Optional[typing.IO] = None
        self.__lock = threading.Lock()

    def open(self) -> None:
        """ (Re)open the mirror file for appending. Safe to call repeatedly (e.g. once per JTAG
        serial reconnect) - a file already open is left as-is. Failure to open is logged and
        otherwise ignored: a broken raw-log mirror must never take down DUT message/console
        handling. """
        if not self.__path or self.__fp is not None:
            return
        try:
            directory = os.path.dirname(self.__path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            self.__fp = open(self.__path, "ab", buffering=0)
            self.__logger.info(f"Mirroring raw JTAG serial traffic to {self.__path}")
        except OSError as e:
            self.__logger.warning(
                f"Could not open raw JTAG serial mirror file {self.__path}: {e} - continuing "
                f"without it")
            self.__fp = None

    def write(self, data: bytes) -> None:
        if not data or self.__fp is None:
            return
        with self.__lock:
            if self.__fp is None:
                return
            try:
                self.__fp.write(data)
            except OSError as e:
                self.__logger.warning(f"Failed writing to raw JTAG serial mirror file {self.__path}: {e}")

    def close(self) -> None:
        with self.__lock:
            if self.__fp is not None:
                try:
                    self.__fp.close()
                except OSError:
                    pass
                self.__fp = None
