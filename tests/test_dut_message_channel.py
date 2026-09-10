import collections
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

from server.dut_message_channel import JTAGMessageChannel

_FakePort = collections.namedtuple("_FakePort", ["device", "serial_number"])


class FakeSerial:
    """ In-memory substitute for serial.Serial, standing in for a JTAG probe's UART bridge that a
    simulated DUT writes status/log lines to. Only the read-side is exercised (JTAGMessageChannel
    never writes to this port), unlike test_dut_connection.py's duplex FakeSerial. """

    def __init__(self, port, baudrate, timeout=None):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._buf = bytearray()
        self._lock = threading.Lock()

    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._buf)

    def read(self, size: int = 1) -> bytes:
        deadline = time.time() + (self.timeout if self.timeout is not None else 0)
        while True:
            with self._lock:
                if self._buf:
                    n = min(size, len(self._buf))
                    data = bytes(self._buf[:n])
                    del self._buf[:n]
                    return data
            if self.timeout is not None and time.time() >= deadline:
                return b""
            time.sleep(0.005)

    def close(self) -> None:
        pass

    def feed(self, data: bytes) -> None:
        with self._lock:
            self._buf.extend(data)


def _patch_serial_with(fake_serial: FakeSerial):
    def _open(port, baudrate, timeout=None):
        fake_serial.port = port
        fake_serial.baudrate = baudrate
        fake_serial.timeout = timeout
        return fake_serial

    return mock.patch("serial.Serial", side_effect=_open)


class JTAGMessageChannelStartupTestCase(unittest.TestCase):
    """ Covers the "server must start even if the JTAG port is not available yet" behavior: unlike
    the pre-existing behavior (open() raising, which propagated out of Machine.__init__ and could
    take down the whole server - see CLAUDE.md/machine.py), open() must never raise for a missing
    port/id; it must instead leave the channel ready for receive() to retry lazily, exactly like a
    later mid-run disconnect already does. """

    def test_open_does_not_raise_when_literal_port_missing(self):
        chan = JTAGMessageChannel(port="/dev/ttyDOES_NOT_EXIST_MC", baudrate=115200, timeout=0.5,
                                  logger_name="TEST")
        chan.open()  # must not raise

    def test_open_does_not_raise_when_jtag_id_unresolved(self):
        with mock.patch("serial.tools.list_ports.comports", return_value=[]):
            chan = JTAGMessageChannel(port=None, jtag_id="NO_SUCH_PROBE", baudrate=115200,
                                      timeout=0.5, logger_name="TEST")
            chan.open()  # must not raise

    def test_receive_times_out_while_port_stays_missing(self):
        chan = JTAGMessageChannel(port="/dev/ttyDOES_NOT_EXIST_MC", baudrate=115200, timeout=0.2,
                                  logger_name="TEST", redeploy_on_disconnect_delay=0.05)
        chan.open()
        with self.assertRaises(TimeoutError):
            chan.receive()

    def test_receive_succeeds_once_port_becomes_available_after_open(self):
        # Simulates a probe plugged in / enumerated only after the server has already started -
        # open() saw it missing, but a later receive() call must still pick it up on its own,
        # without anyone needing to reconstruct the channel or restart the Machine thread.
        fake_serial = FakeSerial(port="/dev/ttyFAKE_MC", baudrate=115200)
        port_present = threading.Event()

        def fake_exists(path):
            return path == "/dev/ttyFAKE_MC" and port_present.is_set()

        with mock.patch("os.path.exists", side_effect=fake_exists), \
                _patch_serial_with(fake_serial):
            chan = JTAGMessageChannel(port="/dev/ttyFAKE_MC", baudrate=115200, timeout=2,
                                      logger_name="TEST", redeploy_on_disconnect_delay=0.1)
            chan.open()

            # Port "plugs in" only now, and the DUT starts sending a message shortly after.
            port_present.set()
            fake_serial.feed(b"#IT 1\n")

            self.assertEqual(b"#IT 1", chan.receive())
            chan.close()


class JTAGMessageChannelJtagIdTestCase(unittest.TestCase):
    def test_jtag_id_is_resolved_to_a_device_path(self):
        fake_serial = FakeSerial(port="/dev/ttyUSB7", baudrate=115200)
        fake_ports = [_FakePort(device="/dev/ttyUSB7", serial_number="PROBE_SERIAL_1")]

        with mock.patch("serial.tools.list_ports.comports", return_value=fake_ports), \
                mock.patch("os.path.exists", return_value=True), \
                _patch_serial_with(fake_serial):
            chan = JTAGMessageChannel(port=None, jtag_id="PROBE_SERIAL_1", baudrate=115200,
                                      timeout=2, logger_name="TEST")
            chan.open()
            fake_serial.feed(b"#IT ok\n")
            self.assertEqual(b"#IT ok", chan.receive())
            chan.close()

    def test_jtag_id_resolves_to_new_device_after_reconnect(self):
        # A probe re-enumerating to a different /dev/ttyUSB<n> mid-run (see dut_message_channel.py
        # / CLAUDE.md's "DUT message channel") must be picked up on the very next reconnect
        # attempt, without the channel needing to be rebuilt.
        serial_a = FakeSerial(port="/dev/ttyUSB8", baudrate=115200)
        serial_b = FakeSerial(port="/dev/ttyUSB9", baudrate=115200)
        current_device = {"path": "/dev/ttyUSB8"}

        def comports():
            return [_FakePort(device=current_device["path"], serial_number="PROBE_SERIAL_2")]

        def fake_serial_open(port, baudrate, timeout=None):
            target = serial_a if port == "/dev/ttyUSB8" else serial_b
            target.timeout = timeout
            return target

        with mock.patch("serial.tools.list_ports.comports", side_effect=comports), \
                mock.patch("os.path.exists", return_value=True), \
                mock.patch("serial.Serial", side_effect=fake_serial_open):
            chan = JTAGMessageChannel(port=None, jtag_id="PROBE_SERIAL_2", baudrate=115200,
                                      timeout=2, logger_name="TEST", redeploy_on_disconnect_delay=0.05)
            chan.open()

            # First message arrives fine over the original device.
            serial_a.feed(b"#IT first\n")
            self.assertEqual(b"#IT first", chan.receive())

            # Probe re-enumerates to a new device node; its old handle starts erroring out.
            current_device["path"] = "/dev/ttyUSB9"

            def broken_read(size=1):
                raise OSError("device disconnected")

            serial_a.read = broken_read

            serial_b.feed(b"#IT second\n")
            self.assertEqual(b"#IT second", chan.receive())
            chan.close()


class JTAGMessageChannelRawTeeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    def test_raw_bytes_are_mirrored_to_the_tee_file(self):
        fake_serial = FakeSerial(port="/dev/ttyFAKE_TEE", baudrate=115200)
        raw_log_path = os.path.join(self.tmp_dir, "nested", "raw.log")

        with mock.patch("os.path.exists", return_value=True), \
                _patch_serial_with(fake_serial):
            chan = JTAGMessageChannel(port="/dev/ttyFAKE_TEE", baudrate=115200, timeout=2,
                                      logger_name="TEST", raw_log_path=raw_log_path)
            chan.open()
            fake_serial.feed(b"#IT 1\n#IT 2\n")
            self.assertEqual(b"#IT 1", chan.receive())
            self.assertEqual(b"#IT 2", chan.receive())
            chan.close()

        with open(raw_log_path, "rb") as fp:
            self.assertEqual(b"#IT 1\n#IT 2\n", fp.read())

    def test_no_tee_file_created_when_raw_log_path_is_none(self):
        fake_serial = FakeSerial(port="/dev/ttyFAKE_NOTEE", baudrate=115200)
        with mock.patch("os.path.exists", return_value=True), \
                _patch_serial_with(fake_serial):
            chan = JTAGMessageChannel(port="/dev/ttyFAKE_NOTEE", baudrate=115200, timeout=2,
                                      logger_name="TEST", raw_log_path=None)
            chan.open()
            fake_serial.feed(b"#IT 1\n")
            self.assertEqual(b"#IT 1", chan.receive())
            chan.close()
        self.assertEqual([], os.listdir(self.tmp_dir))


if __name__ == '__main__':
    unittest.main()
