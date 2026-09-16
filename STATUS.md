# Status: operator -> Machine command interface

Snapshot of what's implemented, what's tested, and what's still open for the operator command
feature (static command API, `Machine.command()`, the interactive CLI, and per-machine Monitor
threads - see `OPERATOR_COMMANDS.md` for the full design). Update this file as the feature
evolves rather than trusting it to stay accurate on its own.

## Done

- **Static command API** (`server/machine_commands.py`): `MachineCommand` enum - `SOFT_REBOOT`,
  `POWER_CYCLE`, `SLEEP`, `SWITCH_BENCHMARK` - dispatched via `MachineCommandDispatcher`.
- **Machine-side execution** (`server/machine.py`): `Machine.command()` entry point, thread-safe
  queue drained from `run()`, all four handlers wired up.
- **Interactive CLI** (`server/command_cli.py`): three syntaxes (positional/flag/key=value), each
  usable with partial input filled in via interactive follow-up prompts; DUT resolution (config
  filename -> hostname fallback); cancel words (`q`/`quit`/`cancel`/`exit`) and `help`/`?` at
  every prompt; immediate, specific validation feedback shared with `Machine`'s own handlers
  (`machine_commands.py`'s `COMMAND_PARAMS`/`validate_command_params`); wired into `server.py`
  for non-curses runs.
- **Two-stage Ctrl+C** (`server.py`): first Ctrl+C stops only the CLI; a further one stops the
  server, but only after `cli_shutdown_confirm_delay` seconds (default 5.0, configurable in
  `server_parameters.yaml`) have passed - guards against an accidental double press ending a run.
- **Monitor framework** (`server/monitors/`): `Monitor` base class with DUT log access,
  `enabled_monitors.py` registry, `PeriodicRebootMonitor` reference implementation, wired into
  `Machine.run()` via a `monitor:` YAML field.
- **Tests**: hermetic, covering the dispatcher, the parser (including partial-input/cancel/help
  behavior via a piped fake stdin driving a real `InteractiveCommandCLI` thread), the
  DUT-resolution logic, the Monitor base class, the registry's import-isolation/duplicate-name
  behavior, the shared parameter validator, and the Ctrl+C decision logic.
- **Docs**: `CLAUDE.md` and `OPERATOR_COMMANDS.md` (formerly `TODO.md`) reflect the shipped
  architecture as it stands.

## Left to do / test

- **Curses-mode CLI integration** - `InteractiveCommandCLI` is currently disabled under
  `--enable_curses` (its stdin reading conflicts with `curses.initscr()` owning the terminal). No
  input line exists in curses mode yet.
- **Per-monitor YAML config** - `PeriodicRebootMonitor`'s interval (and any future monitor's own
  tunables) can't be overridden from a DUT's YAML; `__start_monitor` only passes the fixed
  base-class args. Would need a generic way to pass extra kwargs through the registry.
- **Real hardware validation** - everything so far is hermetic/unit-tested with fakes
  (`FakeSerial`-style stubs, in-process UDP, no real console/power-switch/JTAG, and now a piped
  fake stdin for the interactive CLI). Nobody has yet run this against an actual DUT to confirm,
  e.g., that a `SLEEP` command issued mid-experiment behaves as expected, that `SWITCH_BENCHMARK`
  correctly hands off to the console kill/run cycle, or that `PeriodicRebootMonitor` cooperates
  with the power switch lock under real timing.
- **SWITCH_BENCHMARK edge case** - not tested against a DUT config with *multiple* benchmarks in
  one `json_files` entry list (only `machines_cfgs/dummy.json`'s single-benchmark case is
  exercised).
- **No test for an actual reboot-escalation interaction with SLEEP** - the pause-check in
  `run()`'s `TimeoutError` branch is logically verified but not exercised end-to-end against a
  real receive-loop timeout.
- **Ctrl+C two-stage shutdown debounce** - the decision logic (`_decide_sigint_action` in
  `server.py`) is unit-tested directly, but the actual signal-handling wiring (real `SIGINT`
  delivery, `sys.exit`, thread teardown) is not - that would need a subprocess-level test, not
  attempted here.
