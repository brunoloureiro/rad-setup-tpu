import collections
import json
import logging
import typing

# Command window execution in seconds
# TODO: Check with Pablo and Daniel if this is static
__COMMAND_WINDOW = 3600


class CommandFactory:
    def __init__(self, json_files_list: list, logger_name: str):
        self.__json_data_list = list()
        self.__logger = logging.getLogger(f"{logger_name}.{__name__}")
        for json_file in json_files_list:
            try:
                with open(json_file) as fp:
                    machine_dict = json.load(fp)
                    # The json files contains a list of dicts
                    self.__json_data_list.extend(machine_dict)
            except FileNotFoundError:
                self.__logger.error(f"Incorrect path for {json_file}, file not found")

        # Transform __json_data_list into a FIFO to manage the codes testing
        self.__cmd_queue = None
        self.__fill_the_queue()

    def __fill_the_queue(self):
        """ Fill or re-fill the command queue
        :return:
        """
        if not self.__cmd_queue:
            self.__logger.debug("Re-filling the queue of commands")
            self.__cmd_queue = collections.deque(self.__json_data_list)

    def get_cmds_and_test_info(self, encode: str = 'ascii') -> typing.Tuple[str, str, str, str]:
        """ Based on the Factory pattern we can build the string taking into consideration how much a cmd already
        executed. For example, if we have 10 configurations on the __json_data_list, then the get_cmd will
        select the one that is currently executing and did not complete __COMMAND_WINDOW time.
        :param encode: encode type, default ascii
        :return: cmd_exec and cmd_kill encoded strings
        """
        # TODO: Check the timestamp of the command (probably a table that saves the it)
        # The following code is not correct
        machine_dict = self.__cmd_queue.pop()
        self.__fill_the_queue()
        cmd_exec = machine_dict["exec"].encode(encoding=encode)
        cmd_kill = machine_dict["killcmd"].encode(encoding=encode)
        code_name, code_header = "", ""
        return cmd_exec, cmd_kill, code_name, code_header


if __name__ == '__main__':
    # TODO: FINISH and DEBUG-ME
    pass
# else:
#     raise NotImplementedError("Please DEBUG-ME FIRST BEFORE INCLUDE IN THE MAIN PROJECT")
