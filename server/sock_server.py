#!/usr/bin/python3
import logging
import yaml
import zmq
import time
from server.logger_formatter import ColoredLogger


def logging_setup(logger_name: str, log_file: str) -> logging.Logger:
    """Logging setup
    :return: logger object
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
        context = zmq.Context()
        socket = context.socket(zmq.REP)
        socket.bind("tcp://*:5555")

        while True:
            #  Wait for next request from client
            message = socket.recv()
            print(f"Received request: {message}")

            #  Do some 'work'
            time.sleep(1)

            #  Send reply back to client
            # socket.send_string("World")
    except KeyboardInterrupt:

        logger.error("KeyboardInterrupt detected, exiting gracefully!( at least trying :) )")
        exit(130)


if __name__ == '__main__':
    main()
