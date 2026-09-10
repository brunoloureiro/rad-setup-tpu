import collections
import logging
import unittest
from unittest import mock

from server.jtag_port import find_serial_port_by_id

_FakePort = collections.namedtuple("_FakePort", ["device", "serial_number"])


class FindSerialPortByIdTestCase(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("TEST_JTAG_PORT")

    def _patch_ports(self, ports):
        return mock.patch("serial.tools.list_ports.comports", return_value=ports)

    def test_exact_match_returns_device(self):
        ports = [
            _FakePort(device="/dev/ttyUSB0", serial_number="AAAA1111"),
            _FakePort(device="/dev/ttyUSB2", serial_number="25163300A1A7A"),
        ]
        with self._patch_ports(ports):
            self.assertEqual("/dev/ttyUSB2", find_serial_port_by_id("25163300A1A7A", self.logger))

    def test_no_match_returns_none(self):
        ports = [_FakePort(device="/dev/ttyUSB0", serial_number="AAAA1111")]
        with self._patch_ports(ports):
            self.assertIsNone(find_serial_port_by_id("NOT_PRESENT", self.logger))

    def test_no_ports_at_all_returns_none(self):
        with self._patch_ports([]):
            self.assertIsNone(find_serial_port_by_id("ANYTHING", self.logger))

    def test_prefix_match_falls_back_when_no_exact_match(self):
        # Some FTDI multi-interface probes report a serial_number that is the board's id plus a
        # per-interface suffix (e.g. 'A') - see jtag_port.py's docstring.
        ports = [_FakePort(device="/dev/ttyUSB3", serial_number="25163300A1A7AA")]
        with self._patch_ports(ports):
            self.assertEqual("/dev/ttyUSB3", find_serial_port_by_id("25163300A1A7A", self.logger))

    def test_ports_without_serial_number_are_ignored(self):
        ports = [_FakePort(device="/dev/ttyUSB0", serial_number=None)]
        with self._patch_ports(ports):
            self.assertIsNone(find_serial_port_by_id("25163300A1A7A", self.logger))

    def test_multiple_matches_picks_lowest_device_name_deterministically(self):
        ports = [
            _FakePort(device="/dev/ttyUSB5", serial_number="SAME_ID"),
            _FakePort(device="/dev/ttyUSB1", serial_number="SAME_ID"),
        ]
        with self._patch_ports(ports):
            self.assertEqual("/dev/ttyUSB1", find_serial_port_by_id("SAME_ID", self.logger))


if __name__ == '__main__':
    unittest.main()
