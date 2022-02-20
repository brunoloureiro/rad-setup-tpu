"""
Module to log the info received from the devices
"""
import enum
import os

from datetime import datetime

END_STATUS = dict(
    NORMAL_END="#END",
    SAME_ERROR_LAST_ITERATION="#ABORT: amount of errors equals of the last iteration",
    TOO_MANY_ERRORS="#ABORT: too many errors per iteration",
    SYSTEM_CRASH="#DUE: system crash",
    POWER_CYCLE="#DUE: power cycle",
)


class MessageType(enum.IntEnum):
    """ Message types defined for the communication """
    CREATE_HEADER = 0
    ITERATION_TIME = 1
    ERROR_DETAIL = 2
    INFO_DETAIL = 3
    SDC_END = 4
    TOO_MANY_ERRORS_PER_ITERATION = 5
    TOO_MANY_INFOS_PER_ITERATION = 6
    NORMAL_END = 7
    SAME_ERROR_LAST_ITERATION = 8

    # Method to perform to string
    def __str__(self) -> str: return str(self.name)
    # Representation is the same as to string
    def __repr__(self) -> str: return str(self)


class DUTLogging:
    """ Device Under Test (DUT) logging class.
    This class will replace the local log procedure that
    each device used to perform in the past.
    """

    def __init__(self, log_dir: str, test_name: str, test_header: str, hostname: str, ecc_config: str = "OFF"):
        """ DUTLogging create the log file and writes the header on the first line
        :param log_dir: directory of the logfile
        :param test_name: Name of the test that will be perform, ex: cuda_lava_fp16, zedboard_lenet_int8, etc.
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
        self.__test_ending_status = END_STATUS["NORMAL_END"]

    def __del__(self):
        """ Destructor of the class
        Check if the file exists and put an END in the last line
        """
        if os.path.isfile(self.__filename):
            with open(self.__filename, "a") as log_file:
                date_fmt = datetime.today().strftime('%Y-%m-%d-%H-%M-%S')
                log_file.write(f"({date_fmt}) {self.__test_ending_status}")

    def set_end_status(self, ending_status: str = END_STATUS["NORMAL_END"]) -> None:
        """ Set the end to the log file
        :param ending_status: Enum that represents the possible endings
        :return: None
        """
        self.__test_ending_status = ending_status

    def log_test_iteration(self, iteration_detail: str):
        # TODO: This method must log one iteration of the test
        #       Must contains the execution time of the kernel, error count, SDC count
        raise NotImplementedError

    def log_error_detail(self, error_detail: str):
        # TODO: This method must log the error_detail received from a device
        raise NotImplementedError

    def log_int_detail(self, info_detail: str):
        # TODO: This method must log the info_detail received from a device
        raise NotImplementedError
