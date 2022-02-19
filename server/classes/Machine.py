import threading
import time
import logging

from .RebootMachine import RebootMachine
from .ErrorCodes import ErrorCodes


class Machine(threading.Thread):
    """
    Machine Thread
    do not change the machine constants unless you
    really know what you are doing, most of the constants
    describes the behavior of HARD reboot execution
    """
    __TIME_MIN_REBOOT_THRESHOLD = 3
    __TIME_MAX_REBOOT_THRESHOLD = 10
    __REBOOT_AGAIN_INTERVAL_AFTER_BOOT_PROBLEM = 3600

    def __init__(self, *args, **kwargs):
        """
        Initialize a new thread that represents a setup machine
        :param args: None
        :param ip:
        :param diff_reboot:
        :param hostname:
        :param power_switch_ip:
        :param power_switch_port:
        :param power_switch_model:
        :param boot_problem_max_delta:
        :param client_socket:
        """
        self.__ip = kwargs["ip"]
        self.__diff_reboot = kwargs["diff_reboot"]
        self.__hostname = kwargs["hostname"]
        self.__switch_ip = kwargs["power_switch_ip"]
        self.__switch_port = kwargs["power_switch_port"]
        self.__switch_model = kwargs["power_switch_model"]
        self.__boot_problem_max_delta = kwargs["boot_problem_max_delta"]
        self.__reboot_sleep_time = kwargs["reboot_sleep_time"]
        self.__client_socket = kwargs["client_socket"]

        self.__logger_name = __name__
        self.__timestamp = time.time()
        self.__logger = logging.getLogger(self.__logger_name)
        self.__stop_event = threading.Event()
        self.__reboot_status = ErrorCodes.SUCCESS

        super(Machine, self).__init__(*args, **kwargs)

    def run(self):
        """
        Run execution of thread
        :return:
        """
        # lower and upper threshold for reboot interval
        lower_threshold = self.__TIME_MIN_REBOOT_THRESHOLD * self.__diff_reboot
        upper_threshold = self.__TIME_MAX_REBOOT_THRESHOLD * self.__diff_reboot
        # mandatory: It must start the machine on
        self.__turn_machine_on()

        while not self.__stop_event.isSet():
            pass

    def __log(self, kind, reboot_message=None):
        """
        Log some behavior
        :param kind:
        :return:
        """
        reboot_msg = ""
        logger_function = self.__logger.info
        if kind == ErrorCodes.REBOOTING:
            if self.__reboot_status == ErrorCodes.SUCCESS:
                reboot_msg = f"Rebooted IP:{self.__ip}"
            else:
                reboot_msg = f"Reboot failed for IP:{self.__ip}"
                logger_function = self.__logger.error
            reboot_msg += f" HOSTNAME:{self.__hostname} STATUS:{self.__reboot_status}"
            reboot_msg += f" PORT_NUMBER: {self.__switch_port} SWITCH_IP: {self.__switch_ip}"
            if reboot_message:
                reboot_msg += f" WHY: {reboot_message}"
        elif kind == ErrorCodes.WAITING_BOOT_PROBLEM:
            reboot_msg = f"Waiting {self.__boot_problem_max_delta}s due boot problem IP:{self.__ip} "
            reboot_msg += f"HOSTNAME:{self.__hostname}"
        elif kind == ErrorCodes.WAITING_FOR_POSSIBLE_BOOT:
            reboot_msg = f"Waiting for a possible boot in the future from IP:{self.__ip} HOSTNAME:{self.__hostname}"
            logger_function = self.__logger.debug
        elif kind == ErrorCodes.BOOT_PROBLEM:
            reboot_msg = f"Boot Problem IP:{self.__ip} HOSTNAME:{self.__hostname}. "
            reboot_msg += f"The thread will wait for a connection for {self.__boot_problem_max_delta}s"
            logger_function = self.__logger.error
        elif kind == ErrorCodes.MAX_SEQ_REBOOT_REACHED:
            reboot_msg = f"Maximum number of reboots allowed reached for IP:{self.__ip} HOSTNAME:{self.__hostname}"
            logger_function = self.__logger.error
        elif kind == ErrorCodes.TURN_ON:
            reboot_msg = f"Turning ON IP:{self.__ip} HOSTNAME:{self.__hostname} STATUS:{self.__reboot_status}"

        logger_function(reboot_msg)
        # TODO: finish enqueue process
        # message = {"msg": msg, "ip": self.__ip, "status": self.__reboot_status, "kind": kind}
        # self.__queue.put(message)

    def __reboot_this_machine(self):
        """
        reboot the device based on RebootMachine class
        :return reboot_status
        :return: last_last_reboot_timestamp
        when the last reboot was performed
        """
        last_reboot_timestamp = time.time()
        # Reboot machine in another thread
        reboot_thread = RebootMachine(machine_address=self.__ip,
                                      switch_model=self.__switch_model,
                                      switch_port=self.__switch_port,
                                      switch_ip=self.__switch_ip,
                                      rebooting_sleep=self.__reboot_sleep_time,
                                      logger_name=self.__logger_name)
        reboot_thread.start()
        reboot_thread.join()
        self.__reboot_status = reboot_thread.reboot_status

        return last_reboot_timestamp

    def __turn_machine_on(self):
        """
        Turn on the machine
        :return:
        """
        reboot_thread = RebootMachine(machine_address=self.__ip,
                                      switch_model=self.__switch_model,
                                      switch_port=self.__switch_port,
                                      switch_ip=self.__switch_ip,
                                      rebooting_sleep=self.__reboot_sleep_time,
                                      logger_name=self.__logger_name)
        self.__log(ErrorCodes.TURN_ON)
        reboot_thread.on()
        self.__reboot_status = reboot_thread.reboot_status

    def join(self, *args, **kwargs):
        """
        Set if thread should stops or not
        :return:
        """
        # self.__is_machine_active = False
        self.__stop_event.set()
        super(Machine, self).join(*args, **kwargs)


if __name__ == '__main__':
    pass
