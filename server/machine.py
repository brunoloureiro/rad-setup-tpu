import errno
import logging
import os
import socket
import telnetlib
import threading
import time

import yaml

from command_factory import CommandFactory
from dut_logging import DUTLogging
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

    # Data receive size in bytes
    __DATA_SIZE = 256

    # Num of start app tries
    __MAX_START_APP_TRIES = 4

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
        self.__ip = machine_parameters["ip"]
        self.__diff_reboot = machine_parameters["diff_reboot"]
        self.__switch_ip = machine_parameters["power_switch_ip"]
        self.__switch_port = machine_parameters["power_switch_port"]
        self.__switch_model = machine_parameters["power_switch_model"]
        self.__boot_problem_max_delta = machine_parameters["boot_problem_max_delta"]
        self.__reboot_sleep_time = machine_parameters["power_cycle_sleep_time"]
        self.__max_timeout_time = machine_parameters["max_timeout_time"]
        self.__dut_hostname = machine_parameters["hostname"]
        self.__dut_username = machine_parameters["username"]
        self.__dut_password = machine_parameters["password"]
        self.__receiving_port = machine_parameters["receive_port"]

        # Factory to manage the command execution
        self.__command_factory = CommandFactory(json_files_list=machine_parameters["json_files"],
                                                logger_name=logger_name)

        self.__stop_event = threading.Event()
        self.__dut_log_path = f"{server_log_path}/{self.__dut_hostname}"
        # make sure that the path exists
        if os.path.isdir(self.__dut_log_path) is False:
            os.mkdir(self.__dut_log_path)

        self.__dut_log_message = None
        # Configure the socket
        self.__messages_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.__messages_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.__messages_socket.bind((server_ip, self.__receiving_port))
        self.__messages_socket.settimeout(self.__max_timeout_time)

        super(Machine, self).__init__(*args, **kwargs)

    def __str__(self) -> str:
        return f"IP:{self.__ip} HOSTNAME:{self.__dut_hostname} RECPORT:{self.__receiving_port}"

    def run(self):
        # Run execution of thread
        # lower and upper threshold for reboot interval
        lower_threshold = self.__TIME_MIN_REBOOT_THRESHOLD * self.__diff_reboot
        upper_threshold = self.__TIME_MAX_REBOOT_THRESHOLD * self.__diff_reboot
        # mandatory: It must start the machine on
        turn_on_status = turn_machine_on(address=self.__ip, switch_model=self.__switch_model,
                                         switch_port=self.__switch_port, switch_ip=self.__switch_ip,
                                         logger_name=self.__logger_name)
        if turn_on_status != ErrorCodes.SUCCESS:
            self.__logger.error(f"Failed to turn ON the str(self)")

        # Control logging timestamps for the machine
        last_message_timestamp = time.time()
        # Rebooting timestamp
        last_reboot_timestamp = time.time()
        sequentially_reboots = 0
        # Start the app for the first time
        self.__start_app()
        while self.__stop_event.is_set():
            try:
                data, address = self.__messages_socket.recvfrom(self.__DATA_SIZE)
                self.__dut_log_message(message=data)
                last_message_timestamp = time.time()
            except TimeoutError:
                if lower_threshold <= last_message_timestamp <= upper_threshold:
                    if self.__command_factory.is_command_window_timeout:
                        self.__kill_app()
                elif last_message_timestamp > upper_threshold:
                    # The last connection was too late, reboot the machine
                    if last_reboot_timestamp > self.__diff_reboot:
                        last_reboot_timestamp = self.__reboot_this_machine()
                        sequentially_reboots += 1
                        if sequentially_reboots > self.__MAX_ATTEMPTS_TO_REBOOT:
                            # Then we wait for a long time
                            self.__stop_event.wait(self.__REBOOT_AGAIN_INTERVAL_AFTER_BOOT_PROBLEM)
                            # fake reboot setting to start trying again
                            last_reboot_timestamp = time.time()

                    # Try to start the app again
                    self.__start_app()

    def __telnet_login(self) -> telnetlib.Telnet:
        """Perform login on telnet before one operation
        :return the telnet object
        """
        tn = telnetlib.Telnet(self.__ip, timeout=30)
        tn.read_until(b'ogin: ', timeout=30)
        tn.write(self.__dut_username.encode('ascii') + b'\n')
        tn.read_very_eager()
        if self.__dut_password != "":
            tn.read_until(b'assword: ', timeout=30)
            tn.write(self.__dut_password.encode('ascii') + b'\n')
        tn.read_until(b'$ ', timeout=30)
        return tn

    def __kill_app(self) -> None:
        # try __MAX_START_APP_TRIES times to start the app on the DUT
        for try_i in range(self.__MAX_START_APP_TRIES):
            try:
                tn = self.__telnet_login()
                tn.write(self.__command_factory.current_cmd_kill)
                tn.read_very_eager()
                # Never sleep with time, but with event wait
                self.__stop_event.wait(0.1)
                tn.close()
                # If it reaches here the app is running
                break
            finally:
                self.__logger.info(f"Command execution not successful, trying {try_i}")

    def __start_app(self) -> None:
        """ Start the app on the DUT
        :return:
        """
        # try __MAX_START_APP_TRIES times to start the app on the DUT
        for try_i in range(self.__MAX_START_APP_TRIES):
            try:
                tn = self.__telnet_login()

                # This process is being redesigned to become a Factory
                # The commands are already encoded
                cmd_line_run, cmd_line_pkill, test_name, header = self.__command_factory.get_commands_and_test_info()
                self.__dut_log_message = DUTLogging(log_dir=self.__dut_log_path, test_name=test_name,
                                                    test_header=header, hostname=self.__dut_hostname,
                                                    logger_name=self.__logger_name)
                tn.write(cmd_line_pkill)
                tn.read_very_eager()
                tn.write(cmd_line_run)
                tn.read_very_eager()
                # Never sleep with time, but with event wait
                self.__stop_event.wait(0.1)
                tn.close()
                # If it reaches here the app is running
                break
            except (OSError, EOFError) as e:
                if e.errno == errno.EHOSTUNREACH:
                    self.__logger.exception(f"Host unreachable str(self)")
                self.__logger.exception(
                    f"Wait for a boot and connection from str(self)")
            finally:
                self.__logger.info(f"Command execution not successful, trying {try_i}")

    def join(self, *args, **kwargs) -> None:
        """ Stop the main function before join the thread
        :param args: to be passed to the base class
        :param kwargs: to be passed to the base class
        """
        self.__stop_event.set()
        super(Machine, self).join(*args, **kwargs)

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
        print("CREATING THE MACHINE")
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
            datefmt='%d-%m-%y %H:%M:%S',
            filename="unit_test_log_Machine.log",
            filemode='w'
        )
        machine = Machine(
            configuration_file="machines_cfgs/carolk401.yaml",
            server_ip="192.168.1.5",
            logger_name="MACHINE_LOG",
            server_log_path="/tmp"
        )

        print("EXECUTING THE MACHINE")
        machine.start()
        print(f"SLEEPING THE MACHINE FOR {100}s")
        time.sleep(100)

        print("JOINING THE MACHINE")
        machine.join()

        print("RAGE AGAINST THE MACHINE")


    debug()

# OLD __log method
#     def __log(self, kind: ErrorCodes) -> None:
#         """ Log some Machine behavior
#         :param kind: Error code to be logged
#         """
#         if kind == ErrorCodes.REBOOTING:
#             if self.__reboot_status == ErrorCodes.SUCCESS:
#                 reboot_msg = f"Rebooted IP:{self.__ip}"
#             else:
#                 reboot_msg = f"Reboot failed for IP:{self.__ip}"
#             reboot_msg += f" HOSTNAME:{self.__dut_hostname} STATUS:{self.__reboot_status}"
#             reboot_msg += f" PORT_NUMBER: {self.__switch_port} SWITCH_IP: {self.__switch_ip}"
#             self.__logger.info(reboot_msg)
#         elif kind == ErrorCodes.WAITING_BOOT_PROBLEM:
#             reboot_msg = f"Waiting {self.__boot_problem_max_delta}s due boot problem IP:{self.__ip} "
#             reboot_msg += f"HOSTNAME:{self.__dut_hostname}"
#             self.__logger.info(reboot_msg)
#         elif kind == ErrorCodes.WAITING_FOR_POSSIBLE_BOOT:
#             self.__logger.debug(
#                 f"Waiting for a possible boot in the future from str(self)")
#         elif kind == ErrorCodes.BOOT_PROBLEM:
#             reboot_msg = f"Boot Problem str(self). "
#             reboot_msg += f"The thread will wait for a connection for {self.__boot_problem_max_delta}s"
#             self.__logger.error(reboot_msg)
#         elif kind == ErrorCodes.MAX_SEQ_REBOOT_REACHED:
#             self.__logger.error(
#                 f"Maximum number of reboots allowed reached for str(self)")
#         elif kind == ErrorCodes.TURN_ON:
#             self.__logger.info(
#                 f"Turning ON str(self) STATUS:{self.__reboot_status}")
#         elif kind == ErrorCodes.APP_CRASH:
#             reboot_msg = f"App Restarted IP:{self.__ip}"
#             self.__logger.error(reboot_msg)


# OLD Class declaration
#     def __init__(self,
#                  ip: str, receiving_port: int, diff_reboot: float, hostname: str, power_switch_ip: str,
#                  power_switch_port: int,
#                  power_switch_model: str, logger_name: str, boot_problem_max_delta: float,
#                  power_cycle_sleep_time: float, server_log_path: str,
#                  sdc_data_size: int, max_timeout_time: int, username: str, dut_passwd: str, dut_app_path: str,
#                  exec_code: str,
#                  app_args: str, *args, **kwargs):
#         :param ip: Machine' IP
#         :param receiving_port: port fro receiving messages from the DUT
#         :param diff_reboot: Difference threshold to wait between the connections of the device
#         :param hostname: Hostname of the device
#         :param power_switch_ip: IP address of the power switch that the device is connected
#         :param power_switch_port: Power switch port that the device is connected
#         :param power_switch_model: Model (type/brand) of the power switch
#         :param logger_name: Main logger name to store the logging information
#         :param boot_problem_max_delta: Delta time necessary to take some action after boot problem
#         :param power_cycle_sleep_time: difference between OFF and ON when rebooting
#         :param server_log_path: directory to store the logs for the test
#         :paran sdc_data_size: size of the SDC message
#         :param max_timeout_time: maximum waiting time for messages
#         :param username: DUT username
#         :param dut_passwd: DUT password
#         :param dut_app_path: path where is the application and input files
#         :param exec_code: name the application running
#         :param app_args: arguments for the application running
#         # TODO: CHeck if the approach will use this way of setting the parameters

#     def get_self_ip_address(self):
#
#         ip_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#         try:
#             ip_socket.connect((self.__ip, 1027))
#         except socket.error:
#             return None
#
#         return ip_socket.getsockname()[0]
#
#     def __process_message(self, message) -> None:
# """ Process the last message in the queue
# All messages have 1024B
# The message is organized in the following way
# | 1 byte MessageType | 1023 message content |
# - MessageType is a number 0 to 255, the following types are defined
#     ITERATION_TIME = 1
#     ERROR_DETAIL = 2
#     INFO_DETAIL = 3
#     SDC_END = 4
#     TOO_MANY_ERRORS_PER_ITERATION = 5
#     TOO_MANY_INFOS_PER_ITERATION = 6
#     NORMAL_END = 7
#     SAME_ERROR_LAST_ITERATION = 8
# :return:
# """
# message_type = MessageType(int(message[0]))
# message_content = message[1:]
# if message_type == MessageType.ITERATION_TIME:
#     raise NotImplementedError
# elif message_type == MessageType.ERROR_DETAIL:
#     raise NotImplementedError
# elif message_type == MessageType.INFO_DETAIL:
#     raise NotImplementedError
# elif message_type == MessageType.SDC_END:
#     raise NotImplementedError
# elif message_type == MessageType.TOO_MANY_ERRORS_PER_ITERATION:
#     raise NotImplementedError
# elif message_type == MessageType.TOO_MANY_INFOS_PER_ITERATION:
#     raise NotImplementedError
# elif message_type == MessageType.NORMAL_END:
#     raise NotImplementedError
# elif message_type == MessageType.SAME_ERROR_LAST_ITERATION:
#     raise NotImplementedError
