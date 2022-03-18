"""
Module to log the info received from the devices
"""
import enum
import logging
import os
import struct

from datetime import datetime


class EndStatus(enum.Enum):
    NORMAL_END = "#END"
    APPLICATION_CRASH = "#DUE: system crash"
    POWER_CYCLE = "#DUE: power cycle"

    def __str__(self):
        return self.name

    def __repr__(self):
        return str(self)


class DUTLogging:
    """ Device Under Test (DUT) logging class.
    This class will replace the local log procedure that
    each device used to perform in the past.
    """

    def __init__(self, log_dir: str, test_name: str, test_header: str, hostname: str, logger_name: str):
        """ DUTLogging create the log file and writes the header on the first line
        :param log_dir: directory of the logfile
        :param test_name: Name of the test that will be performed, ex: cuda_lava_fp16, zedboard_lenet_int8, etc.
        :param test_header: Specific characteristics of the test, extracted from the configuration files
        :param hostname: Device hostname
        """
        self.__log_dir = log_dir
        self.__test_name = test_name
        self.__test_header = test_header
        self.__hostname = hostname
        self.__logger = logging.getLogger(f"{logger_name}.{__name__}")
        # Create the file when the first message arrives
        self.__filename = None

    def __create_new_file(self, ecc_status: int):
        if self.__filename is None:
            ecc_config = "OFF" if ecc_status == 0 else "ON"
            # log example: 2021_11_15_22_08_25_cuda_trip_half_lava_ECC_OFF_fernando.log
            date = datetime.today()
            date_fmt = date.strftime('%Y_%m_%d_%H_%M_%S')
            log_filename = f"{self.__log_dir}/{date_fmt}_{self.__test_name}_ECC_{ecc_config}_{self.__hostname}.log"
            # Writing the header to the file
            try:
                with open(log_filename, "w") as log_file:
                    begin_str = f"#SERVER_BEGIN Y:{date.year} M:{date.month} D:{date.day} "
                    begin_str += f"Time:{date.hour}:{date.minute}:{date.second}-{date.microsecond}\n"
                    log_file.write(f"#SERVER_HEADER {self.__test_header}\n")
                    log_file.write(begin_str)
                    self.__filename = log_filename
            except OSError:
                self.__logger.exception(f"Could not create the file {log_filename}")

    def __call__(self, message: bytes, *args, **kwargs) -> None:
        """ Log a message from the DUT
        :param message: a message is composed of
        <first byte ecc status>
        <message of maximum 1023 bytes>
        1 byte for ecc + 1023 maximum message content = 1024 bytes
        """
        ecc_status = int(message[0])
        self.__create_new_file(ecc_status=ecc_status)
        message_content = message[1:].decode("ascii")
        with open(self.__filename, "a") as log_file:
            log_file.write(message_content + "\n")

    def finish_this_dut_log(self, end_status: EndStatus = EndStatus.NORMAL_END):
        """ Destructor of the class
        Check if the file exists and put an END in the last line
        :param end_status status of the ending of the log
        EndStatus:
            NORMAL_END = "#END"
            APPLICATION_CRASH = "#DUE: system crash"
            POWER_CYCLE = "#DUE: power cycle"
        """
        if os.path.isfile(self.__filename):
            with open(self.__filename, "a") as log_file:
                date_fmt = datetime.today().strftime('%Y-%m-%d-%H-%M-%S')
                log_file.write(f"({date_fmt}) {end_status}")

    @property
    def log_filename(self):
        return self.__filename


if __name__ == '__main__':
    def debug():
        # FOR DEBUG ONLY
        print("CREATING THE MACHINE")
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
            datefmt='%d-%m-%y %H:%M:%S',
            filename="unit_test_log_DUTLogging.log",
            filemode='w'
        )
        dut_logging = DUTLogging(
            log_dir="/tmp",
            test_name="DebugTest",
            test_header="Testing DUT_LOGGING",
            hostname="carol",
            endianness="little-endian",
            logger_name="DUT_LOGGING"
        )
        print("Not valid name", dut_logging.log_filename)
        ecc = 0
        for i in range(100):
            mss_content = f"Testing iteration {i}"
            print("MSG:", mss_content)
            ecc_status = struct.pack("<b", ecc)
            mss = ecc_status + mss_content.encode("ascii")
            dut_logging(message=mss)
        print("Log filename", dut_logging.log_filename)
        dut_logging(message=bytes(struct.pack("<b", ecc)) + "#END".encode("ascii"))


    debug()
