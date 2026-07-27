# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`radiation-setup` is the Python server component of the RADHelper framework. It runs outside a
beam room during radiation experiments, coordinating one or more Devices Under Test (DUTs). For
each DUT it: powers the device on via a network power switch, (re)starts its application, listens
for status/log messages from the DUT (sent by the `libLogHelper` client library), and reboots the
device (soft app restart, soft OS reboot, or hard power cycle) when it stops responding or requests
one.

Each DUT is configured along **two independent axes** (both per-DUT YAML fields, see "Config
files" below):

- **`dut_mode`: `active` vs `passive`** — how the app is (re)started.
  - `active` (default): the DUT runs an OS/shell. The server logs into its console and issues
    kill/run commands (from the JSON files listed in `json_files`). See "Machine lifecycle" and
    "DUT console connection" below.
  - `passive`: the DUT is bare-metal (no OS/shell). The server runs a local command (`redeploy_cmd`
    in the DUT's YAML, e.g. a TCL script driven through a JTAG debugger) to (re)load and start the
    app. See "Passive DUT deployment" below.
- **`console_type`: `telnet` vs `jtag`** — only meaningful for `dut_mode: active` (a `passive` DUT
  never opens a console at all); selects the transport used to log into the DUT and issue kill/run
  commands.
  - `telnet` (default): a network Telnet connection, requires `ip`, `username`, `password` in the
    DUT's YAML.
  - `jtag`: the JTAG probe's serial/UART bridge (`console_jtag_port`/`console_jtag_baudrate` in the
    DUT's YAML), for DUTs with no network path to a console at all; still requires `username`,
    `password` but not `ip`. See "DUT console connection" below.
- **`connection_type`: `ethernet` vs `jtag`** — how the server *listens for DUT status/log
  messages* (`#IT`, `#LOGFILE`, `#CMD`, ...).
  - `ethernet` (default): a UDP socket bound to `server_ip:receive_port`, requires the DUT to have
    a working network stack pointed at this server.
  - `jtag`: the JTAG probe's serial/UART bridge (`jtag_port`/`jtag_baudrate` in the DUT's YAML),
    for DUTs with no network stack at all. See "DUT message channel" below.

These three axes are all independent — e.g. a `passive` bare-metal DUT can report status over
`ethernet` if it happens to have a network stack (`machines_cfgs/versal_bm_eth_passive.yaml`) or
over `jtag` if it doesn't (`machines_cfgs/versal_bm_jtag_passive.yaml`); an `active` OS-based DUT
almost always uses `console_type: telnet` and `connection_type: ethernet`, since it has a network
stack anyway, but a DUT whose only console path is through a JTAG probe's UART bridge (no network
route to a Telnet console) can set `console_type: jtag` while still reporting status over
`connection_type: ethernet`, if the board's network stack is otherwise functional - `console_type`
and `connection_type` may independently point at the same or different serial devices/JTAG probes.
`console_type` has no effect for `dut_mode: passive` (no console is ever opened), and
`connection_type: jtag` is unrelated to `console_type: jtag` even though both may reuse the phrase
"JTAG probe's serial/UART bridge" - one is the message channel, the other is the console.

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
particular change. `test_dut_commands.py` is fully hermetic (pure dispatcher logic, no I/O).
`test_dut_connection.py` is also fully hermetic: it exercises `JTAGDUTConnection` (open/login/
write/read_very_eager/close) against a simulated DUT, using a `FakeSerial` in-memory duplex
substitute (monkeypatched over `serial.Serial`) driven by a background thread that plays the DUT
side of a login handshake — no real JTAG hardware, pty, or OS tty involved.
`test_machine_config.py` is likewise hermetic: it builds `Machine` instances (never `.run()`/
`.start()`'d) from temp YAML configs to check `console_type`/`console_jtag_port` validation, using
`connection_type: ethernet` (an in-process UDP socket) so no serial device is ever opened by
`Machine.__init__` itself. Don't expect the hardware-dependent tests to pass in a sandboxed/CI
environment without the physical rig; when changing shared logic, reason about correctness
directly rather than trusting a green run.

## Architecture

### Threading model

`server.py:main` reads `server_parameters.yaml`, then spawns one `Machine` thread
(`server/machine.py`) per enabled entry under `machines`. Each `Machine` is a `threading.Thread`
that owns a `MessageChannel` (a UDP socket or a JTAG serial port, see "DUT message channel" below)
and runs an independent state machine for exactly one DUT — machines never share state.
`threading.excepthook` is overridden so that if any Machine thread dies uncaught, the whole server
logs it and exits (`__machine_thread_exception_handler` in `server.py`); a SIGINT handler does an
orderly shutdown of all machines via `Machine.stop()` (sets a `threading.Event`, closes the message
channel) followed by `join()`.

### Machine lifecycle (`server/machine.py`)

`Machine.run()` is the core loop:
1. Power the DUT on (`reboot_machine.turn_machine_on`), then wait for it to be ready
   (`__wait_for_booting`): for `dut_mode: active` this polls via console login (plus a ping check
   first, only when `console_type: telnet` - a JTAG console has no IP to ping); for
   `dut_mode: passive` this returns immediately (no console to probe, and `redeploy_cmd` performs
   any board-specific settle waits itself — see "Passive DUT deployment" below).
2. (Re)start the app for the first time (`__soft_app_reboot`): console kill+run commands (Telnet or
   JTAG, per `console_type`) for `active` DUTs, or `redeploy_cmd` for `passive` ones
   (`__passive_redeploy`). Either way this also opens a new `DUTLogging` file for the run.
3. Loop on `self.__message_channel.receive()` with a timeout (`max_timeout_time` from the
   machine's YAML config) — a UDP `recvfrom` or a JTAG serial read depending on `connection_type`,
   see "DUT message channel" below. Every received message is: (a) appended to the current
   `DUTLogging` file, and (b) classified via `PossibleMessages.get_message_type` (a
   `#LOGFILE`/`#IT`/`#HEADER`/`#BEGIN`/`#END`/`#INF`/`#ERR`/`#SDC`/`#ABORT`/`#CMD`/
   `#INF POWER_CYCLE_REQUEST` prefix protocol shared with `libLogHelper`).
4. On a `MessageChannel.receive()` timeout, escalate through three levels with per-level retry
   counters that reset when good data (`#IT`) arrives: soft app reboot -> soft OS reboot (skippable
   via `disable_os_soft_reboot`, and always disabled for `passive` DUTs since there is no OS) ->
   hard power cycle. A `#INF POWER_CYCLE_REQUEST` message forces an immediate hard reboot
   regardless of timeout state; a `#CMD <NAME>` message runs whatever the DUT asked for (see DUT
   commands below).
5. `CommandFactory.is_command_window_timed_out` is also checked on every received message so a
   benchmark that runs longer than its configured window gets restarted even without a timeout
   (only applies when `json_files` is configured — see "Config files" below).

Reboot counters (`__soft_app_reboot_count`, `__soft_os_reboot_count`, `__hard_reboot_count`) are
reset at different points intentionally (e.g. a hard reboot resets both soft counters) — this
encodes the escalation policy, so don't "simplify" the reset logic without re-reading the
surrounding comments in `machine.py`.

Never use `time.sleep()` inside `Machine` for waits that should be interruptible on shutdown —
use `self.__stop_event.wait(seconds)` instead (existing code follows this convention throughout).

### DUT console connection (`server/dut_connection.py`)

`Machine` talks to an `active`-mode DUT's console through a `DUTConnection` abstraction with two
implementations selected per-machine by that DUT's `console_type` field (`"telnet"`, the default,
or `"jtag"`): `TelnetDUTConnection` (network Telnet) and `JTAGDUTConnection` (a serial console
reached through a JTAG probe's UART bridge, via `pyserial`; config fields `console_jtag_port` and
optional `console_jtag_baudrate`, kept separate from `connection_type: jtag`'s `jtag_port`/
`jtag_baudrate` since the two may be different serial devices — see "What this is" above). Both are
built on four raw I/O primitives (`open`/`write`/`read_until`/`read_very_eager`/`close`); the login
handshake (username/password/shell prompts) is implemented once in `DUTConnection.login()`.
`Machine.__dut_login()` builds a fresh connection via `create_dut_connection(...)` and logs in.
Console access is independent of `connection_type` (that field only selects the message-listening
transport, see below) — adding a third console transport (e.g. SSH) means implementing
`DUTConnection`'s four primitives and adding a branch to `create_dut_connection`; nothing else in
`Machine` changes.

`JTAGDUTConnection.open()` follows the same up-front-validation pattern as `JTAGMessageChannel.open()`
below: it checks `os.path.exists(console_jtag_port)` before ever touching `pyserial`, so a
wrong/unplugged port produces one clear log line instead of a bare stack trace or a silent hang.

### DUT message channel (`server/dut_message_channel.py`)

`Machine` listens for DUT status/log messages through a `MessageChannel` abstraction with two
implementations selected per-machine by the `connection_type` field in that DUT's YAML config
(`"ethernet"`, the default, or `"jtag"`): `EthernetMessageChannel` (a UDP socket bound to
`server_ip:receive_port`, the original behavior) and `JTAGMessageChannel` (reads the JTAG probe's
serial/UART bridge, via `pyserial`; config fields `jtag_port` and optional `jtag_baudrate`).
`JTAGMessageChannel` frames messages by splitting the serial byte stream on `\n` — it expects the
DUT to write one ASCII-text message per line, the same wire format `libLogHelper` uses per UDP
datagram (see `dut_logging.py`). Both implementations raise
`TimeoutError` from `receive()` when no message arrives within `max_timeout_time`, so
`Machine.run()`'s receive loop is transport-agnostic. This is independent of `dut_mode` — see "What
this is" above.

Both `TelnetDUTConnection.open()` and `JTAGMessageChannel.open()` check preconditions and log
clearly before failing (e.g. `JTAGMessageChannel` checks `os.path.exists(jtag_port)` up front)
rather than letting a missing device/host produce a bare, easy-to-miss stack trace or a silent
retry loop — keep that pattern when adding new transports.

`JTAGMessageChannel.receive()` also treats a mid-run serial disconnect (e.g. the USB JTAG/UART
adapter dropping out, which can happen when a board reset briefly cuts power to the onboard FTDI
chip) the same way as a plain timeout: it catches `serial.SerialException`/`OSError` from the
read and closes the now-broken `serial.Serial` handle, but rather than immediately raising
`TimeoutError`, it first tries `__reconnect_with_retries()` — up to
`JTAGMessageChannel.MAX_JTAG_RECONNECT_ATTEMPTS` (hard-coded, defaults to 5) reopen attempts,
spaced `redeploy_on_disconnect_delay / MAX_JTAG_RECONNECT_ATTEMPTS` seconds apart (`stop_event`,
threaded down from `Machine`, makes that wait interruptible on shutdown). `redeploy_on_disconnect_delay`
is a per-DUT YAML field (only meaningful for `connection_type: jtag`, defaults to 1.0s if
omitted) — it's the total time budget spent absorbing a brief adapter hiccup before giving up.
Only if the port is still unavailable after all attempts does `receive()` raise `TimeoutError`,
which feeds into `Machine.run()`'s existing timeout-escalation logic (soft app reboot/redeploy ->
soft OS reboot -> hard power cycle) exactly like an unresponsive DUT would — for a
`dut_mode: passive` DUT this means `redeploy_cmd` and a power-switch cycle, matching the
active-mode Telnet-unreachable case. If reconnection does succeed (either during this retry loop
or on a later `receive()` call, since a still-`None` `__serial` is retried every call), it
self-heals without ever needing to escalate.

### DUT-requested commands (`server/dut_commands.py`)

A DUT can ask the server to perform an action at runtime by sending a `#CMD <NAME>` message over
whichever `connection_type` transport is configured (e.g. `#CMD HARD_REBOOT`). `DUTCommandDispatcher`
maps `DUTCommand` enum members to handler callables registered in `Machine.__init__`; `Machine.run()`
parses the `#CMD` payload and calls `dispatch()`. The pre-existing `#INF POWER_CYCLE_REQUEST`
message is kept for backward compatibility but is now just routed through the same dispatcher
(`DUTCommand.HARD_REBOOT`). Adding a new remote command is a two-step, additive change: add a
`DUTCommand` member, then `dispatcher.register(...)` a handler — no changes needed to the
message-parsing code in `run()`.

### Passive DUT deployment (`server/dut_deployment.py`)

For `dut_mode: passive` DUTs, `Machine.__passive_redeploy()` (called from `__soft_app_reboot`
instead of the Telnet kill+run path) calls `redeploy_dut()`, which runs the DUT's configured
`redeploy_cmd` (a shell-style string or, preferably, a YAML argv list — avoids shell
quoting/injection) as a subprocess. `redeploy_dut()` streams the subprocess's combined
stdout/stderr into the log line-by-line as it runs (prefixed `[redeploy]`), rather than only
surfacing output at the end — these commands (e.g. `xsct`/`xsdb` driving a JTAG probe) can take
up to a couple minutes, and silently waiting that whole time gives no indication of progress.
Timeout is enforced with a background reader thread + polling loop rather than
`subprocess.run(timeout=...)`, since reading `process.stdout` for streaming would otherwise block
past the deadline if the subprocess stops producing output without exiting.

Unlike `active` DUTs' `__wait_for_booting`, which polls (ping + Telnet login) for up to
`boot_waiting_time` before the app is (re)started, `passive` DUTs skip that wait entirely and run
`redeploy_cmd` immediately after power-on — `redeploy_cmd` scripts are expected to perform any
board-specific reset/settle waits themselves (see e.g. `machines_cfgs/deploy_versal_jtag.sh`,
which switches JTAG boot mode, resets the board, and sleeps before programming).

`machines_cfgs/deploy_versal_jtag.sh` is a reference `redeploy_cmd` implementation for Xilinx
Versal boards: it validates its inputs up front (PDI/ELF files exist, the `versal_scripts` TCL
subtree is present, `xsdb` is on `PATH`, `hw_server` is reachable) before touching `xsdb`, since
those are otherwise silent failure points that would only surface as an opaque TCL error deep
inside `xsdb -eval`.

### Command/benchmark selection (`server/command_factory.py`)

`CommandFactory` loads one or more JSON files (a DUT config's `json_files` list) into a FIFO queue
of benchmark definitions (`exec`, `killcmd`, `codename`, `header`). It pops one command at a time
and keeps running it until `command_window` seconds elapse, then rotates to the next; the queue
refills from the original list once exhausted, so benchmarks cycle indefinitely.

### DUT logging (`server/dut_logging.py`)

`DUTLogging` lazily creates one timestamped log file per benchmark run (filename encodes
date/test/hostname), on the first message received. Every message (UDP datagram or JTAG serial
line, see "DUT message channel" above) is decoded ASCII text (falling back to a per-byte `chr()`
reconstruction if `UnicodeDecodeError` occurs, since the DUT may occasionally send non-ASCII
bytes). `finish_this_dut_log` writes a trailer line whose `EndStatus` records *why* the run ended
(normal end, soft app/OS reboot, hard reboot, unknown/`__del__`).

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
- `machines_cfgs/*.yaml`: one per physical DUT, combining the three independent axes described in
  "What this is" above:
  - `dut_mode: active` (default) or `passive`, plus whichever fields that mode needs: `active`
    needs `username`/`password` and `json_files` (benchmarks); `passive` needs `redeploy_cmd` (and
    optionally `redeploy_timeout`, `test_name`/`test_header` in place of `json_files`).
  - For `dut_mode: active` only, `console_type: telnet` (default) or `jtag` further selects what
    the console needs: `telnet` needs `ip`; `jtag` needs `console_jtag_port` (and optionally
    `console_jtag_baudrate`) instead. Ignored entirely for `dut_mode: passive`.
  - `connection_type: ethernet` (default) or `jtag`, plus whichever fields that transport needs:
    `ethernet` needs `receive_port`; `jtag` needs `jtag_port` (and optionally `jtag_baudrate`).
  - Plus power switch details (`power_switch_ip`/`power_switch_port`/`power_switch_model`) and
    timing knobs (`boot_waiting_time`, `max_timeout_time`, `disable_os_soft_reboot`,
    `restart_interval`) common to every DUT. Same schema for every DUT regardless of which
    `dut_mode`/`connection_type` combination is in use — only the mode/transport-specific fields
    differ, and `Machine.__init__` validates that the fields required by the configured
    combination are present.
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
