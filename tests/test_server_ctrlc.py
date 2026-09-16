"""
Hermetic test for server.py's two-stage Ctrl+C behavior (see OPERATOR_COMMANDS.md): the first
Ctrl+C stops the interactive CLI without touching the server; a further Ctrl+C only actually
stops the server once at least 'cli_shutdown_confirm_delay' seconds have passed, to guard
against an accidental double press. Only the pure decision function (_decide_sigint_action) is
tested here - it takes no signals, threads, or global state, and never calls sys.exit(), by
design (see its own docstring in server.py) specifically so this logic can be checked directly.
The real signal-handling wiring around it is not covered by an automated test.
"""
import importlib.util
import os
import unittest

# server.py (this repo's top-level script) shares its name with the server/ package (server/
# machine.py, etc.) - a plain 'import server' resolves to that package, not the script, so it is
# loaded directly by file path under a distinct module name instead. server.py's own internal
# 'from server.command_cli import ...' etc. still resolve normally against the real package,
# since only the name used *here*, for *this* module object, is different.
_server_py_path = os.path.join(os.path.dirname(__file__), "..", "server.py")
_spec = importlib.util.spec_from_file_location("radiation_setup_jtag_server_script", _server_py_path)
_server_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_server_script)  # module __name__ != "__main__", so main() is not called

_decide_sigint_action = _server_script._decide_sigint_action


class DecideSigintActionTestCase(unittest.TestCase):
    def test_stops_cli_first_while_it_is_still_alive(self):
        action = _decide_sigint_action(cli_alive=True, cli_stopped_at=None, now=1000.0, confirm_delay=5.0)
        self.assertEqual(action, "stop_cli")

    def test_stops_cli_even_if_a_previous_stop_timestamp_exists(self):
        # e.g. the CLI was restarted somehow and is alive again - still stop it first, not shut down
        action = _decide_sigint_action(cli_alive=True, cli_stopped_at=999.0, now=1000.0, confirm_delay=5.0)
        self.assertEqual(action, "stop_cli")

    def test_ignores_a_second_press_too_soon_after_stopping_the_cli(self):
        action = _decide_sigint_action(cli_alive=False, cli_stopped_at=1000.0, now=1002.0, confirm_delay=5.0)
        self.assertEqual(action, "ignore")

    def test_shuts_down_once_the_confirm_delay_has_elapsed(self):
        action = _decide_sigint_action(cli_alive=False, cli_stopped_at=1000.0, now=1005.1, confirm_delay=5.0)
        self.assertEqual(action, "shutdown")

    def test_shuts_down_immediately_when_the_cli_was_never_running(self):
        # e.g. --enable_curses: no CLI exists to stop first, so a single Ctrl+C shuts down right
        # away, exactly as before this feature existed.
        action = _decide_sigint_action(cli_alive=False, cli_stopped_at=None, now=1000.0, confirm_delay=5.0)
        self.assertEqual(action, "shutdown")

    def test_boundary_at_exactly_the_confirm_delay_shuts_down(self):
        action = _decide_sigint_action(cli_alive=False, cli_stopped_at=1000.0, now=1005.0, confirm_delay=5.0)
        self.assertEqual(action, "shutdown")

    def test_respects_a_custom_confirm_delay(self):
        action = _decide_sigint_action(cli_alive=False, cli_stopped_at=1000.0, now=1001.0, confirm_delay=0.5)
        self.assertEqual(action, "shutdown")


if __name__ == "__main__":
    unittest.main()
