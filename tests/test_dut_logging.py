import os.path
import struct
import unittest

from server.dut_logging import DUTLogging
from server.logger_formatter import logging_setup


class DUTLoggingTestCase(unittest.TestCase):
    def test_dut_logging(self):
        logger = logging_setup(logger_name="DUT_LOGGING", log_file="unit_test_log_DUTLogging.log")
        logger.debug("DEBUGGING THE DUT LOGGING")
        dut_logging = DUTLogging(log_dir="/tmp",
                                 test_name="DebugTest",
                                 test_header="Testing DUT_LOGGING",
                                 hostname="carol",
                                 logger_name="DUT_LOGGING")
        logger.debug(f"Not valid log name {dut_logging.log_filename}")
        ecc = 13
        for i in range(10):
            mss_content = f"Testing iteration {i}"
            logger.debug("MSG:" + mss_content)
            ecc_status = struct.pack("<b", ecc)
            mss = ecc_status + mss_content.encode("ascii")
            dut_logging(message=mss)
        logger.debug("Log filename " + dut_logging.log_filename)
        # dut_logging.finish_this_dut_log(EndStatus.NORMAL_END)
        self.assertEqual(True, os.path.isfile(
            dut_logging.log_filename) and "ECC_OFF" in dut_logging.log_filename)  # add assertion here


if __name__ == '__main__':
    unittest.main()
