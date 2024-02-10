import collections
import json
import logging
import time
import typing

_ONE_HOUR_WINDOW = 3600


class CommandFactory:
    def __init__(self, json_files_list: list, logger_name: str, command_window: int = _ONE_HOUR_WINDOW):
        self.__command_window = command_window
        self.__json_data_list = list()
        self.__logger = logging.getLogger(f"{logger_name}.{__name__}")
        for json_file in json_files_list:
            try:
                with open(json_file) as fp:
                    machine_dict = json.load(fp)
                    # The json files contain a list of dicts
                    self.__json_data_list.extend(machine_dict)
            except FileNotFoundError:
                self.__logger.exception(f"Incorrect path for {json_file}, file not found")
                raise

        # Transform __json_data_list into a FIFO to manage the codes testing
        self.__cmd_queue = collections.deque()
        self.__check_and_refill_the_queue()
        self.__current_command = self.__cmd_queue.pop()
        self.__current_command["start_timestamp"] = time.time()

    def __check_and_refill_the_queue(self):
        """ Fill or re-fill the command queue """
        # If self.__cmd_queue is empty re-fill it
        if not self.__cmd_queue:
            self.__logger.info("Re-filling the queue of commands")
            self.__cmd_queue = collections.deque(self.__json_data_list)

    @property
    def is_command_window_timed_out(self):
        """ Only checks if the self.__current_command is outside execute window
        :return:
        """
        now = time.time()
        time_diff = now - self.__current_command["start_timestamp"]
        return time_diff > self.__command_window

    def get_commands_and_test_info(self, encode: str = 'ascii') -> typing.Tuple[bytes, bytes, str, str]:
        """ Based on a Factory pattern we can build the string taking into consideration how much a cmd already
        executed. For example, if we have 10 configurations on the __json_data_list, then the get_cmd will
        select the one that is currently executing and did not complete __command_window time.
        :param encode: encode type, default ascii
        :return: cmd_exec and cmd_kill encoded strings
        """
        self.__check_and_refill_the_queue()

        # verify the timestamp first
        if self.is_command_window_timed_out:
            self.__current_command = self.__cmd_queue.pop()
            self.__current_command["start_timestamp"] = time.time()

        # Following Pablo approach we need to make the process detach from the terminal
        # 'nohup exec_code+...' &\r\n'
        # Just to make sure that not concatenating duplicate
        cmd_exec = self.__current_command["exec"].replace("nohup", "").replace("&\r\n", "")
        cmd_exec = f"nohup {cmd_exec} &\r\n".encode(encoding=encode)

        # Kill does not have nohup and &
        cmd_kill = self.__current_command["killcmd"].replace("nohup", "")
        cmd_kill = f"{cmd_kill} \r\n".encode(encoding=encode)

        code_name = self.__current_command["codename"]
        code_header = self.__current_command["header"]
        return cmd_exec, cmd_kill, code_name, code_header

    @property
    def current_command_cmd_kill(self) -> bytes:
        """ Get the current command kill command line
        """
        cmd_kill = self.__current_command["killcmd"].replace("nohup", "")
        return f"{cmd_kill} \r\n".encode(encoding='ascii')
