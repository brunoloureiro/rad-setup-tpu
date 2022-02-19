#!/usr/bin/python3
import logging
import socket
import yaml
from datetime import datetime
from classes.LoggerFormatter import ColoredLogger
from classes.Machine import Machine


def logging_setup(logger_name, log_file):
    """
    Logging setup
    :return: logger
    """
    # create logger with 'spam_application'
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


def init_new_client_on_connection(client_socket: socket.socket, address: str, machines: list) -> Machine:
    """
    Generate the objects for the devices
    :return:
    """
    for mac in machines:
        if mac["enabled"] and address == mac["ip"]:
            mac_obj = Machine(
                ip=mac["ip"],
                diff_reboot=mac["diff_reboot"],
                hostname=mac["hostname"],
                power_switch_ip=mac["power_switch_ip"],
                power_switch_port=mac["power_switch_port"],
                power_switch_model=mac["power_switch_model"],
                client_socket=client_socket
            )
            return mac_obj
    return None


def main():
    """
    Main function
    :return: None
    """
    server_parameters_default_file = "server_parameters.yaml"
    # Store only a day of logs
    now = datetime.now().strftime("%Y_%m_%d")
    server_log_default_file = f"server_{now}.log"
    # log format
    logger = logging_setup(logger_name=__name__, log_file=server_log_default_file)

    # attach signal handler for CTRL + C
    try:
        # load yaml file
        with open(server_parameters_default_file, 'r') as fp:
            server_parameters = yaml.load(fp, Loader=yaml.SafeLoader)

        machines = server_parameters["machines"]
        # Init a dict with all devices
        machines_hash = {mac["ip"]: None for mac in machines}

        # Start the server socket
        # Create an INET, STREAMing socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            # Bind the socket to a public host, and a well-known port
            server_socket.bind((server_parameters["server_ip"], server_parameters["socket_port"]))
            logger.info(f"Server bind to: {server_parameters['server_ip']}")

            # Become a server socket
            # TODO: find the correct value for backlog parameter
            server_socket.listen(15)

            while True:
                client_socket, address = server_socket.accept()
                new_mac = init_new_client_on_connection(client_socket=client_socket, address=address, machines=machines)

                if new_mac:
                    # Check if first there is nothing running on this IP
                    if machines_hash[address]:
                        machines_hash[address].join()
                        del machines_hash[address]
                    else:
                        machines_hash[address] = new_mac
                else:
                    logger.debug(f"Machine with IP: {address} is not on the {server_parameters_default_file}. "
                                 f"Please add it on the machines list")

    except KeyboardInterrupt:

        logger.error("KeyboardInterrupt detected, exiting gracefully!( at least trying :) )")
        exit(130)


if __name__ == '__main__':
    main()
