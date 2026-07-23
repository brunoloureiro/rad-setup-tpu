"""
(Re)deployment for "passive" bare-metal DUTs.

An 'active' DUT runs an OS with a shell reachable over a console (see dut_connection.py):
starting/restarting its benchmark means logging in and issuing kill/run commands. A 'passive'
(bare-metal) DUT has no OS and no shell to log into - it starts running its application
automatically as soon as that application is loaded onto it (e.g. an FPGA/SoC bare-metal ELF
loaded over JTAG). For those DUTs there is nothing to "log into and run a command" on; instead,
the server (re)loads/resets the app by invoking an external redeploy command configured per-DUT
(typically a TCL script driven through a JTAG debugger, e.g. Xilinx xsct/xsdb), via the
'redeploy_cmd' field in that DUT's YAML config (see machine.py, 'dut_mode: passive').
"""
import logging
import shlex
import subprocess
import typing

from .error_codes import ErrorCodes

DEFAULT_REDEPLOY_TIMEOUT = 60


def redeploy_dut(redeploy_cmd: typing.Union[str, list], logger_name: str,
                 timeout: float = DEFAULT_REDEPLOY_TIMEOUT) -> ErrorCodes:
    """ Run the configured redeploy command to (re)load and start the application on a
    passive/bare-metal DUT, e.g. 'xsct /path/to/deploy.tcl'.
    :param redeploy_cmd: command to run, either a shell-style string or an argv list
    :param logger_name: logger name, threaded down from the owning Machine
    :param timeout: max seconds to wait for the redeploy command to finish
    :return: ErrorCodes.SUCCESS if the command exits zero, otherwise a failure code
    """
    logger = logging.getLogger(f"{logger_name}.{__name__}")
    argv = shlex.split(redeploy_cmd) if isinstance(redeploy_cmd, str) else list(redeploy_cmd)
    logger.info(f"Redeploying passive DUT app, cmd={argv}")
    try:
        result = subprocess.run(argv, timeout=timeout, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        logger.error(f"Redeploy command timed out after {timeout}s, cmd={argv}")
        return ErrorCodes.TIMEOUT_ERROR
    except OSError as e:
        logger.error(f"Redeploy command could not be executed, cmd={argv} error={e}")
        return ErrorCodes.GENERAL_ERROR

    if result.returncode != 0:
        logger.error(f"Redeploy command failed rc={result.returncode} cmd={argv} "
                     f"stdout={result.stdout[-500:]} stderr={result.stderr[-500:]}")
        return ErrorCodes.GENERAL_ERROR

    logger.info(f"Redeploy command finished successfully, cmd={argv}")
    return ErrorCodes.SUCCESS
