import errno
import logging
import os
import socket
import subprocess
import telnetlib
import threading
import time
from typing import Optional

import yaml

from .command_factory import CommandFactory
from .dut_logging import DUTLogging, EndStatus
from .error_codes import ErrorCodes
from .reboot_machine import reboot_machine, turn_machine_on


class Machine(threading.Thread):
    """ Machine Thread
    Each machine is attached to one Device Under Test (DUT),
    it basically controls the status of the device and monitor it.
    Do not change the machine constants unless you
    really know what you are doing, most of the constants
    describe the behavior of HARD reboot execution
    """
    # Wait time to see if the board returns, 1800 = half an hour
    __LONG_REBOOT_WAIT_TIME_AFTER_PROBLEM = 1800
    # Data receive size in bytes
    __DATA_SIZE = 4096
    # Num of start app tries
    __MAX_TELNET_TRIES = 4
    # Max attempts to reboot the device
    __MAX_SEQUENTIALLY_HARD_REBOOTS = 6
    __MAX_SEQUENTIALLY_SOFT_APP_REBOOTS = 3
    __MAX_SEQUENTIALLY_SOFT_OS_REBOOTS = 3

    # Time in seconds between the POWER switch OFF and ON
    # Smaller intervals are too dangerous ChipIR 12/2022
    __POWER_SWITCH_DEFAULT_TIME_REST = 4
    __READ_EAGER_TIMEOUT = 1
    __BOOT_PING_TIMEOUT = 2

    # This time is just to make the OS start the rebooting process;
    # otherwise the next ping will be successful, right after sudo reboot command
    __WAIT_AFTER_SOFT_OS_REBOOT_TIME = 5

    # Possible connection string
    __ALL_POSSIBLE_CONNECTION_TYPES = [  # Add more if necessary
        '#IT', '#HEADER', '#BEGIN', '#END', '#INF', '#ERR', "#SDC", "#ABORT"
    ]

    def __init__(self, configuration_file: str, server_ip: str, logger_name: str, server_log_path: str,
                 *args, **kwargs):
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
        self.__logger.info(f"Creating a new Machine thread for IP {server_ip}")
        self.__stop_event = threading.Event()

        # load yaml file
        with open(configuration_file, 'r') as fp:
            machine_parameters = yaml.load(fp, Loader=yaml.SafeLoader)
        self.__dut_ip = machine_parameters["ip"]
        self.__dut_hostname = machine_parameters["hostname"]
        self.__dut_username = machine_parameters["username"]
        self.__dut_password = machine_parameters["password"]
        self.__switch_ip = machine_parameters["power_switch_ip"]
        self.__switch_port = machine_parameters["power_switch_port"]
        self.__switch_model = machine_parameters["power_switch_model"]
        self.__boot_waiting_time = machine_parameters["boot_waiting_time"]
        self.__max_timeout_time = machine_parameters["max_timeout_time"]
        self.__receiving_port = machine_parameters["receive_port"]
        self.__disable_os_soft_reboot = False
        if "disable_os_soft_reboot" in machine_parameters:
            self.__disable_os_soft_reboot = machine_parameters["disable_os_soft_reboot"] is True

        # Factory to manage the command execution
        self.__command_factory = CommandFactory(json_files_list=machine_parameters["json_files"],
                                                logger_name=logger_name)

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

        # Variables to control rebooting (soft app and soft OS) process
        self.__soft_app_reboot_count = 0
        self.__soft_os_reboot_count = 0
        self.__hard_reboot_count = 0

        super(Machine, self).__init__(*args, **kwargs)

    def __str__(self) -> str:
        dut_str = f"IP:{self.__dut_ip} USERNAME:{self.__dut_username} "
        dut_str += f"HOSTNAME:{self.__dut_hostname} RECPORT:{self.__receiving_port}"
        return dut_str

    def run(self):
        # Run execution of thread
        # mandatory: It must start the machine on (do not change to reboot, ON is the correct config)
        turn_on_status = turn_machine_on(address=self.__dut_ip, switch_model=self.__switch_model,
                                         switch_port=self.__switch_port, switch_ip=self.__switch_ip,
                                         logger_name=self.__logger_name)
        if turn_on_status != ErrorCodes.SUCCESS:
            self.__logger.error(f"Failed to turn ON the {self}")

        # Wait and start the app for the first time
        self.__wait_for_booting()
        self.__soft_app_reboot()
        while self.__stop_event.is_set() is False:
            try:
                data, address = self.__messages_socket.recvfrom(self.__DATA_SIZE)
                self.__dut_logging_obj(message=data)
                data_decoded = data.decode("ascii")[1:]
<<<<<<< HEAD
                connection_type_str = f"UNKNOWN_CONNECTION_TYPE:{data_decoded[0:10]}"
=======
                connection_type_str = "UnknownConn:" + data_decoded[:10]
>>>>>>> 6ed280c (Fix bug: now the hard_reboot_counter is reset after the Machine thread receives an #IT connection)
                for substring in self.__ALL_POSSIBLE_CONNECTION_TYPES:
                    # It must start from the 1, as the 0 is the ECC defining byte
                    if data_decoded.startswith(substring):
                        connection_type_str = substring
                        break

                # TO AVOID making sequential reboot when receiving good data,
                # This is necessary to fix the behavior when a device keeps crashing for multiple times
                # in a short period, but eventually comes to life again
                if connection_type_str == "#IT":
                    self.__soft_app_reboot_count = 0
                    self.__hard_reboot_count = 0

                self.__logger.debug(f"{connection_type_str} - Connection from {self}")

                if self.__command_factory.is_command_window_timed_out:
                    self.__logger.info(
                        f"Benchmark exceeded the command execution window, executing another one now on {self}.")
                    self.__soft_app_reboot(previous_log_end_status=EndStatus.NORMAL_END)
            except (TimeoutError, socket.timeout):
                # Soft app reboot
                soft_app_reboot_status = self.__soft_app_reboot(previous_log_end_status=EndStatus.SOFT_APP_REBOOT)
                if soft_app_reboot_status == ErrorCodes.SUCCESS:
                    continue
                # Soft OS reboot
                soft_os_reboot = self.__soft_os_reboot()
                if soft_os_reboot == ErrorCodes.SUCCESS:
                    self.__soft_app_reboot(previous_log_end_status=EndStatus.SOFT_OS_REBOOT)
                    continue
                # Finally, the Power cycle Hard reboot
                self.__hard_reboot()
                self.__soft_app_reboot(previous_log_end_status=EndStatus.HARD_REBOOT)

    def __telnet_login(self) -> telnetlib.Telnet:
        """ Return a telnet session
        :return:
        """
        tn = telnetlib.Telnet(self.__dut_ip, timeout=self.__max_timeout_time)

        if not tn.read_until(b'ogin: ', timeout=self.__max_timeout_time):
            raise RuntimeError("Telnet error: Failed to login into Telnet. Could not input username.")
        tn.write(self.__dut_username.encode('ascii') + b'\n')
        tn.read_very_eager()

        if not tn.read_until(b'assword: ', timeout=self.__max_timeout_time):
            raise RuntimeError("Telnet error: Could not login into Telnet. Could not input password.")
        tn.write(self.__dut_password.encode('ascii') + b'\n')

        if not tn.read_until(b'$ ', timeout=self.__max_timeout_time):
            raise RuntimeError("Telnet error: Could not login into Telnet. Failed after trying to enter inputs.")

        self.__logger.debug("Successfully logged into Telnet.")
        return tn

    def __soft_app_reboot(self, previous_log_end_status: EndStatus = None) -> ErrorCodes:
        """ kill and start an app on the device
        :previous_log_end_status: if it is not the first time that the device will run an app,
        then pass the end_status, otherwise leave it None
        :return: If the start was successful or not
        """
        if self.__stop_event.is_set():
            return ErrorCodes.THREAD_EVENT_IS_SET

        if previous_log_end_status is None and self.__dut_logging_obj is not None:
            self.__logger.exception(
                f"INCORRECT CONFIGURATION: previous_ending_status is None and __dut_logging_obj is Not None - {self}")
            raise

        if self.__soft_app_reboot_count >= self.__MAX_SEQUENTIALLY_SOFT_APP_REBOOTS:
            self.__logger.info(f"MAXIMUM_APP_REBOOT_REACHED on {self}")
            return ErrorCodes.MAXIMUM_APP_REBOOT_REACHED

        # First check if there is an app running
        self.__logger.info(f"TRYING SOFT APP REBOOT (app kill and run again/start first time) on {self}")

        # self.__command_factory produces the commands that will be executed
        # The commands are already encoded
        cmd_line_run, cmd_kill, test_name, header = self.__command_factory.get_commands_and_test_info()
        # try __MAX_START_APP_TRIES times to start the app on the DUT
        for try_i in range(self.__MAX_TELNET_TRIES):
            # All loops must stop after the event is set
            if self.__stop_event.is_set():
                break
            try:
                with self.__telnet_login() as tn:
                    # Kill first
                    tn.write(cmd_kill)
                    tn.read_very_eager()
                    # Never sleep with time, but with event
                    self.__stop_event.wait(self.__READ_EAGER_TIMEOUT)
                    # Execute the command
                    tn.write(cmd_line_run)
                    tn.read_very_eager()
                    # Never sleep with time, but with event
                    self.__stop_event.wait(self.__READ_EAGER_TIMEOUT)
                    # If it reaches here, the app is running
                    self.__logger.info(f"SUCCESSFULLY SEND THE SOFT REBOOT CMDS:{cmd_kill} "
                                       f"COUNTER:{self.__soft_app_reboot_count} "
                                       f"TRY:{try_i} on {self} CMDEXEC={cmd_line_run[:10]}...")
                    # Close the DUTLogging only if there is a log file open
                    if self.__dut_logging_obj:
                        self.__dut_logging_obj.finish_this_dut_log(end_status=previous_log_end_status)
                    # Delete the current dut logging obj
                    del self.__dut_logging_obj
                    self.__dut_logging_obj = DUTLogging(log_dir=self.__dut_log_path, test_name=test_name,
                                                        test_header=header, hostname=self.__dut_hostname,
                                                        logger_name=self.__logger_name)
                self.__soft_app_reboot_count += 1
                return ErrorCodes.SUCCESS
            except OSError as e:
                if e.errno == errno.EHOSTUNREACH:
                    self.__logger.error(f"Host unreachable {self} ")
                    return ErrorCodes.HOST_UNREACHABLE
            except RuntimeError as e:
                self.__logger.error(f"{e} {self}")
                return ErrorCodes.TELNET_CONNECTION_ERROR
            except EOFError:
                self.__logger.info(f"Command execution not successful TRY:{try_i} on {self}")
        return ErrorCodes.TELNET_CONNECTION_ERROR

    def __wait_for_booting(self):
        current_timestamp = time.time()
        start_timestamp = current_timestamp
        while (current_timestamp - start_timestamp) <= self.__boot_waiting_time:
            # All loops must stop after the event is set
            if self.__stop_event.is_set():
                break
            # Pinging the board
            try:
                subprocess.check_output(["ping", "-c", "1", self.__dut_ip], timeout=self.__BOOT_PING_TIMEOUT)
                # Try to see if the telnet login is indeed possible
                tn = self.__telnet_login()
                tn.close()
                self.__logger.info(f"Boot ping successful {self}")
                return ErrorCodes.SUCCESS
                # return ErrorCodes.SUCCESS
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
                self.__logger.error(f"Boot ping failed {self} error:{e}")
            except (OSError, EOFError, RuntimeError) as e:
                self.__logger.error(f"Telnet conn failed {self} error:{e}")
                if isinstance(e, OSError) and e.errno == errno.ECONNREFUSED:
                    # When connection is refused, it crashes instantaneously
                    self.__stop_event.wait(self.__BOOT_PING_TIMEOUT)
            current_timestamp = time.time()

        return ErrorCodes.HOST_UNREACHABLE

    def __soft_os_reboot(self):
        """ SOFT OS REBOOT: Reboot the operating system, or try to reboot using telnet
            THE KILL APP WILL MAKE THE LOGGING ENDING BASED ON THE EndStatus
        """
        if self.__stop_event.is_set():
            return ErrorCodes.THREAD_EVENT_IS_SET

        if self.__disable_os_soft_reboot is True:
            return ErrorCodes.DISABLED_SOFT_OS_REBOOT

        if self.__soft_os_reboot_count >= self.__MAX_SEQUENTIALLY_SOFT_OS_REBOOTS:
            self.__logger.info(f"MAXIMUM_OS_REBOOT_REACHED on {self}")
            return ErrorCodes.MAXIMUM_OS_REBOOT_REACHED

        self.__logger.info(f"Trying to perform a soft Operating System reboot (OS reboot and run app) on {self}")
        default_os_reboot_cmd = b"sudo /sbin/reboot\r\n"
        # for try_i in range(self.__MAX_TELNET_TRIES):
        try:
            with self.__telnet_login() as tn:
                # OS reboot
                tn.write(default_os_reboot_cmd)
                tn.read_very_eager()
                self.__stop_event.wait(self.__READ_EAGER_TIMEOUT)

            self.__logger.info(f"SUCCESSFUL OS REBOOT:{default_os_reboot_cmd} "
                               f"COUNTER:{self.__soft_os_reboot_count} on {self}")
            # This time is just to make the OS start the rebooting process;
            # otherwise the next ping will be successful, right after sudo reboot command
            self.__stop_event.wait(self.__WAIT_AFTER_SOFT_OS_REBOOT_TIME)
            # Wait the machine to boot
            self.__wait_for_booting()
            # Reset the soft app reboot as the system will be rebooted
            self.__soft_app_reboot_count = 0
            self.__soft_os_reboot_count += 1
            # return self.__soft_app_reboot(previous_log_end_status=EndStatus.SOFT_OS_REBOOT)
            return ErrorCodes.SUCCESS
        except (OSError, EOFError, RuntimeError) as e:
            self.__logger.error(f"Soft OS reboot not successful {self} - {e}")
            if isinstance(e, OSError) and e.errno == errno.EHOSTUNREACH:
                self.__logger.error(f"Host unreachable {self} ")
                return ErrorCodes.HOST_UNREACHABLE
            return ErrorCodes.TELNET_CONNECTION_ERROR

    def __hard_reboot(self):
        """ reboot the device based on reboot_machine module
        :return reboot_status
        """
        if self.__stop_event.is_set():
            return ErrorCodes.THREAD_EVENT_IS_SET

        reboot_sleep_time = self.__POWER_SWITCH_DEFAULT_TIME_REST
        if self.__hard_reboot_count > self.__MAX_SEQUENTIALLY_HARD_REBOOTS:
            # We turn off the device for __LONG_REBOOT_WAIT_TIME_AFTER_PROBLEM seconds
            reboot_sleep_time = self.__LONG_REBOOT_WAIT_TIME_AFTER_PROBLEM
            self.__hard_reboot_count = 0
        else:
            self.__hard_reboot_count += 1

        self.__logger.info(
            f"Trying to perform a hard reboot on device (power cycle). Sleep interval is {reboot_sleep_time} on {self}")
        off_status, on_status = reboot_machine(address=self.__dut_ip,
                                               switch_model=self.__switch_model,
                                               switch_port=self.__switch_port,
                                               switch_ip=self.__switch_ip,
                                               rebooting_sleep=reboot_sleep_time,
                                               logger_name=self.__logger_name,
                                               thread_event=self.__stop_event)
        reboot_msg = f"HARD REBOOT FOR - {self} POWER_SWITCH_PORT_NUMBER:{self.__switch_port} "
        reboot_msg += f"COUNTER:{self.__hard_reboot_count} SWITCH_IP:{self.__switch_ip}"
        if off_status != ErrorCodes.SUCCESS or on_status != ErrorCodes.SUCCESS:
            reboot_msg += f" failed. ON_STATUS:{on_status} OFF_STATUS:{off_status}"
            self.__logger.error(reboot_msg)
        else:
            self.__logger.info(reboot_msg + " finished.")
        # Wait the machine to boot
        self.__wait_for_booting()
        # Reset the soft app and the soft os reboot as the system will be hard rebooted
        self.__soft_app_reboot_count = 0
        self.__soft_os_reboot_count = 0

    def join(self, timeout: Optional[float] = None) -> None:
        self.__logger.info(f"Joining Machine {self}.")
        # FIXME: This method is taking too much time, needs improvement

        # # Test if the board is alive
        # # Pinging the board
        # try:
        #     subprocess.check_output(["ping", "-c", "1", self.__dut_ip], timeout=self.__BOOT_PING_TIMEOUT)
        #     with self.__telnet_login() as tn:
        #         # Kill first
        #         tn.write(self.__command_factory.current_command_cmd_kill)
        #         tn.read_very_eager()
        # except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        #     self.__logger.error(f"Ping failed while trying to join the thread {self} error:{e}")
        # except (OSError, EOFError, RuntimeError) as e:
        #     self.__logger.error(f"Unsuccessful kill command after Machine thread joining on {self} - {e}")

        super(Machine, self).join(timeout)

    def stop(self) -> None:
        """ Stop the main function before join the thread """
        self.__stop_event.set()
