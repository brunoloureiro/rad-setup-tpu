# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`radiation-setup` is the Python server component of the RADHelper framework. It runs outside a
beam room during radiation experiments, coordinating one or more Devices Under Test (DUTs). For
each DUT it: powers the device on via a network power switch, starts a benchmark over a console
connection (Telnet, or a JTAG probe's serial/UART bridge), listens for UDP log/status messages from
the DUT (sent by the `libLogHelper` client library), and reboots the device (soft app restart, soft
OS reboot, or hard power cycle) when it stops responding or requests one.

## Running

```bash
pip install -r requirements.txt
python3 server.py --config path/to/server_parameters.yaml   # default: ./server_parameters.yaml
python3 server.py --enable_curses                            # curses-based live console instead of plain stdout
```

Requires Python >= 3.10 (enforced at startup in `server.py:main`) and a `curl` binary on PATH
(checked at import time in `server/reboot_machine.py`).

## Tests

```bash
python -m unittest tests.test_command_factory
python -m unittest discover tests
```

There is no pytest config; tests are plain `unittest.TestCase`s. Most of them are **not** hermetic
unit tests — they open real Telnet connections, hit real power-switch HTTP endpoints, and
reference hardcoded lab IPs and hostnames (e.g. `tests/test_machine.py`, `test_reboot_machine.py`,
`test_connection.py`, the latter an untracked scratch file, not part of the repo). `test_machine.py`
sleeps for 500s and expects a real DUT to be reachable. `test_command_factory.py` and
`test_dut_logging.py` also currently fail out of the box against `logging_setup`'s current
signature (missing the required `enable_curses` arg) — pre-existing breakage, not caused by any
particular change. `test_dut_commands.py` is fully hermetic (pure dispatcher logic, no I/O). Don't
expect the hardware-dependent tests to pass in a sandboxed/CI environment without the physical rig;
when changing shared logic, reason about correctness directly rather than trusting a green run.

## Architecture

### Threading model

`server.py:main` reads `server_parameters.yaml`, then spawns one `Machine` thread
(`server/machine.py`) per enabled entry under `machines`. Each `Machine` is a `threading.Thread`
that owns a UDP socket bound to `server_ip:receive_port` and runs an independent state machine for
exactly one DUT — machines never share state. `threading.excepthook` is overridden so that if any
Machine thread dies uncaught, the whole server logs it and exits (`__machine_thread_exception_handler`
in `server.py`); a SIGINT handler does an orderly shutdown of all machines via `Machine.stop()`
(sets a `threading.Event`) followed by `join()`.

### Machine lifecycle (`server/machine.py`)

`Machine.run()` is the core loop:
1. Power the DUT on (`reboot_machine.turn_machine_on`), then poll via ping (skipped for non-network
   transports) + console login until it boots (`__wait_for_booting`).
2. Start the current benchmark over the console connection (`__soft_app_reboot`), which also opens
   a new `DUTLogging` file for the run.
3. Loop on `recvfrom` with a timeout (`max_timeout_time` from the machine's YAML config). Every
   received UDP datagram is: (a) appended to the current `DUTLogging` file, and (b) classified via
   `PossibleMessages.get_message_type` (a `#LOGFILE`/`#IT`/`#HEADER`/`#BEGIN`/`#END`/`#INF`/`#ERR`/
   `#SDC`/`#ABORT`/`#CMD`/`#INF POWER_CYCLE_REQUEST` prefix protocol shared with `libLogHelper`).
4. On socket timeout, escalate through three levels with per-level retry counters that reset when
   good data (`#IT`) arrives: soft app reboot -> soft OS reboot (skippable via
   `disable_os_soft_reboot` in the machine config) -> hard power cycle. A `#INF POWER_CYCLE_REQUEST`
   message forces an immediate hard reboot regardless of timeout state; a `#CMD <NAME>` message runs
   whatever the DUT asked for (see DUT commands below).
5. `CommandFactory.is_command_window_timed_out` is also checked on every received message so a
   benchmark that runs longer than its configured window gets restarted even without a timeout.

Reboot counters (`__soft_app_reboot_count`, `__soft_os_reboot_count`, `__hard_reboot_count`) are
reset at different points intentionally (e.g. a hard reboot resets both soft counters) — this
encodes the escalation policy, so don't "simplify" the reset logic without re-reading the
surrounding comments in `machine.py`.

Never use `time.sleep()` inside `Machine` for waits that should be interruptible on shutdown —
use `self.__stop_event.wait(seconds)` instead (existing code follows this convention throughout).

### DUT console connection (`server/dut_connection.py`)

`Machine` talks to a DUT's console through a `DUTConnection`, an abstraction with two
implementations selected per-machine by the `connection_type` field in that DUT's YAML config
(`"telnet"`, the default, or `"jtag"`): `TelnetDUTConnection` (network Telnet, the original
behavior) and `JTAGDUTConnection` (serial console over a JTAG probe's UART bridge, via `pyserial`;
config fields `jtag_port` and optional `jtag_baudrate`). Both are driven through the same four raw
I/O primitives (`open`/`write`/`read_until`/`read_very_eager`/`close`); the login handshake
(username/password/shell prompts) is transport-agnostic and implemented once in
`DUTConnection.login()`. `Machine.__dut_login()` builds a fresh connection via
`create_dut_connection(...)` and logs in — every call site that used to talk to `telnetlib`
directly now goes through this interface, so IP-based and JTAG-based DUTs are otherwise driven by
identical `Machine` code (same YAML schema, one machine config file per DUT either way, only the
connection-specific fields differ). Adding a third transport means implementing `DUTConnection`'s
four primitives and adding a branch in `create_dut_connection`; nothing else changes.

### DUT-requested commands (`server/dut_commands.py`)

A DUT can ask the server to perform an action at runtime by sending a `#CMD <NAME>` UDP message
(e.g. `#CMD HARD_REBOOT`). `DUTCommandDispatcher` maps `DUTCommand` enum members to handler
callables registered in `Machine.__init__`; `Machine.run()` parses the `#CMD` payload and calls
`dispatch()`. The pre-existing `#INF POWER_CYCLE_REQUEST` message is kept for backward
compatibility but is now just routed through the same dispatcher (`DUTCommand.HARD_REBOOT`).
Adding a new remote command is a two-step, additive change: add a `DUTCommand` member, then
`dispatcher.register(...)` a handler — no changes needed to the message-parsing code in `run()`.

### Command/benchmark selection (`server/command_factory.py`)

`CommandFactory` loads one or more JSON files (a DUT config's `json_files` list) into a FIFO queue
of benchmark definitions (`exec`, `killcmd`, `codename`, `header`). It pops one command at a time
and keeps running it until `command_window` seconds elapse, then rotates to the next; the queue
refills from the original list once exhausted, so benchmarks cycle indefinitely.

### DUT logging (`server/dut_logging.py`)

`DUTLogging` lazily creates one timestamped log file per benchmark run (filename encodes
date/test/ECC-status/hostname), on the first message received. The DUT protocol reserves the first
byte of every UDP payload for ECC status (`0xD`=OFF, `0xE`=ON); the remainder is decoded ASCII text
(falling back to a per-byte `chr()` reconstruction if `UnicodeDecodeError` occurs, since the DUT
may occasionally send non-ASCII bytes). `finish_this_dut_log` writes a trailer line whose `EndStatus`
records *why* the run ended (normal end, soft app/OS reboot, hard reboot, unknown/`__del__`).

### Power switch control (`server/reboot_machine.py`)

Only `reboot_machine`, `turn_machine_on`, `turn_machine_off` are the public API; everything else is
prefixed `_`/`__`. Two switch backends are supported via `switch_model` in the DUT config: `"lindy"`
(HTTP POST to the switch's `.cgi` endpoints) and `"default"` (shells out to `curl` via `os.system`,
parsing the raw curl progress-meter output to detect success — fragile but intentional, this switch
has no structured API). All switch commands go through `__GLOBAL_LOCK`, a single module-level
`threading.Lock`, since concurrent HTTP/curl calls to the same switch caused issues in the field —
keep new switch backends behind that lock too.

### Config files

- `server_parameters.yaml`: top-level — `server_ip`, `server_log_file`, `server_log_store_dir`, and
  the list of `machines` (each an `{enabled, cfg_file}` pair pointing at a per-DUT YAML file).
- `machines_cfgs/*.yaml`: one per physical DUT — network identity, power switch details, timing
  knobs (`boot_waiting_time`, `max_timeout_time`), console transport (`connection_type: telnet`,
  the default, or `jtag` with `jtag_port`/`jtag_baudrate`), and a `json_files` list of benchmark
  definitions. Same schema and one file per DUT regardless of transport — only the
  transport-specific fields differ.
- `machines_cfgs/*.json`: benchmark definitions consumed by `CommandFactory` (see above).

### Logging (`server/logger_formatter.py`, `server/print_manager.py`)

All modules log through `logging.getLogger(f"{logger_name}.{__name__}")`, where `logger_name` is
threaded down from `server.py`'s `PARENT_LOGGER_NAME` through `Machine` into every submodule it
owns — this keeps every log line attributable to a specific machine thread/module even though
`logging_setup` is only called once. `--enable_curses` swaps the console handler for one that feeds
a `queue.Queue` consumed by `ConsoleCursesManager`, a separate thread that renders one live-updating
panel per thread name; the plain-file handler (`server_log_file`) is unaffected either way.

### `parser_server_log.py`

Standalone offline script (not imported by the server) that regexes a produced `server.log` file
to tally hard/OS/app reboot counts per hostname using pandas. Useful as a reference for the log line
formats emitted by `logger_formatter.py`, but has no runtime dependency on the rest of the package.
