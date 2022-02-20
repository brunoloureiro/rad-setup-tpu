#!/usr/bin/python3
import argparse
import logging
import os
import typing
import yaml
import socketserver
from logger_formatter import ColoredLogger
from machine import Machine


def logging_setup(logger_name: str, log_file: str) -> logging.Logger:
    """Logging setup
    :return: logger object
    """
    # create logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    # create file handler which logs even debug messages
    fh = logging.FileHandler(log_file, mode='a')
    fh.setLevel(logging.INFO)
    # create formatter and add it to the handlers
    file_formatter = logging.Formatter(fmt='%(asctime)s %(name)s %(levelname)s %(message)s %(filename)s:%(lineno)d',
                                       datefmt='%d-%m-%y %H:%M:%S')

    # add the handlers to the logger
    fh.setFormatter(file_formatter)
    logger.addHandler(fh)

    # create console handler with a higher log level for console
    console = ColoredLogger(logger_name)
    # noinspection PyTypeChecker
    logger.addHandler(console)
    return logger


class UDPHandler(socketserver.BaseRequestHandler):
    """ This class works similar to the TCP handler class, except that
    self.request consists of a pair of data and client socket, and since
    there is no connection the client address must be given explicitly
    when sending data back via sendto().
    extracted from https://docs.python.org/3/library/socketserver.html#socketserver.UDPServer
    """

    def __init__(self, machines: typing.Dict[str, Machine], *args, **kwargs):
        """ Init the UDPHandler
        :param machines: a dictionary that contains all the active machines
        :param args: to be passed to base class
        :param kwargs: to be passed to base class
        """
        super(UDPHandler, self).__init__(*args, **kwargs)
        self.__machines = machines

    def handle(self) -> None:
        """ Handle the data from connections """
        data, socket = self.request
        data = data.strip()
        ip, port = self.client_address
        # TODO: Need to talk with Pablo if it is the best approach
        self.__machines[ip].append_data_on_queue(data=data)


def main():
    """ Main function """
    parser = argparse.ArgumentParser(description='Server to monitor radiation experiments')
    parser.add_argument('--config', metavar='PATH_YAML_FILE', type=str, default="server_parameters.yaml",
                        help='Path to an YAML FILE that contains the server parameters. '
                             'Default is ./server_parameters.yaml')
    args = parser.parse_args()
    # load yaml file
    with open(args.config, 'r') as fp:
        server_parameters = yaml.load(fp, Loader=yaml.SafeLoader)
    socket_port = server_parameters['socket_port']
    server_ip = server_parameters['server_ip']
    hard_reboot_sleep_time = server_parameters['hard_reboot_sleep_time']
    server_log_file = server_parameters['server_log_file']
    server_log_store_dir = server_parameters['server_log_store_dir']
    boot_problem_max_delta = server_parameters['boot_problem_max_delta']

    # log format
    logger_name = __name__
    logger = logging_setup(logger_name=logger_name, log_file=server_log_file)

    # Create a dictionary that will contains all the active Machine threads in the setup
    machines_dict = dict()
    for m in server_parameters["machines"]:
        if m['enabled']:
            dut_log_path = f"{server_log_store_dir}/{m['hostname']}"
            new_machine = Machine(
                ip=m["ip"], diff_reboot=m['diff_reboot'],
                hostname=m['hostname'], power_switch_ip=m['power_switch_ip'],
                power_switch_port=m['power_switch_port'],
                power_switch_model=m['power_switch_model'], logger_name=logger_name,
                boot_problem_max_delta=boot_problem_max_delta,
                power_cycle_sleep_time=hard_reboot_sleep_time, dut_log_path=dut_log_path,
            )
            # If path does not exists create it
            if os.path.isdir(dut_log_path) is False:
                os.mkdir(dut_log_path)
            machines_dict[m["ip"]] = new_machine
            new_machine.start()

    # attach signal handler for CTRL + C
    try:
        # Start the server socket
        with socketserver.UDPServer((server_ip, socket_port), UDPHandler) as server:
            server.serve_forever()
    except KeyboardInterrupt:
        for ip, machine in machines_dict.items():
            logger.info(f"Joining IP {ip}")
            machine.join()

        logger.error("KeyboardInterrupt detected, exiting gracefully!( at least trying :) )")
        exit(130)


if __name__ == '__main__':
    main()
