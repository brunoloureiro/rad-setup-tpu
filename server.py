#!/usr/bin/python3
import argparse
import errno
import logging
import os
import signal
import sys
import threading
import time
import traceback
import typing

import yaml

from server.command_cli import InteractiveCommandCLI
from server.logger_formatter import logging_setup
from server.machine import Machine
from server.print_manager import ConsoleCursesManager

# Logger name in the main server thread
PARENT_LOGGER_NAME: str = os.path.basename(str(__file__).lower().replace(".py", ""))

# Those global variables are necessary to stop all the threads when an exception is raised
# Machine List
MACHINE_LIST: list = list()
CONSOLE_CURSES_MANAGER: typing.Optional[ConsoleCursesManager] = None
INTERACTIVE_CLI: typing.Optional[InteractiveCommandCLI] = None

THREAD_JOIN_TIMEOUT: float = 1.0

# Default for server_parameters.yaml's optional 'cli_shutdown_confirm_delay' - see
# _decide_sigint_action/__ctrlc_handler below.
_DEFAULT_CLI_SHUTDOWN_CONFIRM_DELAY_SECONDS = 5.0
_cli_shutdown_confirm_delay_seconds: float = _DEFAULT_CLI_SHUTDOWN_CONFIRM_DELAY_SECONDS
# Set to time.time() the moment a Ctrl+C actually stops the interactive CLI (see
# __ctrlc_handler) - None means that has not happened yet (e.g. --enable_curses runs no CLI at
# all, or the CLI already exited on its own, such as stdin EOF, rather than via Ctrl+C).
_cli_stopped_at: typing.Optional[float] = None


def __end_daemon_machines():
    # FIXME: This does not work when the end is before the threads are not started yet
    """ General end for all machines """
    logger = logging.getLogger(name=PARENT_LOGGER_NAME)
    logger.info("Stopping all threads")
    for machine in MACHINE_LIST:
        machine.stop()
    logger.info("Waiting for all threads to join")
    for machine in MACHINE_LIST:
        machine.join(timeout=THREAD_JOIN_TIMEOUT)

    if INTERACTIVE_CLI is not None:
        INTERACTIVE_CLI.stop()
        INTERACTIVE_CLI.join(timeout=THREAD_JOIN_TIMEOUT)

    if CONSOLE_CURSES_MANAGER is not None:
        CONSOLE_CURSES_MANAGER.stop()
        CONSOLE_CURSES_MANAGER.join()


def __machine_thread_exception_handler(args: threading.ExceptHookArgs):
    """ It handles the exception on the Machine threads
    The args argument has the following attributes:
    exc_type: Exception type --> DEPRECATED after Python 3.10, the value is ignored
    exc_value: Exception value can be None.
    exc_traceback: Exception trace-back can be None.
    thread: Thread, which raised the exception, can be None. """
    # FIXME: some exceptions are problematic as not all attributes are available
    logger = logging.getLogger(name=PARENT_LOGGER_NAME)
    exception_str = "".join(
        traceback.format_exception(args.exc_type, value=args.exc_value, tb=args.exc_traceback)
    )
    logger.error(f"Error {exception_str} at Machine thread:{args.thread}")
    # Log the thread that raises the exception
    __end_daemon_machines()
    sys.exit(errno.ECHILD)


def _decide_sigint_action(cli_alive: bool, cli_stopped_at: typing.Optional[float], now: float,
                          confirm_delay: float) -> str:
    """ Pure decision logic behind __ctrlc_handler's two-stage Ctrl+C behavior, kept side-effect
    -free specifically so it can be unit-tested without touching real signals, threads, or
    sys.exit() - see tests/test_server_ctrlc.py.

    :param cli_alive: whether the interactive CLI thread is currently running
    :param cli_stopped_at: time.time() of the Ctrl+C that stopped the CLI, or None if that has
        not happened yet
    :param now: time.time() at the moment of this SIGINT
    :param confirm_delay: minimum seconds required between stopping the CLI and a further Ctrl+C
        being allowed to actually stop the server (server_parameters.yaml's
        'cli_shutdown_confirm_delay', default 5.0) - guards against an accidental double press
        ending the whole experiment by mistake
    :return: one of "stop_cli", "ignore", "shutdown"
    """
    if cli_alive:
        return "stop_cli"
    if cli_stopped_at is not None and (now - cli_stopped_at) < confirm_delay:
        return "ignore"
    return "shutdown"


def __ctrlc_handler(signum, frame):
    """ Signal handler to be attached.

    First stops the interactive CLI (see command_cli.py), if one is running, rather than the
    whole server: an operator sitting at the terminal mid radiation experiment must not be able
    to end the entire run with a single reflexive Ctrl+C. Only a *further* Ctrl+C stops the
    server - and even then only once at least _cli_shutdown_confirm_delay_seconds have passed
    since the CLI was stopped, to guard against an accidental double press doing the same thing
    by mistake (see OPERATOR_COMMANDS.md). --enable_curses runs have no CLI to stop, so a single
    Ctrl+C there still shuts down immediately, exactly as before this feature existed.
    """
    global _cli_stopped_at
    logger = logging.getLogger(name=PARENT_LOGGER_NAME)

    cli_alive = INTERACTIVE_CLI is not None and INTERACTIVE_CLI.is_alive()
    action = _decide_sigint_action(cli_alive=cli_alive, cli_stopped_at=_cli_stopped_at,
                                   now=time.time(), confirm_delay=_cli_shutdown_confirm_delay_seconds)

    if action == "stop_cli":
        logger.warning(f"Ctrl+C: stopping the interactive CLI (server keeps running) - press "
                       f"Ctrl+C again after {_cli_shutdown_confirm_delay_seconds:.0f}s to stop "
                       f"the whole server")
        INTERACTIVE_CLI.stop()
        _cli_stopped_at = time.time()
        return

    if action == "ignore":
        logger.warning("Ctrl+C ignored (too soon after stopping the CLI) - press again to stop the server")
        return

    logger.error(
        f"KeyboardInterrupt detected, exiting gracefully!( at least trying :) ). signum:{signum} frame:{frame}")
    logger.info("Stopping all threads")
    __end_daemon_machines()
    sys.exit(130)


def main():
    """ Main function """
    # The First thing is to guarantee that python >=3.10 is running
    if sys.version_info.major < 3 or sys.version_info.minor < 10:
        raise ValueError("Python 3.10 or greater required")

    # Attach CTRL-C pressing to the function
    signal.signal(signal.SIGINT, __ctrlc_handler)

    # Argument reading
    parser = argparse.ArgumentParser(description='Server to monitor radiation experiments')
    parser.add_argument('-c', '--config', metavar='PATH_YAML_FILE', type=str, default="server_parameters.yaml",
                        help='Path to an YAML FILE that contains the server parameters. '
                             'Default is ./server_parameters.yaml')
    parser.add_argument('--enable_curses', default=False, action="store_true", help='Enable curses display')
    args = parser.parse_args()
    # load yaml file
    with open(args.config, 'r') as fp:
        server_parameters = yaml.load(fp, Loader=yaml.SafeLoader)

    server_log_file = server_parameters['server_log_file']
    server_log_store_dir = server_parameters['server_log_store_dir']
    server_ip = server_parameters['server_ip']

    global _cli_shutdown_confirm_delay_seconds
    _cli_shutdown_confirm_delay_seconds = server_parameters.get(
        "cli_shutdown_confirm_delay", _DEFAULT_CLI_SHUTDOWN_CONFIRM_DELAY_SECONDS)

    # log in the stdout
    global CONSOLE_CURSES_MANAGER
    if args.enable_curses is True:
        CONSOLE_CURSES_MANAGER = ConsoleCursesManager(daemon=True)
        CONSOLE_CURSES_MANAGER.start()

    logger = logging_setup(logger_name=PARENT_LOGGER_NAME, log_file=server_log_file, enable_curses=args.enable_curses)
    logger.info(f"Python version: {sys.version_info.major}.{sys.version_info.minor} machine:{server_ip}")

    # If a path does not exist, create it
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

    # Interactive operator command CLI (see command_cli.py) - only in plain (non-curses) mode:
    # curses.initscr() owns the terminal display, and this CLI's own stdin reading is not
    # compatible with it (see InteractiveCommandCLI's docstring).
    if args.enable_curses is False:
        global INTERACTIVE_CLI
        INTERACTIVE_CLI = InteractiveCommandCLI(machines=MACHINE_LIST, logger_name=PARENT_LOGGER_NAME)
        INTERACTIVE_CLI.start()


if __name__ == '__main__':
    main()
