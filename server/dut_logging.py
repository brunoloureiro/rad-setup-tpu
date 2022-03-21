"""
Module to log the info received from the devices
"""
import enum
import logging
from datetime import datetime


class EndStatus(enum.Enum):
    NORMAL_END = "#SERVER_END"
    SOFT_APP_REBOOT = "#SERVER_DUE:soft APP reboot"
    SOFT_OS_REBOOT = "#SERVER_DUE:soft OS reboot"
    HARD_REBOOT = "#SERVER_DUE:power cycle"
    UNKNOWN = "#SERVER_UNKNOWN"

    def __str__(self):
        return self.value

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

    def __create_file_if_does_not_exist(self, ecc_status: str):
        if self.__filename is None:
            # log example: 2021_11_15_22_08_25_cuda_trip_half_lava_ECC_OFF_fernando.log
            date = datetime.today()
            date_fmt = date.strftime('%Y_%m_%d_%H_%M_%S')
            log_filename = f"{self.__log_dir}/{date_fmt}_{self.__test_name}_ECC_{ecc_status}_{self.__hostname}.log"
            # Writing the header to the file
            try:
                with open(log_filename, "w") as log_file:
                    begin_str = f"#SERVER_BEGIN Y:{date.year} M:{date.month} D:{date.day} "
                    begin_str += f"TIME:{date.hour}:{date.minute}:{date.second}-{date.microsecond}\n"
                    log_file.write(f"#SERVER_HEADER {self.__test_header}\n")
                    log_file.write(begin_str)
                    self.__filename = log_filename
            except (OSError, PermissionError):
                self.__logger.exception(f"Could not create the file {log_filename}")

    def __call__(self, message: bytes, *args, **kwargs) -> None:
        """ Log a message from the DUT
        :param message: a message is composed of
        <first byte ecc status>
        On file_writer defined as:
        #define ECC_ENABLED 0xE
        #define ECC_DISABLED 0xD
        <message of maximum 1023 bytes>
        1 byte for ecc + 1023 maximum message content = 1024 bytes
        """
        ecc_values = {0xD: "OFF", 0xE: "ON"}
        ecc_status = ecc_values[message[0]]
        self.__create_file_if_does_not_exist(ecc_status=ecc_status)
        message_content = message[1:].decode("ascii")

        if self.__filename:
            with open(self.__filename, "a") as log_file:
                message_content += "\n" if "\n" not in message_content else ""
                log_file.write(message_content)
        else:
            self.__logger.exception("[ERROR in __call__(message) Unable to open file]")

    def finish_this_dut_log(self, end_status: EndStatus):
        """ Check if the file exists and put an END in the last line
        :param end_status status of the ending of the log EndStatus
        """
        if self.__filename:
            with open(self.__filename, "a") as log_file:
                date_fmt = datetime.today().strftime('%Y-%m-%d-%H-%M-%S')
                log_file.write(f"{end_status} TIME:{date_fmt}\n")
                self.__filename = None

    def __del__(self):
        # If it is not finished it should
        if self.__filename:
            self.finish_this_dut_log(end_status=EndStatus.UNKNOWN)

    @property
    def log_filename(self):
        return self.__filename
