import threading
import time
import logging
import queue

from dut_logging import DUTLogging, MessageType
from error_codes import ErrorCodes
from reboot_machine import reboot_machine, turn_machine_on


class Machine(threading.Thread):
    """ Machine Thread
    do not change the machine constants unless you
    really know what you are doing, most of the constants
    describes the behavior of HARD reboot execution
    """
    __TIME_MIN_REBOOT_THRESHOLD = 3
    __TIME_MAX_REBOOT_THRESHOLD = 10
    __REBOOT_AGAIN_INTERVAL_AFTER_BOOT_PROBLEM = 3600

    def __init__(self,
                 ip: str, diff_reboot: float, hostname: str, power_switch_ip: str, power_switch_port: int,
                 power_switch_model: str, logger_name: str, boot_problem_max_delta: float,
                 power_cycle_sleep_time: float, dut_log_path: str,
                 *args, **kwargs):
        """ Initialize a new thread that represents a setup machine
        :param ip: Machine' IP
        :param diff_reboot: Difference threshold to wait between the connections of the device
        :param hostname: Hostname of the device
        :param power_switch_ip: IP address of the power switch that the device is connected
        :param power_switch_port: Power switch port that the device is connected
        :param power_switch_model: Model (type/brand) of the power switch
        :param logger_name: Main logger name to store the logging information
        :param boot_problem_max_delta: Delta time necessary to take some action after boot problem
        :param power_cycle_sleep_time: difference between OFF and ON when rebooting
        :param dut_log_path: directory to store the logs for the test
        # TODO: CHeck if the approach will use this way of setting the parameters
        """
        self.__ip = ip
        self.__diff_reboot = diff_reboot
        self.__hostname = hostname
        self.__switch_ip = power_switch_ip
        self.__switch_port = power_switch_port
        self.__switch_model = power_switch_model
        self.__logger_name = logger_name
        self.__boot_problem_max_delta = boot_problem_max_delta
        self.__reboot_sleep_time = power_cycle_sleep_time
        self.__timestamp = time.time()
        self.__logger = logging.getLogger(self.__logger_name)
        self.__stop_event = threading.Event()
        self.__reboot_status = ErrorCodes.SUCCESS
        self.__dut_log_path = dut_log_path
        self.__data_queue = queue.Queue()

        self.__dut_log_obj = None
        super(Machine, self).__init__(*args, **kwargs)

    def run(self):
        """ Run execution of thread
        """
        # lower and upper threshold for reboot interval
        lower_threshold = self.__TIME_MIN_REBOOT_THRESHOLD * self.__diff_reboot
        upper_threshold = self.__TIME_MAX_REBOOT_THRESHOLD * self.__diff_reboot
        # mandatory: It must start the machine on
        turn_machine_on(address=self.__ip, switch_model=self.__switch_model, switch_port=self.__switch_port,
                        switch_ip=self.__switch_ip, logger_name=self.__logger_name)
        # TODO: Refactor this code to manage the new setup
        #       The following behaviors must be present here:
        #           - The Machine class must control the DUT logging that is being received from the network
        #           - Create a log obj of DUTLogging in the first connection from a device
        #           - At the destruction of the class or stop of the server the Machine MUST close all log files
        #           - Control if the machine stopped or is still working
        while self.__stop_event.is_set():
            # TODO: Check if the queue is empty
            if self.__data_queue.not_empty:
                # There are logs to process
                self.__process_message()
            else:
                raise NotImplementedError("Check the TODO on Machine class")
                # TODO: Check if machine is working fine
                #       Wait for the logging connection

    def join(self, *args, **kwargs) -> None:
        """ Stop the main function before join the thread
        :param args: to be passed to the base class
        :param kwargs: to be passed to the base class
        """
        self.__stop_event.set()
        super(Machine, self).join(*args, **kwargs)

    def __process_message(self) -> None:
        """ Process the last message in the queue
        All messages have 1024B
        The message is organized in the following way
        | 1 byte MessageType | 1023 message content |
        - MessageType is a number 0 to 255, the following types are defined
            CREATE_HEADER = 0
            ITERATION_TIME = 1
            ERROR_DETAIL = 2
            INFO_DETAIL = 3
            SDC_END = 4
            TOO_MANY_ERRORS_PER_ITERATION = 5
            TOO_MANY_INFOS_PER_ITERATION = 6
            NORMAL_END = 7
            SAME_ERROR_LAST_ITERATION = 8
        :return:
        """
        message = self.__data_queue.get()
        message_type = MessageType(int(message[0]))
        message_content = message[1:]
        if message_type == MessageType.CREATE_HEADER:
            self.__dut_log_obj = DUTLogging(log_dir=self.__dut_log_path,
                                            test_name="None", test_header=message_content,
                                            hostname=self.__hostname, ecc_config="OFF")
            raise NotImplementedError

        elif message_type == MessageType.ITERATION_TIME:
            raise NotImplementedError
        elif message_type == MessageType.ERROR_DETAIL:
            raise NotImplementedError
        elif message_type == MessageType.INFO_DETAIL:
            raise NotImplementedError
        elif message_type == MessageType.SDC_END:
            raise NotImplementedError
        elif message_type == MessageType.TOO_MANY_ERRORS_PER_ITERATION:
            raise NotImplementedError
        elif message_type == MessageType.TOO_MANY_INFOS_PER_ITERATION:
            raise NotImplementedError
        elif message_type == MessageType.NORMAL_END:
            raise NotImplementedError
        elif message_type == MessageType.SAME_ERROR_LAST_ITERATION:
            raise NotImplementedError

    def append_data_on_queue(self, data: str) -> None:
        """ TODO: Need to talk with Pablo if it is the best approach
        :param data: Data received from the device
        :return: None
        """
        self.__data_queue.put(data)

    def __log(self, kind: ErrorCodes) -> None:
        """ Log some Machine behavior
        :param kind: Error code to be logged
        """
        if kind == ErrorCodes.REBOOTING:
            if self.__reboot_status == ErrorCodes.SUCCESS:
                reboot_msg = f"Rebooted IP:{self.__ip}"
            else:
                reboot_msg = f"Reboot failed for IP:{self.__ip}"
            reboot_msg += f" HOSTNAME:{self.__hostname} STATUS:{self.__reboot_status}"
            reboot_msg += f" PORT_NUMBER: {self.__switch_port} SWITCH_IP: {self.__switch_ip}"
            self.__logger.info(reboot_msg)
        elif kind == ErrorCodes.WAITING_BOOT_PROBLEM:
            reboot_msg = f"Waiting {self.__boot_problem_max_delta}s due boot problem IP:{self.__ip} "
            reboot_msg += f"HOSTNAME:{self.__hostname}"
            self.__logger.info(reboot_msg)
        elif kind == ErrorCodes.WAITING_FOR_POSSIBLE_BOOT:
            self.__logger.debug(
                f"Waiting for a possible boot in the future from IP:{self.__ip} HOSTNAME:{self.__hostname}")
        elif kind == ErrorCodes.BOOT_PROBLEM:
            reboot_msg = f"Boot Problem IP:{self.__ip} HOSTNAME:{self.__hostname}. "
            reboot_msg += f"The thread will wait for a connection for {self.__boot_problem_max_delta}s"
            self.__logger.error(reboot_msg)
        elif kind == ErrorCodes.MAX_SEQ_REBOOT_REACHED:
            self.__logger.error(
                f"Maximum number of reboots allowed reached for IP:{self.__ip} HOSTNAME:{self.__hostname}")
        elif kind == ErrorCodes.TURN_ON:
            self.__logger.info(f"Turning ON IP:{self.__ip} HOSTNAME:{self.__hostname} STATUS:{self.__reboot_status}")

    def __reboot_this_machine(self) -> float:
        """ reboot the device based on reboot_machine module
        :return reboot_status
        """
        last_reboot_timestamp = time.time()
        # Reboot machine in another thread
        off_status, on_status = reboot_machine(address=self.__ip,
                                               switch_model=self.__switch_model,
                                               switch_port=self.__switch_port,
                                               switch_ip=self.__switch_ip,
                                               rebooting_sleep=self.__reboot_sleep_time,
                                               logger_name=self.__logger_name)
        self.__reboot_status = ErrorCodes.SUCCESS
        if off_status != ErrorCodes.SUCCESS:
            self.__reboot_status = off_status
        if on_status != ErrorCodes.SUCCESS:
            self.__reboot_status = on_status
        return last_reboot_timestamp


if __name__ == '__main__':
    # FOR DEBUG ONLY
    # from RebootMachine import RebootMachine

    print("CREATING THE MACHINE")
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
        datefmt='%d-%m-%y %H:%M:%S',
        filename="unit_test_log_Machine.log",
        filemode='w'
    )
    machine = Machine(
        ip="127.0.0.1",
        diff_reboot=1,
        hostname="test",
        power_switch_ip="127.0.0.1",
        power_switch_port=1,
        power_switch_model="lindy",
        logger_name="MACHINE_LOG",
        boot_problem_max_delta=10,
        power_cycle_sleep_time=2,
        dut_log_path="/tmp"
    )

    print("EXECUTING THE MACHINE")
    machine.start()
    print(f"SLEEPING THE MACHINE FOR {100}s")
    time.sleep(100)

    print("JOINING THE MACHINE")
    machine.join()

    print("RAGE AGAINST THE MACHINE")
