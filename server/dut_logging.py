"""
Module to log the info received from the devices
"""
import enum
import logging
import os

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

    def __init__(self, log_dir: str, test_name: str, test_header: str, hostname: str, ecc_config: str = "OFF"):
        """ DUTLogging create the log file and writes the header on the first line
        :param log_dir: directory of the logfile
        :param test_name: Name of the test that will be performed, ex: cuda_lava_fp16, zedboard_lenet_int8, etc.
        :param test_header: Specific characteristics of the test, extracted from the configuration files
        :param hostname: Device hostname
        :param ecc_config: ECC configuration of the memories, can be ON or OFF. Default is OFF
        """
        # log example: 2021_11_15_22_08_25_cuda_trip_half_lava_ECC_OFF_fernando.log
        date = datetime.today()
        date_fmt = date.strftime('%Y_%m_%d_%H_%M_%S')
        self.__filename = f"{log_dir}/{date_fmt}_{test_name}_ECC_{ecc_config}_{hostname}.log"

        # Writing the header to the file
        with open(self.__filename, "w") as log_file:
            begin_str = f"#BEGIN Y:{date.year} M:{date.month} D:{date.day} "
            begin_str += f"Time:{date.hour}:{date.minute}:{date.second}-{date.microsecond}\n"
            log_file.write(f"#HEADER {test_header}\n")
            log_file.write(begin_str)

        # This var will be set to false in case the machine stops responding and a DUE is logged
        self.__test_ending_status = EndStatus.NORMAL_END

    def __del__(self):
        """ Destructor of the class
        Check if the file exists and put an END in the last line
        """
        if os.path.isfile(self.__filename):
            with open(self.__filename, "a") as log_file:
                date_fmt = datetime.today().strftime('%Y-%m-%d-%H-%M-%S')
                log_file.write(f"({date_fmt}) {self.__test_ending_status}")

    @property
    def test_ending_status(self): return self.__test_ending_status

    @test_ending_status.setter
    def test_ending_status(self, ending_status: EndStatus) -> None:
        """ Set the end to the log file
        :param ending_status: Enum that represents the possible endings
        :return: None
        """
        self.__test_ending_status = ending_status

    def log_message(self, message: str):
        # TODO: This must log a message that come from LogHelper
        raise NotImplementedError


if __name__ == '__main__':
    def debug():
        # FOR DEBUG ONLY
        print("CREATING THE MACHINE")
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
            datefmt='%d-%m-%y %H:%M:%S',
            filename="unit_test_log_Machine.log",
            filemode='w'
        )
        dut_logging = DUTLogging(
            log_dir="/tmp/",
            test_name="DebugTest",
            test_header="Testing DUT_LOGGING",
            hostname="carol",
            ecc_config="OFF"
        )

        dut_logging.test_ending_status = EndStatus.POWER_CYCLE

    debug()
