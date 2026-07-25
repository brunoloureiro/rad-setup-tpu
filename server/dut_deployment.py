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
import queue
import shlex
import subprocess
import threading
import time
import typing

from .error_codes import ErrorCodes

DEFAULT_REDEPLOY_TIMEOUT = 60


def _stream_reader(pipe: typing.IO, line_queue: "queue.Queue") -> None:
    """ Read lines from `pipe` and push them to `line_queue` until EOF, then push None as a
    sentinel so the consumer knows the subprocess has closed its output. """
    try:
        for line in iter(pipe.readline, ""):
            line_queue.put(line)
    finally:
        line_queue.put(None)
        pipe.close()


def redeploy_dut(redeploy_cmd: typing.Union[str, list], logger_name: str,
                 timeout: float = DEFAULT_REDEPLOY_TIMEOUT) -> ErrorCodes:
    """ Run the configured redeploy command to (re)load and start the application on a
    passive/bare-metal DUT, e.g. 'xsct /path/to/deploy.tcl'. The command's stdout/stderr is
    streamed to the log line-by-line as it runs (rather than only surfaced at the end), since
    these commands (e.g. xsct/xsdb driving a JTAG probe) can take up to a couple minutes and
    silently waiting that whole time gives no indication whether the deployment is progressing
    or stuck.
    :param redeploy_cmd: command to run, either a shell-style string or an argv list
    :param logger_name: logger name, threaded down from the owning Machine
    :param timeout: max seconds to wait for the redeploy command to finish
    :return: ErrorCodes.SUCCESS if the command exits zero, otherwise a failure code
    """
    logger = logging.getLogger(f"{logger_name}.{__name__}")
    argv = shlex.split(redeploy_cmd) if isinstance(redeploy_cmd, str) else list(redeploy_cmd)
    logger.info(f"Redeploying passive DUT app, cmd={argv}")

    try:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1)
    except OSError as e:
        logger.error(f"Redeploy command could not be executed, cmd={argv} error={e}")
        return ErrorCodes.GENERAL_ERROR

    line_queue: "queue.Queue" = queue.Queue()
    reader = threading.Thread(target=_stream_reader, args=(process.stdout, line_queue), daemon=True)
    reader.start()

    start_time = time.monotonic()
    deadline = start_time + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.error(f"Redeploy command timed out after {timeout}s, cmd={argv} - killing it")
            process.kill()
            process.wait()
            reader.join(timeout=5)
            return ErrorCodes.TIMEOUT_ERROR
        try:
            line = line_queue.get(timeout=min(remaining, 1))
        except queue.Empty:
            continue
        if line is None:
            break
        logger.info(f"[redeploy] {line.rstrip()}")

    remaining = max(0.0, deadline - time.monotonic())
    try:
        returncode = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        logger.error(f"Redeploy command timed out after {timeout}s, cmd={argv} - killing it")
        process.kill()
        process.wait()
        return ErrorCodes.TIMEOUT_ERROR

    elapsed = time.monotonic() - start_time
    if returncode != 0:
        logger.error(f"Redeploy command failed rc={returncode} after {elapsed:.1f}s, cmd={argv} "
                     f"(see [redeploy] lines above for output)")
        return ErrorCodes.GENERAL_ERROR

    logger.info(f"Redeploy command finished successfully in {elapsed:.1f}s, cmd={argv}")
    return ErrorCodes.SUCCESS
