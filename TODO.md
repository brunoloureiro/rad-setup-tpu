# Versal support

## Quick reset

Use the tcl scripts to re-deploy upon seeing a crash/exit/abort/etc.

### SDCs

The current implementation of the experiment setup (re)loads the input/golden data from DRAM... this is obviously problematic. One option is to actually have it re-read from SD card (adds a lot of overhead + interrupts), or to have the server push the binary via xsdb (not the worst, but need to benchmark it). The other option is just a full elf reset each time. Benchmark and evaluate these options.

# Operator -> Machine command interface (planned, design in progress)

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

- `REBOOT_NOW` — no parameters; forces an immediate hard power cycle of that DUT (same underlying
  action as the existing `#INF POWER_CYCLE_REQUEST` / `DUTCommand.HARD_REBOOT` path, just
  operator-triggered instead of DUT-triggered).
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
- `cmd=<command>` — one of the statically known command names (`REBOOT_NOW`, `SLEEP`,
  `SWITCH_BENCHMARK`, ... see command list above).
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

### Monitor thread API

- One `Monitor` instance per `Machine`, spawned as its own `threading.Thread` from within (or
  alongside) that `Machine`'s own startup — scoped to exactly one DUT, the same way each `Machine`
  already owns its message channel and console connection independently. No global/shared monitor
  thread.
- The owning `Machine` passes the monitor a bound reference to one of its own methods at
  construction time — the working name is `Machine.command(name, **params)` (exact name/signature
  TBD) — as the *only* way the monitor thread is allowed to affect that machine. The monitor never
  reaches into `Machine` internals directly; it only ever calls that one injected method, with
  already-validated `(cmd, params)` — the same call shape the CLI drives once it has resolved which
  `Machine` a parsed command targets. So `Machine.command(...)` is the actual single command API;
  the CLI and any `Monitor` implementation are just two front-ends onto it.
- `Machine.command(...)` itself still needs to hand the command off safely into that machine's own
  `run()` loop (likely a thread-safe queue polled alongside the existing receive-loop timeout,
  similar in spirit to how `__stop_event` is polled) rather than mutating `Machine` state directly
  from the monitor's thread.
- Still open, to discuss next: how a specific `Monitor` implementation/transport is selected per
  machine (a new YAML field? one fixed implementation for all machines? pluggable?).

## Non-negotiable: doesn't compromise "the server must never crash"

Per CLAUDE.md's prime directive — a new inbound-command listener (CLI input loop or monitor
thread) is new, less-trusted-input surface, and it must not be able to bring the process down: no
`eval`/`exec`/arbitrary shell dispatch (the static enum is precisely what rules that out),
malformed/unknown commands get logged and dropped rather than raising into the command-handling
thread, and a stuck/misbehaving command source (e.g. a monitor connection that hangs) must not be
able to block a `Machine`'s own receive loop indefinitely.

Implementation not started — this section is a design placeholder to be expanded as the two
features get fleshed out.