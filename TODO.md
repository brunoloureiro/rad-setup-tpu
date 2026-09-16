# Versal support

## Quick reset

Use the tcl scripts to re-deploy upon seeing a crash/exit/abort/etc.

### SDCs

The current implementation of the experiment setup (re)loads the input/golden data from DRAM... this is obviously problematic. One option is to actually have it re-read from SD card (adds a lot of overhead + interrupts), or to have the server push the binary via xsdb (not the worst, but need to benchmark it). The other option is just a full elf reset each time. Benchmark and evaluate these options.

# Operator -> Machine command interface (command execution, CLI, and Monitor all implemented)

Implemented so far: the static command list/dispatcher (`server/machine_commands.py`), the
`Machine.command(...)` entry point + thread-safe queue/drain (`server/machine.py`), the
interactive CLI (`server/command_cli.py`, wired into `server.py` for `--enable_curses`-off runs),
and the per-machine Monitor thread (`server/monitors/` - base class, registry, one example
implementation - see "Monitor thread API" below for the now-resolved design and machine.py's
`__start_monitor`/`__current_log_file`). Covered by hermetic tests:
`tests/test_machine_commands.py`, `tests/test_command_cli.py`,
`tests/test_machine_operator_commands.py`, `tests/test_monitors.py`, `tests/test_machine_monitor.py`.

Two deliberate deviations from the original write-up below:
- `SWITCH_BENCHMARK`'s parameter identifies a benchmark by its **codename** (the `codename` field
  already present on every entry loaded from `json_files`), not by a JSON filename - a single
  json_files entry can itself be a list of several benchmarks (see `machines_cfgs/dummy.json`),
  so codename is the only unambiguous per-benchmark identifier already present in
  `CommandFactory`'s loaded data; `CommandFactory.switch_to_benchmark(codename)`/`known_codenames`
  implement the lookup.
- The two reboot-style commands ended up named `SOFT_REBOOT` and `POWER_CYCLE` (not `REBOOT_NOW`)
  - "now" is implied (there is no delayed/scheduled variant of either), and having both a soft and
    a hard operator-triggered reboot command mirrors `DUTCommand`'s own `SOFT_REBOOT`/`HARD_REBOOT`
    pair.

Still pending, not implemented yet: curses-mode integration for the interactive CLI (see
`InteractiveCommandCLI`'s docstring - it is currently disabled under `--enable_curses` since a
concurrent `input()` loop is not compatible with `curses.initscr()` owning the terminal), and any
per-DUT way to override a Monitor's own constructor kwargs from YAML (e.g. `PeriodicRebootMonitor`'s
interval is currently only overridable by constructing it directly in code, not via any
`monitor:`-adjacent YAML field - `__start_monitor` always instantiates with just the base
constructor args).

## Original design notes

Two related features, both just different *transports* for the same underlying idea: letting an
operator tell a running `Machine` thread to do something on demand, instead of only reacting to
what the DUT sends. This is the mirror image of the existing DUT -> server channel
(`#CMD <NAME>`, `server/dut_commands.py`'s `DUTCommand`/`DUTCommandDispatcher`) — same shape
(static enum + dispatcher, additive to extend), opposite direction (operator -> `Machine` instead
of DUT -> `Machine`).

## Command list must be static and enumerable

Not an arbitrary shell/script/eval sent to the server — a fixed, known set of commands, each with
its own typed, minimal parameter shape, mirroring how `DUTCommand` is a closed enum rather than a
free-form string. Candidate first commands (exact names/params TBD):

- `SOFT_REBOOT` — no parameters; restarts the app without power cycling (console kill+run for
  active DUTs, redeploy_cmd for passive ones) - same underlying action as `DUTCommand.SOFT_REBOOT`,
  just operator-triggered. Not guaranteed to succeed on every request (console unreachable, or
  this DUT already hit its soft-reboot retry ceiling) - the handler logs a warning rather than
  raising in that case, same as everywhere else in this codebase.
- `POWER_CYCLE` — no parameters ("now" is implied, there is no delayed/scheduled variant); forces
  an immediate hard power cycle of that DUT (same underlying action as the existing
  `#INF POWER_CYCLE_REQUEST` / `DUTCommand.HARD_REBOOT` path, just operator-triggered instead of
  DUT-triggered).
- `SLEEP` — one numeric parameter (seconds); pause that DUT's monitoring for the given duration.
  Needs to interact carefully with `Machine.run()`'s existing timeout-escalation counters (see
  `machine.py`'s "Reboot counters ... reset at different points intentionally" note in CLAUDE.md)
  so a deliberate sleep isn't mistaken for an unresponsive DUT and doesn't trigger a spurious
  reboot escalation.
- `SWITCH_BENCHMARK` — one string parameter (a benchmark JSON filename, i.e. one of the entries
  normally listed under that DUT's `json_files` in its YAML config); swaps what `CommandFactory`
  is currently running for that machine.

Whatever new dispatch mechanism backs these should follow the same enum-member + registered-
handler pattern `DUTCommandDispatcher` already uses, so adding a fourth command later stays a
two-step additive change, not a rewrite.

## Two delivery mechanisms, same command API

1. **Interactive CLI**, ideally live in the same terminal as the current monitoring output (plain
   stdout or `--enable_curses`) rather than a separate tool — exact UX (a command prompt line
   under/alongside the curses panels? a separate key-binding mode?) still to be worked out, but the
   message format it parses is fixed (see below).
2. **A "monitor"**: a Python thread, one per `Machine` (see "Monitor thread API" below), that calls
   the same underlying per-machine command method the CLI ends up calling once it has resolved a
   target `Machine`.

Both are just producers feeding the same static command API against a target `Machine` — the CLI
and the monitor are two front-ends onto one call shape, not two separate dispatch mechanisms.

### Shared command message format (CLI today; same shape the monitor API speaks internally)

Every command message reduces to a `(dut, cmd, params)` triple:

- `dut=<dut_name>` — resolved in two steps, tried in order:
  1. Treat `<dut_name>` as a machine-config filename (no path, just the basename, e.g. `dut01` or
     `dut01.yaml`) and look for a `machines:` entry in the loaded `server_parameters.yaml` whose
     `cfg_file` basename matches.
  2. If no filename match, fall back to loading each listed machine's YAML (from
     `server_parameters.yaml`'s `machines:` list) and matching `<dut_name>` against that file's own
     `hostname` field instead.
  3. If neither matches any configured/enabled machine, drop the command with a warning (unknown
     DUT) — never raise.
- `cmd=<command>` — one of the statically known command names (`SOFT_REBOOT`, `POWER_CYCLE`,
  `SLEEP`, `SWITCH_BENCHMARK`, ... see command list above).
- Remaining parameters are command-specific (e.g. `SLEEP`'s duration, `SWITCH_BENCHMARK`'s
  filename) and are validated per-command (type, range, that a referenced benchmark file is
  actually one of that DUT's configured `json_files`, etc.).

The CLI accepts the same triple in three equivalent surface syntaxes, so operators can use
whichever is more convenient (all three parse to the identical `(dut, cmd, params)` before
dispatch):

- **Positional**: `<dut_name> <command> <arg1> [arg2 ...]`
- **Flag-style**: `--dut <dut_name> --command <command> --<param> <value> ...`
- **Key=value**: `dut=<dut_name> command=<command> <param>=<value> ...`

Any parse failure — unknown DUT, unknown command, missing/malformed/out-of-range parameters, or
input matching none of the three syntaxes — is logged as a warning and the input is dropped.
Nothing here may raise past the CLI's own input loop; this is the same "never crash" rule as
everywhere else in this codebase (see CLAUDE.md's prime directive).

### Monitor thread API (implemented)

- One `Monitor` instance per `Machine`, spawned as its own `threading.Thread` once that
  `Machine`'s own thread actually starts running (`Machine.run()` calls `__start_monitor()` right
  after the initial `__soft_app_reboot()`, before entering the receive loop) — scoped to exactly
  one DUT, the same way each `Machine` already owns its message channel and console connection
  independently. No global/shared monitor thread.
- The owning `Machine` passes the monitor a bound reference to `Machine.command(name, **params)`
  at construction time (`command_callback` in `server/monitors/base.py::Monitor.__init__`) — the
  *only* way a Monitor is allowed to affect its machine. A Monitor never reaches into `Machine`
  internals directly; it only ever calls that one injected method, exactly the same call shape the
  CLI drives once it has resolved which `Machine` a parsed command targets. So
  `Machine.command(...)` is the actual single command API; the CLI and any `Monitor`
  implementation are just two front-ends onto it. `Machine.command(...)` hands the command off
  through the same thread-safe queue/drain described above regardless of which of the two called it.
- **DUT log access is standard on the base class**, since most monitoring logic needs to look at
  what the DUT is actually doing: `Monitor.log_files()` globs every log file `DUTLogging` has ever
  written for this DUT (a stable directory, `machine.py`'s `__dut_log_path`), and
  `Monitor.current_log_file()` returns whichever one is currently open (or `None` between app
  restarts) via a `current_log_file` callback the owning `Machine` provides
  (`__current_log_file`, reading its own ever-changing `__dut_logging_obj.log_filename` so the
  Monitor never touches that private, moving-target attribute directly).
- Selection per-DUT (previously open, now resolved): a `monitor:` field in that DUT's YAML config
  names one entry in `server/monitors/enabled_monitors.py`'s `MONITORS` dict
  (`{name: MonitorClass}`, exactly the plain-dict-registry approach discussed - no
  reflection/auto-discovery). `enabled_monitors.py` is the one file to edit to plug in a custom
  monitor: write the subclass in its own file under `server/monitors/`, import it there, and
  `_register(name, cls)` it - each import is wrapped in its own `try/except` (a broken custom
  monitor module can only make its own name unavailable, never prevent the server from starting
  for any other DUT), and a duplicate name keeps the first registration and logs a warning about
  the second, per your call. No `monitor:` field (the default) just means no monitor for that DUT;
  an unrecognized name is logged as an error and that machine simply runs without one - neither
  case raises.
- Built-in example: `server/monitors/periodic_reboot_monitor.py`'s `PeriodicRebootMonitor`
  (registered as `"periodic_reboot"`) calls `command_callback("POWER_CYCLE")` every
  `interval_seconds` (default 180s/3 minutes) via `self._stop_event.wait(interval_seconds)` -
  purely internal timer logic, same pattern every other interruptible wait in this codebase
  follows, so shutdown is prompt rather than waiting out the rest of the interval.

## Non-negotiable: doesn't compromise "the server must never crash"

Per CLAUDE.md's prime directive — the CLI's input loop and every Monitor thread are new,
less-trusted-input surfaces, and neither can be allowed to bring the process down: no
`eval`/`exec`/arbitrary shell dispatch (the static enum is precisely what rules that out),
malformed/unknown commands and unknown/failing monitor names are logged and dropped rather than
raising, and `MachineCommandDispatcher.dispatch()` wraps handler execution in its own
`try/except` as a backstop on top of each handler validating its own parameters. Still a
Monitor's own `run()` loop is squarely that Monitor implementation's own responsibility to keep
exception-free (see `server/monitors/base.py`'s docstring) - the dispatcher backstop only covers
what happens *inside* `Machine.command(...)`'s dispatch, not a Monitor's independent thread.