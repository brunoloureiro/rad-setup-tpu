import errno
import logging
import os
import socket
import telnetlib
import threading
import time

import yaml

from command_factory import CommandFactory
from dut_logging import DUTLogging, EndStatus
from error_codes import ErrorCodes
from reboot_machine import reboot_machine, turn_machine_on
from logger_formatter import logging_setup


class Machine(threading.Thread):
    """ Machine Thread
    do not change the machine constants unless you
    really know what you are doing, most of the constants
    describes the behavior of HARD reboot execution
    """
    __MAX_REBOOT_THRESHOLD_TIMES = 3

    # Data receive size in bytes
    __DATA_SIZE = 256

    # Num of start app tries
    __MAX_START_APP_TRIES = 4
    __MAX_KILL_APP_TRIES = 4

    # Max attempts to reboot the device
    __MAX_ATTEMPTS_TO_REBOOT = 6

    def __init__(self, configuration_file: str, server_ip: str, logger_name: str, server_log_path: str, *args,
                 **kwargs):
        """ Initialize a new thread that represents a setup machine
        :param configuration_file: YAML file that contains all information from that specific Device Under Test (DUT)
        :param server_ip: IP of the server
        :param logger_name: Main logger name to store the logging information
        :param server_log_path: directory to store the logs for the test
        :param *args: args that will be passed to threading.Thread
        :param *kwargs: kwargs that will be passed to threading.Thread
        """
        self.__logger_name = f"{logger_name}.{__name__}"
        self.__logger = logging.getLogger(self.__logger_name)
        self.__logger.info("Creating a new Machine thread")

        # load yaml file
        with open(configuration_file, 'r') as fp:
            machine_parameters = yaml.load(fp, Loader=yaml.SafeLoader)
        self.__dut_ip = machine_parameters["ip"]
        self.__dut_hostname = machine_parameters["hostname"]
        self.__dut_username = machine_parameters["username"]
        self.__dut_password = machine_parameters["password"]

        self.__diff_reboot = machine_parameters["diff_reboot"]
        self.__switch_ip = machine_parameters["power_switch_ip"]
        self.__switch_port = machine_parameters["power_switch_port"]
        self.__switch_model = machine_parameters["power_switch_model"]
        self.__boot_problem_max_delta = machine_parameters["boot_problem_max_delta"]
        self.__reboot_sleep_time = machine_parameters["power_cycle_sleep_time"]
        self.__max_timeout_time = machine_parameters["max_timeout_time"]
        self.__receiving_port = machine_parameters["receive_port"]

        # Factory to manage the command execution
        self.__command_factory = CommandFactory(json_files_list=machine_parameters["json_files"],
                                                logger_name=logger_name)

        self.__stop_event = threading.Event()
        self.__dut_log_path = f"{server_log_path}/{self.__dut_hostname}"
        # make sure that the path exists
        if os.path.isdir(self.__dut_log_path) is False:
            os.mkdir(self.__dut_log_path)

        self.__dut_logging_obj = None
        # Configure the socket
        self.__messages_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.__messages_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.__messages_socket.bind((server_ip, self.__receiving_port))
        self.__messages_socket.settimeout(self.__max_timeout_time)

        super(Machine, self).__init__(*args, **kwargs)

    def __str__(self) -> str:
        return f"IP:{self.__dut_ip} HOSTNAME:{self.__dut_hostname} RECPORT:{self.__receiving_port}"

    def run(self):
        # Run execution of thread
        # mandatory: It must start the machine on
        turn_on_status = turn_machine_on(address=self.__dut_ip, switch_model=self.__switch_model,
                                         switch_port=self.__switch_port, switch_ip=self.__switch_ip,
                                         logger_name=self.__logger_name)
        if turn_on_status != ErrorCodes.SUCCESS:
            self.__logger.error(f"Failed to turn ON the {self}")

        sequentially_reboots = 0
        # Start the app for the first time
        self.__start_app()
        while self.__stop_event.is_set():
            try:
                data, address = self.__messages_socket.recvfrom(self.__DATA_SIZE)
                self.__dut_logging_obj(message=data)
                sequentially_reboots = 0
                if self.__command_factory.is_command_window_timeout:
                    self.__soft_reboot(end_status=EndStatus.NORMAL_END)
                self.__logger.debug(f"Connection from {self}")
            except TimeoutError:
                soft_reboot_status = self.__soft_reboot(end_status=EndStatus.TIMEOUT)
                if soft_reboot_status != ErrorCodes.SUCCESS:
                    self.__hard_reboot()
                    sequentially_reboots += 1
                    if sequentially_reboots > self.__MAX_ATTEMPTS_TO_REBOOT:
                        # We turn off for __REBOOT_AGAIN_INTERVAL_AFTER_BOOT_PROBLEM seconds
                        self.__power_cycle_machine(self.__boot_problem_max_delta)
                        sequentially_reboots = 0

    def __telnet_login(self) -> telnetlib.Telnet:
        """Perform login on telnet before one operation
        :return the telnet object
        """
        tn = telnetlib.Telnet(self.__dut_ip, timeout=30)
        tn.read_until(b'ogin: ', timeout=30)
        tn.write(self.__dut_username.encode('ascii') + b'\n')
        tn.read_very_eager()
        tn.read_until(b'assword: ', timeout=30)
        tn.write(self.__dut_password.encode('ascii') + b'\n')
        tn.read_until(b'$ ', timeout=30)
        return tn

    def __kill_app(self) -> ErrorCodes:
        """ Try to kill the app on the host
        :return: If the kill was successful or not
        """
        for try_i in range(self.__MAX_KILL_APP_TRIES):
            try:
                tn = self.__telnet_login()
                tn.write(self.__command_factory.current_cmd_kill)
                tn.read_very_eager()
                # Never sleep with time, but with event wait
                self.__stop_event.wait(0.1)
                tn.close()
                # If it reaches here the app is not running anymore
                return ErrorCodes.SUCCESS
            finally:
                self.__logger.info(f"Kill app execution not successful, trying {try_i}")
        return ErrorCodes.CONNECTION_ERROR

    def __start_app(self) -> ErrorCodes:
        """ Start the app on the DUT
        :return: If the start was successful or not
        """
        # try __MAX_START_APP_TRIES times to start the app on the DUT
        for try_i in range(self.__MAX_START_APP_TRIES):
            try:
                tn = self.__telnet_login()

                # This process is being redesigned to become a Factory
                # The commands are already encoded
                cmd_line_run, test_name, header = self.__command_factory.get_commands_and_test_info()
                # Delete the current dut logging obj
                del self.__dut_logging_obj
                self.__dut_logging_obj = DUTLogging(log_dir=self.__dut_log_path, test_name=test_name,
                                                    test_header=header, hostname=self.__dut_hostname,
                                                    logger_name=self.__logger_name)
                tn.write(cmd_line_run)
                tn.read_very_eager()
                # Never sleep with time, but with event wait
                self.__stop_event.wait(0.1)
                tn.close()
                # If it reaches here the app is running
                self.__logger.info(f"Command execution successful, trying {try_i}")
                return ErrorCodes.SUCCESS
            except (OSError, EOFError) as e:
                if e.errno == errno.EHOSTUNREACH:
                    self.__logger.exception(f"Host unreachable str(self)")
                self.__logger.exception(
                    f"Wait for a boot and connection ConnectionRefusedError USER:{self.__dut_username} "
                    f"HOSTNAME:{self.__dut_hostname} IP:{self.__dut_ip}")

            self.__logger.info(f"Command execution not successful, trying {try_i}")
        return ErrorCodes.CONNECTION_ERROR

    def __hard_reboot(self):
        """HARD REBOOT OF THE MACHINE HERE"""
        last_reboot_timestamp = self.__power_cycle_machine(reboot_sleep_time=self.__reboot_sleep_time)
        self.__dut_logging_obj.finish_this_dut_log(end_status=EndStatus.POWER_CYCLE)
        # Wait for the diff_reboot then try to start the app again
        self.__stop_event.wait(self.__diff_reboot)
        self.__start_app()
        return last_reboot_timestamp

    def __soft_reboot(self, end_status: EndStatus) -> ErrorCodes:
        """ SOFT REBOOT HERE
            THE KILL APP WILL MAKE THE LOGGING ENDING BASED ON THE EndStatus
        :param end_status:
        """
        self.__dut_logging_obj.finish_this_dut_log(end_status=end_status)
        self.__kill_app()
        return self.__start_app()

    def join(self, *args, **kwargs) -> None:
        """ Stop the main function before join the thread
        :param args: to be passed to the base class
        :param kwargs: to be passed to the base class
        """
        self.__stop_event.set()
        super(Machine, self).join(*args, **kwargs)

    def __power_cycle_machine(self, reboot_sleep_time: float) -> float:
        """ reboot the device based on reboot_machine module
        :return reboot_status
        """
        last_reboot_timestamp = time.time()
        # Reboot machine in another thread
        off_status, on_status = reboot_machine(address=self.__dut_ip,
                                               switch_model=self.__switch_model,
                                               switch_port=self.__switch_port,
                                               switch_ip=self.__switch_ip,
                                               rebooting_sleep=reboot_sleep_time,
                                               logger_name=self.__logger_name,
                                               thread_event=self.__stop_event)

        reboot_msg = f"Rebooted"
        reboot_status = ErrorCodes.SUCCESS
        if off_status != ErrorCodes.SUCCESS or on_status != ErrorCodes.SUCCESS:
            reboot_msg = f"Reboot failed for"
            reboot_status = off_status if off_status != ErrorCodes.SUCCESS else on_status
        reboot_msg += f" str(self) STATUS:{reboot_status}"
        reboot_msg += f" PORT_NUMBER: {self.__switch_port} SWITCH_IP: {self.__switch_ip}"
        self.__logger.info(reboot_msg)
        return last_reboot_timestamp


if __name__ == '__main__':
    def debug():
        # FOR DEBUG ONLY
        logger = logging_setup(logger_name="MACHINE_LOG", log_file="unit_test_log_Machine.log")
        logger.debug("DEBUGGING THE MACHINE")
        machine = Machine(
            configuration_file="../machines_cfgs/carolk401.yaml",
            server_ip="131.254.160.174",
            logger_name="MACHINE_LOG",
            server_log_path="/tmp"
        )

        logger.debug("EXECUTING THE MACHINE")
        machine.start()
        logger.debug(f"SLEEPING THE MACHINE FOR {500}s")
        time.sleep(500)

        logger.debug("JOINING THE MACHINE")
        machine.join()

        logger.debug("RAGE AGAINST THE MACHINE")


    debug()
