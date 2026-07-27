import threading
import time
import unittest
from unittest import mock

from server.dut_connection import JTAGDUTConnection, TelnetDUTConnection, create_dut_connection


class FakeSerial:
    """ In-memory duplex substitute for serial.Serial, standing in for a JTAG probe's UART bridge
    to a simulated DUT. Bytes written by the client under test (JTAGDUTConnection) land in
    to_dut/from_client; bytes queued via dut_send() are what the client's read()/in_waiting see -
    i.e. this plays the DUT side of the wire, so tests can drive a scripted console handshake
    (login/password/shell prompts) without any real hardware or OS-level tty/pty involved.
    """

    def __init__(self, port, baudrate, timeout=None):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._to_client = bytearray()
        self.from_client = bytearray()
        self._lock = threading.Lock()
        self.closed = False

    def write(self, data: bytes) -> int:
        with self._lock:
            self.from_client.extend(data)
        return len(data)

    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._to_client)

    def read(self, size: int = 1) -> bytes:
        deadline = time.time() + (self.timeout if self.timeout is not None else 0)
        while True:
            with self._lock:
                if self._to_client:
                    n = min(size, len(self._to_client))
                    data = bytes(self._to_client[:n])
                    del self._to_client[:n]
                    return data
            if self.timeout is not None and time.time() >= deadline:
                return b""
            time.sleep(0.005)

    def close(self) -> None:
        self.closed = True

    def dut_send(self, data: bytes) -> None:
        """ Test helper: queue bytes as if sent by the simulated DUT """
        with self._lock:
            self._to_client.extend(data)


def _patch_serial_with(fake_serial: FakeSerial):
    """ Patch serial.Serial so opening it returns fake_serial, configured with whatever
    port/baudrate/timeout the code under test actually requested (a plain mock.patch(...,
    return_value=fake_serial) would silently ignore the real timeout kwarg, leaving reads blocking
    forever instead of honoring it). """

    def _open(port, baudrate, timeout=None):
        fake_serial.port = port
        fake_serial.baudrate = baudrate
        fake_serial.timeout = timeout
        return fake_serial

    return mock.patch("serial.Serial", side_effect=_open)


class CreateDUTConnectionTestCase(unittest.TestCase):
    def test_telnet_returns_telnet_connection(self):
        conn = create_dut_connection(console_type="telnet", username="u", password="p", timeout=1,
                                     logger_name="TEST", ip="10.0.0.1", jtag_port=None, jtag_baudrate=115200)
        self.assertIsInstance(conn, TelnetDUTConnection)

    def test_jtag_returns_jtag_connection(self):
        conn = create_dut_connection(console_type="jtag", username="u", password="p", timeout=1,
                                     logger_name="TEST", ip=None, jtag_port="/dev/ttyFAKE", jtag_baudrate=115200)
        self.assertIsInstance(conn, JTAGDUTConnection)

    def test_unsupported_console_type_raises(self):
        with self.assertRaises(ValueError):
            create_dut_connection(console_type="ssh", username="u", password="p", timeout=1, logger_name="TEST")


class JTAGDUTConnectionTestCase(unittest.TestCase):
    def _simulate_dut_login(self, fake_serial: FakeSerial, username: str, password: str) -> None:
        """ Background 'DUT' thread: send prompts and react to what the client writes, exactly
        like a real bare-metal/OS console would during login """

        def wait_for_line() -> bytes:
            deadline = time.time() + 2
            while time.time() < deadline:
                with fake_serial._lock:
                    if b"\n" in fake_serial.from_client:
                        line, rest = fake_serial.from_client.split(b"\n", 1)
                        fake_serial.from_client = bytearray(rest)
                        return bytes(line)
                time.sleep(0.005)
            raise TimeoutError("simulated DUT never received expected input")

        fake_serial.dut_send(b"some banner text\r\nlogin: ")
        received_user = wait_for_line()
        assert received_user == username.encode("ascii"), received_user
        fake_serial.dut_send(b"Password: ")
        received_pass = wait_for_line()
        assert received_pass == password.encode("ascii"), received_pass
        fake_serial.dut_send(b"$ ")

    def test_login_succeeds_against_simulated_dut(self):
        fake_serial = FakeSerial(port="/dev/ttyFAKE", baudrate=115200)
        with _patch_serial_with(fake_serial), \
                mock.patch("os.path.exists", return_value=True):
            conn = JTAGDUTConnection(port="/dev/ttyFAKE", baudrate=115200, username="carol",
                                     password="qwerty0", timeout=2, logger_name="TEST")

            dut_thread = threading.Thread(
                target=self._simulate_dut_login, args=(fake_serial, "carol", "qwerty0"), daemon=True)
            dut_thread.start()

            logged_in = conn.login()
            dut_thread.join(timeout=2)

            self.assertIs(logged_in, conn)
            self.assertFalse(dut_thread.is_alive())

            # Exercise write()/read_very_eager() the way Machine.__soft_app_reboot does
            fake_serial.dut_send(b"benchmark output\n")
            time.sleep(0.05)
            conn.write(b"killall -9 dummy\n")
            eager = conn.read_very_eager()
            self.assertIn(b"benchmark output", eager)
            self.assertIn(b"killall -9 dummy\n", bytes(fake_serial.from_client))

            conn.close()
            self.assertTrue(fake_serial.closed)

    def test_login_times_out_when_dut_is_silent(self):
        fake_serial = FakeSerial(port="/dev/ttyFAKE", baudrate=115200)
        with _patch_serial_with(fake_serial), \
                mock.patch("os.path.exists", return_value=True):
            conn = JTAGDUTConnection(port="/dev/ttyFAKE", baudrate=115200, username="carol",
                                     password="qwerty0", timeout=0.2, logger_name="TEST")
            with self.assertRaises(RuntimeError):
                conn.login()

    def test_open_raises_when_port_does_not_exist(self):
        conn = JTAGDUTConnection(port="/dev/ttyDOES_NOT_EXIST_JTAG_CONSOLE", baudrate=115200,
                                 username="carol", password="qwerty0", timeout=1, logger_name="TEST")
        with self.assertRaises(Exception):
            conn.open()


if __name__ == '__main__':
    unittest.main()
