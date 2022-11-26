#!/usr/bin/python3
import argparse
import errno
import logging
import os
import signal
import sys
import threading
import traceback

import yaml

from server.logger_formatter import logging_setup
from server.machine import Machine

# Logger name in the main server thread
PARENT_LOGGER_NAME: str = os.path.basename(str(__file__).lower().replace(".py", ""))
# Machine List
MACHINE_LIST: list = list()


def __end_daemon_machines():
    """ General end for all machines """
    logger = logging.getLogger(name=PARENT_LOGGER_NAME)
    logger.info("Stopping all threads")
    for machine in MACHINE_LIST:
        machine.stop()
    logger.info("Waiting for all threads to join")
    for machine in MACHINE_LIST:
        machine.join()


def __machine_thread_exception_handler(args):
    """ It handles the exception on the Machine threads
    The args argument has the following attributes:
    exc_type: Exception type.
    exc_value: Exception value, can be None.
    exc_traceback: Exception traceback, can be None.
    thread: Thread which raised the exception, can be None. """
    logger = logging.getLogger(name=PARENT_LOGGER_NAME)
    exception_str = "".join(
        traceback.format_exception(etype=args.exc_type, value=args.exc_value, tb=args.exc_traceback)
    )
    logger.error(f"Error {exception_str} at Machine thread:{args.thread}")
    # Log the thread that raise the
    __end_daemon_machines()
    sys.exit(errno.ECHILD)


def __ctrlc_handler(signum, frame):
    """ Signal handler to be attached
    """
    logger = logging.getLogger(name=PARENT_LOGGER_NAME)
    logger.error(
        f"KeyboardInterrupt detected, exiting gracefully!( at least trying :) ). signum:{signum} frame:{frame}")
    logger.info("Stopping all threads")
    __end_daemon_machines()
    sys.exit(130)


def main():
    """ Main function """
    # Attach CTRL-C pressing to the function
    signal.signal(signal.SIGINT, __ctrlc_handler)

    # Argument reading
    parser = argparse.ArgumentParser(description='Server to monitor radiation experiments')
    parser.add_argument('-c', '--config', metavar='PATH_YAML_FILE', type=str, default="server_parameters.yaml",
                        help='Path to an YAML FILE that contains the server parameters. '
                             'Default is ./server_parameters.yaml')
    args = parser.parse_args()
    # load yaml file
    with open(args.config, 'r') as fp:
        server_parameters = yaml.load(fp, Loader=yaml.SafeLoader)

    server_log_file = server_parameters['server_log_file']
    server_log_store_dir = server_parameters['server_log_store_dir']
    server_ip = server_parameters['server_ip']

    # log format
    logger = logging_setup(logger_name=PARENT_LOGGER_NAME, log_file=server_log_file)

    # If path does not exist create it
    if os.path.isdir(server_log_store_dir) is False:
        os.mkdir(server_log_store_dir)

    # noinspection SpellCheckingInspection
    # set the exception hook
    threading.excepthook = __machine_thread_exception_handler

    try:
        # Start the server threads
        for m in server_parameters["machines"]:
            if m['enabled']:
                machine = Machine(configuration_file=m["cfg_file"], server_ip=server_ip, logger_name=PARENT_LOGGER_NAME,
                                  server_log_path=server_log_store_dir)

                logger.info(f"Starting a new thread to listen at {machine}")
                machine.start()
                MACHINE_LIST.append(machine)
    except Exception as err:
        logger.exception(f"General exception:{err}")
        __end_daemon_machines()
        # Unknown exit
        sys.exit(-1)


if __name__ == '__main__':
    main()
