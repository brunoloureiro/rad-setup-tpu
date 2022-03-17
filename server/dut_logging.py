"""
Module to log the info received from the devices
"""
import enum
import logging
import struct

from datetime import datetime


class EndStatus(enum.Enum):
    NORMAL_END = "#END"
    SAME_ERROR_LAST_ITERATION = "#ABORT: amount of errors equals of the last iteration"
    TOO_MANY_ERRORS = "#ABORT: too many errors per iteration"
    APPLICATION_CRASH = "#DUE: system crash"
    POWER_CYCLE = "#DUE: power cycle"

    def __str__(self): return self.name

    def __repr__(self): return str(self)


class DUTLogging:
    """ Device Under Test (DUT) logging class.
    This class will replace the local log procedure that
    each device used to perform in the past.
    """

    def __init__(self, log_dir: str, test_name: str, test_header: str, hostname: str, logger_name: str,
                 endianness: str):
        """ DUTLogging create the log file and writes the header on the first line
        :param log_dir: directory of the logfile
        :param test_name: Name of the test that will be performed, ex: cuda_lava_fp16, zedboard_lenet_int8, etc.
        :param test_header: Specific characteristics of the test, extracted from the configuration files
        :param hostname: Device hostname
        :param endianness: if the DUT is big our little endian
        """
        self.__log_dir = log_dir
        self.__test_name = test_name
        self.__test_header = test_header
        self.__hostname = hostname
        self.__logger = logging.getLogger(f"{logger_name}.{__name__}")
        # Create the file when the first message arrives
        self.__is_file_created = False
        self.__endianness = endianness

    def __create_new_file(self, ecc_status: int):
        if self.__is_file_created is False:
            ecc_config = "OFF" if ecc_status == 0 else "ON"
            # log example: 2021_11_15_22_08_25_cuda_trip_half_lava_ECC_OFF_fernando.log
            date = datetime.today()
            date_fmt = date.strftime('%Y_%m_%d_%H_%M_%S')
            self.__filename = f"{self.__log_dir}/{date_fmt}_{self.__test_name}_ECC_{ecc_config}_{self.__hostname}.log"
            # Writing the header to the file
            try:
                with open(self.__filename, "w") as log_file:
                    begin_str = f"#BEGIN Y:{date.year} M:{date.month} D:{date.day} "
                    begin_str += f"Time:{date.hour}:{date.minute}:{date.second}-{date.microsecond}\n"
                    log_file.write(f"#HEADER {self.__test_header}\n")
                    log_file.write(begin_str)
                    self.__is_file_created = True
            except OSError:
                self.__logger.exception(f"Could not create the file {self.__filename}")
                self.__is_file_created = False

    def __call__(self, message: bytes, *args, **kwargs) -> None:
        """ Log a message from the DUT
        :param message: a message is composed of
        <first byte ecc status>
        <2 next bytes size of the message in bytes max 32764>
        <message of maximum 32764 bytes>
        1 byte for ecc + 2 bytes for message length + 32764 maximum message content = 32767 bytes
        """
        endianness = ">" if self.__endianness == "big-endian" else "<"
        ecc_status = int(message[0])
        self.__create_new_file(ecc_status=ecc_status)
        print(message[0:3])

        message_size = struct.unpack(f'{endianness}H', message[1:3])[0]
        message_content = message[3:message_size].decode("ascii")
        with open(self.__filename, "a") as log_file:
            log_file.write(message_content + "\n")


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
            log_dir="/tmp/",
            test_name="DebugTest",
            test_header="Testing DUT_LOGGING",
            hostname="carol",
            endianness="little-endian",
            logger_name="DUT_LOGGING"
        )
        for i in range(100):
            mss_content = f"Testing iteration {i}"
            packed = struct.pack("<H", len(mss_content))
            mss = bytes(0) + packed + mss_content.encode("ascii")
            dut_logging(message=mss)


    debug()
