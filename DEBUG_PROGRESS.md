# JTAG passive DUT debugging — progress log

Goal: figure out why `server.py` (config `machines_cfgs/versal_bm_jtag_passive.yaml`) is not
receiving any messages from the DUT over `/dev/ttyUSB1`, and confirm `redeploy_cmd` actually runs
successfully.

## Environment checks (before starting server)

- `/dev/ttyUSB1` exists, permissions `crw-rw-rw-` (666) — world read/write, so group membership
  (`dialout`) is not required. User `loureiro` is *not* in the `dialout` group, but this doesn't
  matter given the 666 perms.
- `machines_cfgs/versal_files/*.pdi`/`*.elf` symlinks exist and resolve into
  `~/repos/versal-aie-dev/build/default/...` — need to confirm targets actually exist (not yet
  checked).
- `machines_cfgs/versal_scripts/{debug.tcl,deploy.tcl}` present (subtree pulled).
- Config/code review of `dut_message_channel.py`, `dut_deployment.py`, `machine.py` shows no
  obvious logic bug in the jtag/passive wiring — moving to a live run to observe actual behavior.

## Environment setup

- `source ~/source_vitis.sh` + `conda activate rad-setup-single` works fine; `xsdb` ends up on
  `PATH` and `hw_server` (already running from an earlier manual session, pid seen in `ps`) answers
  on `localhost:3121`. (My first check of this appeared to fail because I piped `source ... | tail`,
  which runs `source` in a subshell — not a real issue, just my own test mistake.)
- `/dev/ttyUSB1` exists, world read/write (666), so the fact the `loureiro` user isn't in the
  `dialout` group doesn't matter.
- `machines_cfgs/versal_files/*.pdi`/`*.elf` symlinks resolve to real, non-empty files under
  `~/repos/versal-aie-dev/build/default/...` — good.
- `machines_cfgs/versal_scripts/{debug.tcl,deploy.tcl}` present.
- **Noted but not yet acted on**: `journalctl -k` shows the FTDI JTAG/UART adapter (both
  `ttyUSB0`+`ttyUSB1`) has disconnected/reconnected together 4 times today, with `error from
  flowcontrol urb` / `failed to get modem status: -71` around each drop. USB autosuspend is
  currently *off* for this device, so that's not the live cause — more likely the board's PMC
  reset (as part of `debug.tcl`) briefly drops power to the onboard FTDI chip. Worth keeping an eye
  on if messages stop arriving mid-run after a redeploy.

## ROOT CAUSE #1 (found): power switch is unreachable, and the switch HTTP call has no timeout

Started `python3 server.py` for real. It logged normal startup (JTAG port opened OK), then called
`turn_machine_on` for the Lindy power switch at `192.168.0.100` — and hung there for 100+ seconds
with no further log output.

Investigated:
- `ip route` / `ip addr` on this host show **no route to `192.168.0.0/24`** at all right now: only
  `wlp0s20f3` (WiFi, `192.168.1.0/24`), a ZeroTier tunnel (`192.168.195.0/24`), and `docker0`. There
  is no wired Ethernet NIC on this machine currently, so `192.168.0.100` (the power switch) is
  simply unreachable from here.
- `server/reboot_machine.py`'s `_lindy_switch()` calls `requests.post(url, ...)` **with no
  `timeout=` argument**. There's a dead `except requests.exceptions.Timeout` handler right below it
  that can never fire, because nothing ever times out — it just hangs until the OS-level TCP
  connect timeout (~2 minutes). Since `turn_machine_on` runs synchronously at the very top of
  `Machine.run()`, this blocks the entire Machine thread — it never even reaches
  `__wait_for_booting`/`__passive_redeploy`/the JTAG receive loop while it's stuck here. This alone
  is sufficient to explain "the server isn't receiving any messages": it never gets that far.
- Asked you how to proceed; you chose to let the current run time out and continue (the code
  already tolerates a failed power-on and proceeds anyway — see `machine.py:250-251`), rather than
  fixing the network path or patching the missing timeout right now.
- Currently waiting out the hang via a background Monitor watching for the timeout log line /
  redeploy start / first DUT message.

**Flagging for later**: even once the network path issue is sorted, `_lindy_switch()` should get an
explicit `timeout=` on its `requests.post()` call so a genuinely offline/unreachable switch fails in
a few seconds (with the existing `Timeout` error path actually firing) instead of hanging the whole
Machine thread for ~2 minutes on every power-cycle attempt. Not fixed yet — flagging only, per your
choice to defer this.

## Separate fix already applied (unrelated to the above): removed the ECC status byte convention

You said you recalled that this project's assumption of a first ECC-status byte on every DUT
message is not how this DUT's protocol actually works — messages are plain ASCII, no reserved
byte. This was a **second, independent bug**: even after the power-on hang clears, the very first
real message received would have crashed the whole Machine thread anyway:
- `server/dut_logging.py`'s `DUTLogging.__call__` did `ecc_values[message[0]]` (a dict lookup
  against `{0xD: "OFF", 0xE: "ON"}`) on every message's first byte. Any real ASCII message (e.g.
  starting with `#` or a letter) is not `0xD`/`0xE`, so this would `KeyError` on the very first
  message and kill the Machine thread (which per `server.py`'s `threading.excepthook` handling
  brings down the *whole server*, not just that DUT).
- `server/machine.py`'s receive loop also stripped the first byte (`data.decode("ascii")[1:]`)
  before classifying the message type (`#IT`, `#CMD`, ...), which would have silently corrupted
  every message's first real character even if the KeyError above didn't kill things first.

Fixed both call sites to treat the whole message as plain ASCII (no byte stripped), updated the
now-stale docstrings/comments in `dut_commands.py`, `dut_message_channel.py`, and `CLAUDE.md`, and
updated `tests/test_dut_logging.py` to stop encoding/asserting on the removed ECC byte/filename
tag. `DUTLogging`'s log filenames no longer carry an `_ECC_ON`/`_ECC_OFF` segment.

## RESOLVED — server is now healthy and receiving messages

After the power-on call timed out (~00:33:14) the run proceeded exactly as designed:
- `redeploy_cmd` ran successfully (`xsdb` debug.tcl JTAG-boot-mode switch, then deploy.tcl PDI+ELF
  load), finishing in 26.4s at 00:33:40 — `SUCCESSFULLY REDEPLOYED APP`.
- The JTAG UART immediately started producing real DUT output: `logs/versal_bm_jtag/2026_07_26_00_33_40_versal_bm_jtag_versal_bm_jtag.log`
  is growing continuously (5000+ lines within ~90s) with clean, correctly-decoded ASCII text —
  `#IT <iter> KerTime:... AccTime:...`, `#INF [...] check:pre_iteration/post_iteration ...`,
  `[PERF]`/`[DEBUG]` lines from what looks like a XilSEM-based scrub-and-compare test. No more
  corrupted/truncated first characters (confirms the ECC-byte fix above was in fact necessary and
  correct — the old code would have silently eaten the first character of every one of these lines,
  and `DUTLogging` would have crashed outright on the very first message).
- Zero exceptions/tracebacks in `server.log` over a 270s+ run; the Machine thread is alive and
  stable.

**So, to directly answer "why isn't the server receiving any messages":** it was two independent,
stacked bugs, both now fixed:
1. `turn_machine_on` hanging ~2 minutes on the unreachable power switch before the Machine thread
   ever got to `redeploy_cmd`/the receive loop (see below — not fully "fixed" since it's a real
   network-reachability issue today, but the missing HTTP timeout that turned it into a multi-minute
   stall is a legitimate latent bug).
2. The ECC status-byte assumption, which — once messages *did* start arriving — would have crashed
   `DUTLogging.__call__` (`KeyError`) on the very first real message, taking down the whole server
   thread. This is now fixed per your instruction.

## Two follow-ups noted, not yet actioned (flagging for you)

1. **`reboot_machine.py`'s `_lindy_switch()` has no HTTP timeout** on its `requests.post()` call —
   an unreachable/offline switch hangs the call for the OS-level TCP connect timeout (~2 min)
   instead of failing fast. There's a dead `except requests.exceptions.Timeout` handler right below
   it that can never trigger today. Since `turn_machine_on` runs synchronously at the top of
   `Machine.run()`, this blocks the *entire* per-DUT thread (redeploy, JTAG receive, everything)
   until it gives up. Recommend adding e.g. `timeout=10` to that `requests.post()` call. Deferred
   per your choice to just let today's run time out and continue rather than patch this now.
2. **DUT sends `#CMD OPEN_BEAM`/`#CMD CLOSE_BEAM` at startup** (11 occurrences, 00:33:40–00:33:43),
   which aren't registered in `DUTCommandDispatcher` (`server/dut_commands.py` only registers
   `HARD_REBOOT`/`SOFT_REBOOT`), so each logs as `Received unknown or unregistered DUT command`.
   Harmless today (just a log line), but if these are meant to signal actual beam-open/close events
   to the server (e.g. for logging/telemetry during a real irradiation run), they currently do
   nothing. Flagging in case that's intentional-for-now vs. a gap worth closing later.

## Follow-up actions (all done)

- Added `timeout=10` to `_lindy_switch()`'s `requests.post()` in `reboot_machine.py`, so an
  unreachable switch now fails in ~10s instead of hanging the Machine thread for ~2 minutes.
- `server.py` (pid 203208) has been stopped. Note: it had actually already crashed on its own
  (before I sent the stop signal) — `journalctl -k` showed the JTAG/UART USB device
  (`/dev/ttyUSB1`) disconnected again mid-run (`error from flowcontrol urb`, same flaky pattern
  noted earlier), which raised an unhandled `SerialException` in `JTAGMessageChannel.receive()`
  and took down the whole server via the thread excepthook. `JTAGMessageChannel` does not currently
  handle a mid-run serial disconnect/reconnect - flagging as a further reliability gap, not fixed
  (out of scope for what was asked).
- Added `DUTCommand.OPEN_BEAM`/`CLOSE_BEAM` with stub (log-only) handlers
  (`Machine.__on_open_beam_command`/`__on_close_beam_command`), registered in `Machine.__init__`.
  Real behavior TBD later. Documented in `README.md`'s "DUT-requested commands" table/section.
- You've stopped the DUT, so re-running `server.py` now won't produce real DUT messages - only
  verified these changes with `py_compile`, not a live run.

(done — see chat for full summary)
