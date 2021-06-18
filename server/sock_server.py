#!/usr/bin/python3
import socket
import logging
import yaml

from classes.LoggerFormatter import ColoredLogger


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


def main():
    """
    Main function
    :return: None
    """
    # log format
    logger = logging_setup(logger_name=__name__, log_file="server.log")

    # load yaml file
    with open("server_parameters.yaml", 'r') as fp:
        server_parameters = yaml.load(fp, Loader=yaml.SafeLoader)

    # attach signal handler for CTRL + C
    try:
        # Start the server socket
        # Create an INET, STREAMing socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            # Bind the socket to a public host, and a well-known port
            server_ip, socket_port = server_parameters["server_ip"], server_parameters["socket_port"]
            server_socket.bind((server_ip, socket_port))
            logger.info(f"Server bind to: {server_ip}")

            # Accept connections from outside
            client_socket, address_list = server_socket.accept()

            # Close the connection
            client_socket.close()
    except KeyboardInterrupt:

        logger.error("KeyboardInterrupt detected, exiting gracefully!( at least trying :) )")
        exit(130)


if __name__ == '__main__':
    main()
