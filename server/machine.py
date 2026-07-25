import errno
import logging
import os
import subprocess
import threading
import time
import enum
from typing import Optional

import yaml

from .command_factory import CommandFactory
from .dut_commands import DUTCommand, DUTCommandDispatcher
from .dut_connection import DUTConnection, create_dut_connection
from .dut_deployment import DEFAULT_REDEPLOY_TIMEOUT, redeploy_dut
from .dut_logging import DUTLogging, EndStatus
from .dut_message_channel import MessageChannel, create_message_channel
from .error_codes import ErrorCodes
from .reboot_machine import reboot_machine, turn_machine_on


class PossibleMessages(enum.Enum):
    LOGFILE = "#LOGFILE"
    IT = "#IT"
    HEADER = "#HEADER"
    BEGIN = "#BEGIN"
    END = "#END"
    INF = "#INF"
    ERR = "#ERR"
    SDC = "#SDC"
    ABORT = "#ABORT"
    CMD = "#CMD"
    POWER_CYCLE_REQUEST = "#INF POWER_CYCLE_REQUEST"
    UNKNOWN = "UNKNOWN CONNECTION"

    @classmethod
    def get_message_type(cls, log_string: str) -> enum.Enum:
        for m in cls:
            if m.value in log_string:
                if m.POWER_CYCLE_REQUEST.value in log_string:
                    return m.POWER_CYCLE_REQUEST
                return m
        return cls.UNKNOWN

    def __str__(self):
        return str(self.value)


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
    # Num of start app tries
    __MAX_LOGIN_TRIES = 4
    # Default connection_type when a machine config does not specify one: this is the axis that
    # selects how the server listens for DUT status/log messages (#IT, #LOGFILE, #CMD, ...) -
    # "ethernet" (a UDP socket) or "jtag" (the JTAG probe's serial/UART bridge). It is independent
    # of dut_mode below (see dut_message_channel.py / dut_deployment.py).
    __DEFAULT_CONNECTION_TYPE = "ethernet"
    __SUPPORTED_CONNECTION_TYPES = ("ethernet", "jtag")
    # Default baud rate for the JTAG serial/UART bridge when a machine config does not specify one
    __DEFAULT_JTAG_BAUDRATE = 115200
    # Default dut_mode when a machine config does not specify one: an OS-enabled DUT driven by
    # console (Telnet) kill+run commands. "passive" is the bare-metal counterpart: no console/
    # shell, the app runs automatically once (re)loaded - see dut_deployment.py. Independent of
    # connection_type above.
    __DEFAULT_DUT_MODE = "active"
    __SUPPORTED_DUT_MODES = ("active", "passive")
    # Default receive_port when a machine config does not specify one: 0 lets the OS pick a free
    # ephemeral port. Only meaningful to omit for a "jtag" connection_type, which never listens on
    # a UDP socket at all.
    __DEFAULT_RECEIVE_PORT = 0
    # Default test_header for a passive DUT configured without 'json_files' (see 'test_name' below)
    __DEFAULT_TEST_HEADER = ""
    # Default delay between receiving a '#ABORT'/'#END' message and restarting the app, unless
    # overridden per-DUT via 'restart_interval'
    __DEFAULT_RESTART_INTERVAL = 1.0
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
        self.__dut_hostname = machine_parameters["hostname"]
        self.__switch_ip = machine_parameters["power_switch_ip"]
        self.__switch_port = machine_parameters["power_switch_port"]
        self.__switch_model = machine_parameters["power_switch_model"]
        self.__boot_waiting_time = machine_parameters["boot_waiting_time"]
        self.__max_timeout_time = machine_parameters["max_timeout_time"]
        self.__disable_os_soft_reboot = False
        if "disable_os_soft_reboot" in machine_parameters:
            self.__disable_os_soft_reboot = machine_parameters["disable_os_soft_reboot"] is True

        # dut_mode selects how the app is (re)started: "active" (default) DUTs run an OS and are
        # driven by Telnet console kill+run commands; "passive" (bare-metal) DUTs have no
        # console/shell and start their app automatically once it is (re)loaded, via the
        # configured 'redeploy_cmd' (see dut_deployment.py). This is independent of
        # connection_type below - e.g. a passive DUT can still report status over Ethernet if it
        # has a working network stack (see machines_cfgs/versal_bm_eth_passive.yaml).
        self.__dut_mode = machine_parameters.get("dut_mode", self.__DEFAULT_DUT_MODE).lower()
        if self.__dut_mode not in self.__SUPPORTED_DUT_MODES:
            raise ValueError(f"Unsupported dut_mode '{self.__dut_mode}', expected one of "
                             f"{self.__SUPPORTED_DUT_MODES}")

        # ip/username/password: only needed for the Telnet console login (kill+run commands, and
        # the boot-time ping check - see __dut_login/__wait_for_booting), which only ever happens
        # for "active" DUTs. Optional/unused for "passive" (bare-metal) DUTs.
        self.__dut_ip = machine_parameters.get("ip")
        self.__dut_username = machine_parameters.get("username")
        self.__dut_password = machine_parameters.get("password")
        if self.__dut_mode == "active":
            if not self.__dut_ip:
                raise ValueError("dut_mode 'active' requires 'ip' to be set in the machine config")
            if self.__dut_username is None or self.__dut_password is None:
                raise ValueError("dut_mode 'active' requires 'username' and 'password' to be set "
                                 "in the machine config")
        elif self.__dut_username is None:
            # "passive" DUTs never log into a Telnet console, so username is only ever used for
            # informational purposes (e.g. __str__ below) - default it to hostname rather than
            # requiring it to be redundantly set in the config.
            self.__dut_username = self.__dut_hostname

        # connection_type selects how the server listens for DUT status/log messages (#IT,
        # #LOGFILE, #CMD, ...): "ethernet" (default) - a UDP socket bound to
        # server_ip:receive_port, requires the DUT to have a working network stack pointed at this
        # server. "jtag" - the JTAG probe's serial/UART bridge (jtag_port), for DUTs with no
        # network stack at all. Independent of dut_mode above (see dut_message_channel.py).
        self.__connection_type = machine_parameters.get("connection_type", self.__DEFAULT_CONNECTION_TYPE).lower()
        if self.__connection_type not in self.__SUPPORTED_CONNECTION_TYPES:
            raise ValueError(f"Unsupported connection_type '{self.__connection_type}', expected one of "
                             f"{self.__SUPPORTED_CONNECTION_TYPES}")

        # receive_port: the UDP port libLogHelper on the DUT sends its log traffic to. Required
        # (and must be a fixed, known-in-advance value - both sides have to agree on it) when
        # connection_type is "ethernet". Unused when connection_type is "jtag".
        self.__receiving_port = machine_parameters.get("receive_port")
        if self.__connection_type == "ethernet" and self.__receiving_port is None:
            raise ValueError("connection_type 'ethernet' requires 'receive_port' to be set in the machine config")
        if self.__receiving_port is None:
            self.__receiving_port = self.__DEFAULT_RECEIVE_PORT

        # jtag_port/jtag_baudrate: the serial device exposed by the JTAG probe's UART bridge, read
        # for DUT messages instead of a UDP socket. Required when connection_type is "jtag";
        # jtag_baudrate defaults to 115200 if omitted. Unused when connection_type is "ethernet".
        self.__jtag_port = machine_parameters.get("jtag_port")
        self.__jtag_baudrate = machine_parameters.get("jtag_baudrate", self.__DEFAULT_JTAG_BAUDRATE)
        if self.__connection_type == "jtag" and not self.__jtag_port:
            raise ValueError("connection_type 'jtag' requires 'jtag_port' to be set in the machine config")

        self.__redeploy_cmd = machine_parameters.get("redeploy_cmd")
        self.__redeploy_timeout = machine_parameters.get("redeploy_timeout", DEFAULT_REDEPLOY_TIMEOUT)
        if self.__dut_mode == "passive":
            if not self.__redeploy_cmd:
                raise ValueError("dut_mode 'passive' requires 'redeploy_cmd' to be set in the machine config")
            # Bare-metal DUTs have no OS, so soft OS reboot is not a meaningful escalation step
            self.__disable_os_soft_reboot = True

        # Delay between receiving '#ABORT'/'#END' and restarting the app, per-DUT configurable
        self.__restart_interval = machine_parameters.get("restart_interval", self.__DEFAULT_RESTART_INTERVAL)

        # Factory to manage the command execution. json_files is only actually needed to obtain
        # the console kill/run commands used by "active" DUTs; "passive" DUTs only need it for the
        # test_name/header used to name DUTLogging files (and the optional command_window
        # rotation), so they may instead supply 'test_name'/'test_header' directly and skip
        # json_files/CommandFactory entirely.
        self.__command_factory = None
        self.__test_name = None
        self.__test_header = None
        json_files = machine_parameters.get("json_files")
        if json_files:
            self.__command_factory = CommandFactory(json_files_list=json_files, logger_name=logger_name)
        elif self.__dut_mode == "active":
            raise ValueError("dut_mode 'active' requires 'json_files' to be set in the machine config")
        else:
            self.__test_name = machine_parameters.get("test_name")
            self.__test_header = machine_parameters.get("test_header", self.__DEFAULT_TEST_HEADER)
            if not self.__test_name:
                raise ValueError("dut_mode 'passive' requires either 'json_files' or 'test_name' "
                                 "to be set in the machine config")

        # Dispatcher for commands the DUT itself requests via '#CMD <NAME>' messages
        self.__command_dispatcher = DUTCommandDispatcher(logger_name=self.__logger_name)
        self.__command_dispatcher.register(DUTCommand.HARD_REBOOT, self.__on_hard_reboot_command)
        self.__command_dispatcher.register(DUTCommand.SOFT_REBOOT, self.__on_soft_reboot_command)
        # Stubs only for now - see README.md, "DUT-requested commands"
        self.__command_dispatcher.register(DUTCommand.OPEN_BEAM, self.__on_open_beam_command)
        self.__command_dispatcher.register(DUTCommand.CLOSE_BEAM, self.__on_close_beam_command)

        self.__dut_log_path = f"{server_log_path}/{self.__dut_hostname}"
        # make sure that the path exists
        if os.path.isdir(self.__dut_log_path) is False:
            os.mkdir(self.__dut_log_path)

        self.__dut_logging_obj = None
        # Channel the server listens on for DUT status/log messages - a UDP socket ("ethernet") or
        # the JTAG probe's serial/UART bridge ("jtag"), per connection_type above.
        self.__message_channel: MessageChannel = create_message_channel(
            connection_type=self.__connection_type, timeout=self.__max_timeout_time,
            logger_name=self.__logger_name, server_ip=server_ip, receive_port=self.__receiving_port,
            jtag_port=self.__jtag_port, jtag_baudrate=self.__jtag_baudrate)
        self.__message_channel.open()

        # Variables to control rebooting (soft app and soft OS) process
        self.__soft_app_reboot_count = 0
        self.__soft_os_reboot_count = 0
        self.__hard_reboot_count = 0

        super(Machine, self).__init__(*args, **kwargs)

    def __str__(self) -> str:
        dut_str = f"IP:{self.__dut_ip} USERNAME:{self.__dut_username} "
        dut_str += f"HOSTNAME:{self.__dut_hostname} CONN:{self.__connection_type}"
        if self.__connection_type == "ethernet":
            dut_str += f" RECPORT:{getattr(self.__message_channel, 'receive_port', self.__receiving_port)}"
        else:
            dut_str += f" JTAGPORT:{self.__jtag_port}"
        return dut_str

    def run(self):
        # Run execution of thread
        # mandatory: It must start the machine on (do not change to reboot, ON is the correct config)
        turn_on_status = turn_machine_on(address=self.__dut_ip, switch_model=self.__switch_model,
                                         switch_port=self.__switch_port, switch_ip=self.__switch_ip,
                                         logger_name=self.__logger_name)
        if turn_on_status != ErrorCodes.SUCCESS:
            self.__logger.error(f"Failed to turn ON the {self}")

        # Wait and start the app for the first time
        boot_status = self.__wait_for_booting()
        if boot_status != ErrorCodes.SUCCESS:
            self.__logger.warning(f"Initial boot check did not succeed ({boot_status}) on {self}, "
                                  f"proceeding to (re)start the app anyway")
        self.__soft_app_reboot()
        while self.__stop_event.is_set() is False:
            try:
                data = self.__message_channel.receive()
                self.__dut_logging_obj(message=data)
                try:
                    data_decoded = data.decode("ascii")
                except UnicodeDecodeError:
                    data_decoded = "".join(chr(chi) for chi in data)

                message_type = PossibleMessages.get_message_type(log_string=data_decoded)

                # TO AVOID making sequential reboot when receiving good data,
                # This is necessary to fix the behavior when a device keeps crashing for multiple times
                # in a short period, but eventually comes to life again
                if message_type == PossibleMessages.IT:
                    self.__soft_app_reboot_count = 0
                    self.__hard_reboot_count = 0

                # We need to power cycle the DUT if it requests to do so
                # (kept as its own message type for backward compatibility with existing DUTs;
                # it is functionally equivalent to '#CMD HARD_REBOOT')
                if message_type == PossibleMessages.POWER_CYCLE_REQUEST:
                    self.__logger.info(f"Power Cycle Request received from {self}")
                    self.__command_dispatcher.dispatch(DUTCommand.HARD_REBOOT.value)

                # Generic DUT-requested commands, e.g. '#CMD HARD_REBOOT' or '#CMD SOFT_REBOOT'
                if message_type == PossibleMessages.CMD:
                    raw_command = data_decoded.split(PossibleMessages.CMD.value, 1)[-1].strip()
                    self.__command_dispatcher.dispatch(raw_command)

                # The benchmark reported it stopped (normally or via an abort) - restart it quickly
                # rather than waiting for the socket to time out. previous_log_end_status records
                # which of the two it was; __soft_app_reboot picks the active (console kill+run) or
                # passive (redeploy_cmd) restart path based on this DUT's configured dut_mode.
                if message_type in (PossibleMessages.ABORT, PossibleMessages.END):
                    self.__logger.info(f"{message_type} received from {self}, restarting the app "
                                       f"in {self.__restart_interval}s")
                    self.__stop_event.wait(self.__restart_interval)
                    end_status = EndStatus.ABORTED if message_type == PossibleMessages.ABORT \
                        else EndStatus.NORMAL_END
                    self.__soft_app_reboot(previous_log_end_status=end_status)

                self.__logger.debug(f"{message_type} - Connection from {self}")

                if self.__command_factory is not None and self.__command_factory.is_command_window_timed_out:
                    self.__logger.info(
                        f"Benchmark exceeded the command execution window, executing another one now on {self}.")
                    self.__soft_app_reboot(previous_log_end_status=EndStatus.NORMAL_END)
            except TimeoutError:
                # Soft app reboot
                soft_app_reboot_status = self.__soft_app_reboot(previous_log_end_status=EndStatus.SOFT_APP_REBOOT)
                if soft_app_reboot_status == ErrorCodes.SUCCESS:
                    continue
                # Soft OS reboot
                soft_os_reboot = self.__soft_os_reboot()
                if soft_os_reboot == ErrorCodes.SUCCESS:
                    self.__soft_app_reboot(previous_log_end_status=EndStatus.SOFT_OS_REBOOT)
                    continue
                # Finally, the Power cycle Hard reboot
                self.__hard_reboot()
                self.__soft_app_reboot(previous_log_end_status=EndStatus.HARD_REBOOT)

    def __on_hard_reboot_command(self, args: str) -> None:
        """ Handler registered for DUTCommand.HARD_REBOOT: power cycle the DUT and restart the app """
        self.__hard_reboot()
        self.__soft_app_reboot(previous_log_end_status=EndStatus.HARD_REBOOT)

    def __on_soft_reboot_command(self, args: str) -> None:
        """ Handler registered for DUTCommand.SOFT_REBOOT: restart the app without power cycling
        (console kill+run for active DUTs, redeploy_cmd for passive ones) """
        self.__soft_app_reboot(previous_log_end_status=EndStatus.SOFT_APP_REBOOT)

    def __on_open_beam_command(self, args: str) -> None:
        """ Stub handler registered for DUTCommand.OPEN_BEAM - see README.md, "DUT-requested commands" """
        self.__logger.info(f"OPEN_BEAM received (not yet implemented) args='{args}' on {self}")

    def __on_close_beam_command(self, args: str) -> None:
        """ Stub handler registered for DUTCommand.CLOSE_BEAM - see README.md, "DUT-requested commands" """
        self.__logger.info(f"CLOSE_BEAM received (not yet implemented) args='{args}' on {self}")

    def __new_dut_connection(self) -> DUTConnection:
        """ Build a fresh, not-yet-logged-in Telnet console connection for this (active) DUT """
        return create_dut_connection(ip=self.__dut_ip, username=self.__dut_username,
                                     password=self.__dut_password, timeout=self.__max_timeout_time,
                                     logger_name=self.__logger_name)

    def __dut_login(self) -> DUTConnection:
        """ Open a new DUT console connection and perform the login handshake
        :return: a logged-in DUTConnection
        """
        return self.__new_dut_connection().login()

    def __soft_app_reboot(self, previous_log_end_status: EndStatus = None) -> ErrorCodes:
        """ (Re)start the app on the device: for 'active' DUTs this kills and re-runs the current
        benchmark over the console connection (telnet/jtag); for 'passive' (bare-metal) DUTs,
        which start their app automatically as soon as it is loaded, this instead runs the
        configured 'redeploy_cmd' to reload/reset it (see dut_deployment.py).
        :previous_log_end_status: if it is not the first time that the device will run an app,
        then pass the end_status, otherwise leave it None
        :return: If the start was successful or not
        """
        if self.__stop_event.is_set():
            return ErrorCodes.THREAD_EVENT_IS_SET

        if previous_log_end_status is None and self.__dut_logging_obj is not None:
            self.__logger.exception(
                f"INCORRECT CONFIGURATION: previous_ending_status is None and __dut_logging_obj is Not None - {self}")
            raise

        if self.__soft_app_reboot_count >= self.__MAX_SEQUENTIALLY_SOFT_APP_REBOOTS:
            self.__logger.info(f"MAXIMUM_APP_REBOOT_REACHED on {self}")
            return ErrorCodes.MAXIMUM_APP_REBOOT_REACHED

        # self.__command_factory (when configured via 'json_files') produces the commands that
        # will be executed, plus the test_name/header used to name the DUTLogging file. A passive
        # DUT configured without 'json_files' instead supplies test_name/header directly
        # ('test_name'/'test_header' in its YAML config) and has no console commands to run.
        if self.__command_factory is not None:
            cmd_line_run, cmd_kill, test_name, header = self.__command_factory.get_commands_and_test_info()
        else:
            cmd_line_run, cmd_kill, test_name, header = None, None, self.__test_name, self.__test_header

        if self.__dut_mode == "passive":
            return self.__passive_redeploy(test_name=test_name, header=header,
                                           previous_log_end_status=previous_log_end_status)

        # First check if there is an app running
        self.__logger.info(f"TRYING SOFT APP REBOOT (app kill and run again/start first time) on {self}")
        # try __MAX_START_APP_TRIES times to start the app on the DUT
        for try_i in range(self.__MAX_LOGIN_TRIES):
            # All loops must stop after the event is set
            if self.__stop_event.is_set():
                break
            try:
                with self.__dut_login() as tn:
                    # Kill first
                    tn.write(cmd_kill)
                    tn.read_very_eager()
                    # Never sleep with time, but with event
                    self.__stop_event.wait(self.__READ_EAGER_TIMEOUT)
                    # Execute the command
                    tn.write(cmd_line_run)
                    tn.read_very_eager()
                    # Never sleep with time, but with event
                    self.__stop_event.wait(self.__READ_EAGER_TIMEOUT)
                    # If it reaches here, the app is running
                    self.__logger.info(f"SUCCESSFULLY SEND THE SOFT REBOOT CMDS:{cmd_kill} "
                                       f"COUNTER:{self.__soft_app_reboot_count} "
                                       f"TRY:{try_i} on {self} CMDEXEC={cmd_line_run[:10]}...")
                    # Close the DUTLogging only if there is a log file open
                    if self.__dut_logging_obj:
                        self.__dut_logging_obj.finish_this_dut_log(end_status=previous_log_end_status)
                    # Delete the current dut logging obj
                    del self.__dut_logging_obj
                    self.__dut_logging_obj = DUTLogging(log_dir=self.__dut_log_path, test_name=test_name,
                                                        test_header=header, hostname=self.__dut_hostname,
                                                        logger_name=self.__logger_name)
                self.__soft_app_reboot_count += 1
                return ErrorCodes.SUCCESS
            except OSError as e:
                self.__logger.error(f"DUT connection failed TRY:{try_i} on {self} error:{e}")
                if e.errno == errno.EHOSTUNREACH:
                    return ErrorCodes.HOST_UNREACHABLE
            except RuntimeError as e:
                self.__logger.error(f"{e} {self}")
                return ErrorCodes.DUT_CONNECTION_ERROR
            except EOFError:
                self.__logger.info(f"Command execution not successful TRY:{try_i} on {self}")
        return ErrorCodes.DUT_CONNECTION_ERROR

    def __passive_redeploy(self, test_name: str, header: str,
                           previous_log_end_status: EndStatus) -> ErrorCodes:
        """ Passive/bare-metal counterpart of the active-mode console kill+run cycle above: run
        this DUT's configured 'redeploy_cmd' instead of logging into a console, then roll the
        DUTLogging file the same way the active path does.
        """
        self.__logger.info(f"TRYING REDEPLOY (redeploy_cmd, no console) on {self}")
        redeploy_status = redeploy_dut(redeploy_cmd=self.__redeploy_cmd, logger_name=self.__logger_name,
                                       timeout=self.__redeploy_timeout)
        if redeploy_status != ErrorCodes.SUCCESS:
            return redeploy_status

        self.__logger.info(f"SUCCESSFULLY REDEPLOYED APP COUNTER:{self.__soft_app_reboot_count} on {self}")
        # Close the DUTLogging only if there is a log file open
        if self.__dut_logging_obj:
            self.__dut_logging_obj.finish_this_dut_log(end_status=previous_log_end_status)
        # Delete the current dut logging obj
        del self.__dut_logging_obj
        self.__dut_logging_obj = DUTLogging(log_dir=self.__dut_log_path, test_name=test_name, test_header=header,
                                            hostname=self.__dut_hostname, logger_name=self.__logger_name)
        self.__soft_app_reboot_count += 1
        return ErrorCodes.SUCCESS

    def __wait_for_booting(self):
        if self.__dut_mode == "passive":
            # Passive/bare-metal DUTs have no console/shell to probe for readiness, and
            # redeploy_cmd (e.g. an xsct/JTAG script) already performs any board-specific
            # reset/settle waits it needs internally - so unlike 'active' DUTs there is nothing to
            # wait/poll for here. Deploy immediately rather than sitting idle for boot_waiting_time
            # (which does not apply to passive DUTs) before ever invoking redeploy_cmd.
            self.__logger.info(f"Passive DUT - skipping boot wait, deploying immediately on {self}")
            return ErrorCodes.SUCCESS

        current_timestamp = time.time()
        start_timestamp = current_timestamp
        while (current_timestamp - start_timestamp) <= self.__boot_waiting_time:
            # All loops must stop after the event is set
            if self.__stop_event.is_set():
                break
            # dut_mode 'active' always uses Telnet for its console (see __new_dut_connection), so
            # a ping check is always meaningful here regardless of connection_type (which only
            # selects the message-listening transport).
            try:
                subprocess.check_output(["ping", "-c", "1", self.__dut_ip], timeout=self.__BOOT_PING_TIMEOUT)
                # Try to see if the DUT console login is indeed possible
                tn = self.__dut_login()
                tn.close()
                self.__logger.info(f"Boot successful {self}")
                return ErrorCodes.SUCCESS
                # return ErrorCodes.SUCCESS
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
                self.__logger.error(f"Boot ping failed {self} error:{e}")
            except (OSError, EOFError, RuntimeError) as e:
                self.__logger.error(f"DUT connection failed {self} error:{e}")
                if isinstance(e, OSError) and e.errno == errno.ECONNREFUSED:
                    # When connection is refused, it crashes instantaneously
                    self.__stop_event.wait(self.__BOOT_PING_TIMEOUT)
            current_timestamp = time.time()

        return ErrorCodes.HOST_UNREACHABLE

    def __soft_os_reboot(self):
        """ SOFT OS REBOOT: Reboot the operating system, or try to reboot using the DUT console connection
            THE KILL APP WILL MAKE THE LOGGING ENDING BASED ON THE EndStatus
        """
        if self.__stop_event.is_set():
            return ErrorCodes.THREAD_EVENT_IS_SET

        if self.__disable_os_soft_reboot is True:
            return ErrorCodes.DISABLED_SOFT_OS_REBOOT

        if self.__soft_os_reboot_count >= self.__MAX_SEQUENTIALLY_SOFT_OS_REBOOTS:
            self.__logger.info(f"MAXIMUM_OS_REBOOT_REACHED on {self}")
            return ErrorCodes.MAXIMUM_OS_REBOOT_REACHED

        self.__logger.info(f"Trying to perform a soft Operating System reboot (OS reboot and run app) on {self}")
        default_os_reboot_cmd = b"sudo /sbin/reboot\r\n"
        # for try_i in range(self.__MAX_LOGIN_TRIES):
        try:
            with self.__dut_login() as tn:
                # OS reboot
                tn.write(default_os_reboot_cmd)
                tn.read_very_eager()
                self.__stop_event.wait(self.__READ_EAGER_TIMEOUT)

            self.__logger.info(f"SUCCESSFUL OS REBOOT:{default_os_reboot_cmd} "
                               f"COUNTER:{self.__soft_os_reboot_count} on {self}")
            # This time is just to make the OS start the rebooting process;
            # otherwise the next ping will be successful, right after sudo reboot command
            self.__stop_event.wait(self.__WAIT_AFTER_SOFT_OS_REBOOT_TIME)
            # Wait the machine to boot
            boot_status = self.__wait_for_booting()
            if boot_status != ErrorCodes.SUCCESS:
                self.__logger.warning(f"Post-OS-reboot boot check did not succeed ({boot_status}) on {self}")
            # Reset the soft app reboot as the system will be rebooted
            self.__soft_app_reboot_count = 0
            self.__soft_os_reboot_count += 1
            # return self.__soft_app_reboot(previous_log_end_status=EndStatus.SOFT_OS_REBOOT)
            return ErrorCodes.SUCCESS
        except (OSError, EOFError, RuntimeError) as e:
            self.__logger.error(f"Soft OS reboot not successful {self} - {e}")
            if isinstance(e, OSError) and e.errno == errno.EHOSTUNREACH:
                self.__logger.error(f"Host unreachable {self} ")
                return ErrorCodes.HOST_UNREACHABLE
            return ErrorCodes.DUT_CONNECTION_ERROR

    def __hard_reboot(self):
        """ reboot the device based on reboot_machine module
        :return reboot_status
        """
        if self.__stop_event.is_set():
            return ErrorCodes.THREAD_EVENT_IS_SET

        reboot_sleep_time = self.__POWER_SWITCH_DEFAULT_TIME_REST
        if self.__hard_reboot_count > self.__MAX_SEQUENTIALLY_HARD_REBOOTS:
            # We turn off the device for __LONG_REBOOT_WAIT_TIME_AFTER_PROBLEM seconds
            reboot_sleep_time = self.__LONG_REBOOT_WAIT_TIME_AFTER_PROBLEM
            self.__hard_reboot_count = 0
        else:
            self.__hard_reboot_count += 1

        self.__logger.info(
            f"Trying to perform a hard reboot on device (power cycle). Sleep interval is {reboot_sleep_time} on {self}")
        off_status, on_status = reboot_machine(address=self.__dut_ip,
                                               switch_model=self.__switch_model,
                                               switch_port=self.__switch_port,
                                               switch_ip=self.__switch_ip,
                                               rebooting_sleep=reboot_sleep_time,
                                               logger_name=self.__logger_name,
                                               thread_event=self.__stop_event)
        reboot_msg = f"HARD REBOOT FOR - {self} POWER_SWITCH_PORT_NUMBER:{self.__switch_port} "
        reboot_msg += f"COUNTER:{self.__hard_reboot_count} SWITCH_IP:{self.__switch_ip}"
        if off_status != ErrorCodes.SUCCESS or on_status != ErrorCodes.SUCCESS:
            reboot_msg += f" failed. ON_STATUS:{on_status} OFF_STATUS:{off_status}"
            self.__logger.error(reboot_msg)
        else:
            self.__logger.info(reboot_msg + " finished.")
        # Wait the machine to boot
        boot_status = self.__wait_for_booting()
        if boot_status != ErrorCodes.SUCCESS:
            self.__logger.warning(f"Post-hard-reboot boot check did not succeed ({boot_status}) on {self}")
        # Reset the soft app and the soft os reboot as the system will be hard rebooted
        self.__soft_app_reboot_count = 0
        self.__soft_os_reboot_count = 0

    def join(self, timeout: Optional[float] = None) -> None:
        self.__logger.info(f"Joining Machine {self}.")
        # FIXME: This method is taking too much time, needs improvement

        # # Test if the board is alive
        # # Pinging the board
        # try:
        #     subprocess.check_output(["ping", "-c", "1", self.__dut_ip], timeout=self.__BOOT_PING_TIMEOUT)
        #     with self.__dut_login() as tn:
        #         # Kill first
        #         tn.write(self.__command_factory.current_command_cmd_kill)
        #         tn.read_very_eager()
        # except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        #     self.__logger.error(f"Ping failed while trying to join the thread {self} error:{e}")
        # except (OSError, EOFError, RuntimeError) as e:
        #     self.__logger.error(f"Unsuccessful kill command after Machine thread joining on {self} - {e}")

        super(Machine, self).join(timeout)

    def stop(self) -> None:
        """ Stop the main function before join the thread """
        self.__stop_event.set()
        self.__message_channel.close()
