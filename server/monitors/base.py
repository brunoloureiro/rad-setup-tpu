"""
Base class for per-Machine Monitor threads - see OPERATOR_COMMANDS.md, "Operator -> Machine command
interface" / "Monitor thread API". A Monitor is a way for a lab to plug in its own
device-/software-specific monitoring logic (e.g. "reboot every N minutes", "watch for a specific
string in the DUT log and switch benchmarks") without touching machine.py: implement one
Monitor subclass and register it in enabled_monitors.py (the one file that needs editing), then
select it per-DUT via that machine's YAML 'monitor:' field.

A Monitor is spawned by its own Machine (once Machine.run() actually starts - see
Machine.__start_monitor) and is handed exactly the following at construction, all bound to that
one owning Machine; a Monitor implementation should never need anything else:

- `command_callback`: bound to that Machine's own Machine.command(...) - the *only* way a Monitor
  may affect its Machine. Same call shape command_cli.py drives once it resolves a target Machine:
  command_callback(name, **params) -> bool.
- DUT log access (`log_dir` / `current_log_file()`): DUT logs are the input most monitoring logic
  actually needs (to decide *when* to act), so this is standard on the base class rather than
  something every custom Monitor has to wire up itself. `log_dir` is the directory holding every
  one of this DUT's per-run log files (see dut_logging.py) - stable for the Machine's whole
  lifetime, so a Monitor can just glob it (see log_files() below). `current_log_file()` returns
  the path of whichever one is currently open (or None between runs / before the first one),
  since that changes every time the app is (re)started - it has to be a callback rather than a
  plain string for exactly that reason.

Subclasses implement run(). A Monitor is a threading.Thread like Machine itself, so the exact
same "never crash" rule applies (see CLAUDE.md's prime directive): an uncaught exception in *any*
thread - a Monitor's included, not just Machine's own - still trips server.py's
threading.excepthook and takes the whole server down. A Monitor's run() must therefore catch its
own expected failure modes and never let anything escape; command_callback/dispatch already never
raises on its end (see machine_commands.py), but whatever a Monitor does on its own (timers, file
reads, network calls, ...) is squarely the Monitor implementation's own responsibility.
"""
import glob
import logging
import os
import threading
import typing

CommandCallback = typing.Callable[..., bool]
CurrentLogFileCallback = typing.Callable[[], typing.Optional[str]]


class Monitor(threading.Thread):
    def __init__(self, command_callback: CommandCallback, log_dir: str,
                 current_log_file: CurrentLogFileCallback, hostname: str, logger_name: str,
                 stop_event: threading.Event, *args, **kwargs):
        """
        :param command_callback: the owning Machine's own Machine.command(name, **params) -> bool
        :param log_dir: directory holding every log file ever written for this DUT (see
            dut_logging.py) - stable for the whole lifetime of the owning Machine
        :param current_log_file: call to get the path of the currently-open log file, or None if
            no run is currently logging (between app restarts, or before the first one)
        :param hostname: the owning DUT's hostname, for this Monitor's own log lines
        :param logger_name: logger name to log under - subclasses should get their own logger via
            logging.getLogger(f"{logger_name}.{__name__}"), the same convention every other
            module in this codebase follows (self._logger below already does this)
        :param stop_event: the owning Machine's own stop event, set when it is stopping -
            subclasses' run() loops should wait/poll on this (self._stop_event.wait(...), never
            time.sleep()) so they shut down promptly, the same convention Machine itself follows
        """
        self._command = command_callback
        self._log_dir = log_dir
        self._current_log_file_callback = current_log_file
        self._hostname = hostname
        self._logger = logging.getLogger(f"{logger_name}.{__name__}")
        self._stop_event = stop_event
        kwargs.setdefault("daemon", True)
        super().__init__(*args, **kwargs)

    def log_files(self) -> typing.List[str]:
        """ Every log file written so far for this DUT (see dut_logging.py), oldest first """
        return sorted(glob.glob(os.path.join(self._log_dir, "*.log")))

    def current_log_file(self) -> typing.Optional[str]:
        """ Path of the currently-open log file for this DUT, or None between app runs """
        return self._current_log_file_callback()

    def run(self) -> None:
        raise NotImplementedError
