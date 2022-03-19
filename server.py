#!/usr/bin/python3
import argparse
import os

import yaml

from server.logger_formatter import logging_setup
from server.machine import Machine


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

    server_log_file = server_parameters['server_log_file']
    server_log_store_dir = server_parameters['server_log_store_dir']
    server_ip = server_parameters['server_ip']

    # log format
    logger_name = os.path.basename(str(__file__).lower().replace(".py", ""))
    logger = logging_setup(logger_name=logger_name, log_file=server_log_file)

    # If path does not exist create it
    if os.path.isdir(server_log_store_dir) is False:
        os.mkdir(server_log_store_dir)

    # Create a dictionary that will contain all the active Machine threads in the setup
    machines_dict = list()

    # attach signal handler for CTRL + C
    try:
        # Start the server threads
        for m in server_parameters["machines"]:
            if m['enabled']:
                machine = Machine(configuration_file=m["cfg_file"], server_ip=server_ip, logger_name=logger_name,
                                  server_log_path=server_log_store_dir)

                logger.info(f"Starting a new thread to listen at {machine}")
                machine.start()

    except KeyboardInterrupt:
        logger.info("Joining all threads")
        for machine in machines_dict:
            machine.join()

        logger.error("KeyboardInterrupt detected, exiting gracefully!( at least trying :) )")
        exit(130)


if __name__ == '__main__':
    main()
