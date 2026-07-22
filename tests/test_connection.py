import logging
import os
import socket
import threading
import time

import yaml


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

        # # Factory to manage the command execution
        # self.__command_factory = CommandFactory(json_files_list=machine_parameters["json_files"],
        #                                         logger_name=logger_name)

        self.__dut_log_path = f"{server_log_path}/{self.__dut_hostname}"
        # make sure that the path exists
        if not os.path.isdir(self.__dut_log_path):
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
        self.__logger.info(f"Created a new Machine thread: {self}")
        super(Machine, self).__init__(*args, **kwargs)

    def stop(self) -> None:
        """ Stop the main function before join the thread """
        self.__stop_event.set()

    def __str__(self) -> str:
        dut_str = f"IP:{self.__dut_ip} USERNAME:{self.__dut_username} "
        dut_str += f"HOSTNAME:{self.__dut_hostname} RECPORT:{self.__receiving_port}"
        return dut_str

    def run(self):
        # Run execution of thread
        # mandatory: It must start the machine on (do not change to reboot, ON is the correct config)
        # turn_on_status = turn_machine_on(address=self.__dut_ip, switch_model=self.__switch_model,
        #                                  switch_port=self.__switch_port, switch_ip=self.__switch_ip,
        #                                  logger_name=self.__logger_name)
        # if turn_on_status != ErrorCodes.SUCCESS:
        #     self.__logger.error(f"Failed to turn ON the {self}")

        # # Wait and start the app for the first time
        # self.__wait_for_booting()
        # self.__soft_app_reboot()
        while not self.__stop_event.is_set():
            try:
                data, address = self.__messages_socket.recvfrom(self.__DATA_SIZE)
                # self.__logger.debug(data)
                data_decoded = data.decode("ascii")[1:]
                connection_type_str = "UnknownConn:" + data_decoded[:10]
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

                # if self.__command_factory.is_command_window_timed_out:
                #     self.__logger.info(
                #         f"Benchmark exceeded the command execution window, executing another one now on {self}.")
                #     self.__soft_app_reboot(previous_log_end_status=EndStatus.NORMAL_END)
            except (TimeoutError, socket.timeout):
                self.__logger.error(f"Timeout while connecting to {self.__dut_ip}")
                # # Soft app reboot
                # soft_app_reboot_status = self.__soft_app_reboot(previous_log_end_status=EndStatus.SOFT_APP_REBOOT)
                # if soft_app_reboot_status == ErrorCodes.SUCCESS:
                #     continue
                # # Soft OS reboot
                # soft_os_reboot = self.__soft_os_reboot()
                # if soft_os_reboot == ErrorCodes.SUCCESS:
                #     self.__soft_app_reboot(previous_log_end_status=EndStatus.SOFT_OS_REBOOT)
                #     continue
                # # Finally, the Power cycle Hard reboot
                # self.__hard_reboot()
                # self.__soft_app_reboot(previous_log_end_status=EndStatus.HARD_REBOOT)


def debug():
    logger = logging.getLogger(name="MACHINE_LOG")
    logger.debug("DEBUGGING THE MACHINE")
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    fmt = logging.Formatter(fmt='%(asctime)s %(name)s %(levelname)s %(message)s %(filename)s:%(lineno)d',
                      datefmt='%d-%m-%y %H:%M:%S')
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    server_log_path = "logs"
    machine = Machine(
        configuration_file="../machines_cfgs/carola20001.yaml",
        server_ip="192.168.192.79",
        logger_name="MACHINE_LOG",
        server_log_path=server_log_path
    )

    logger.debug("EXECUTING THE MACHINE")
    machine.start()
    logger.debug(f"SLEEPING THE MACHINE FOR {200}s")
    time.sleep(200)

    logger.debug("JOINING THE MACHINE")
    machine.stop()
    machine.join()
    logger.debug("RAGE AGAINST THE MACHINE")


if __name__ == '__main__':
    debug()
