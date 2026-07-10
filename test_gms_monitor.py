#!/usr/bin/env python3
"""Non-interactive tests for gms_monitor and run_gms_monitoring.bat."""

import os
import subprocess
import sys
import unittest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


def _import_curses():
    try:
        import curses
    except ImportError:
        raise unittest.SkipTest("curses is not available on this platform")
    return curses


from gms_monitor import (  # noqa: E402
    MonitorState,
    compute_recent_stats,
    draw_ui,
    run_ping,
    safe_addnstr,
    set_language,
    validate_target_host,
)


class _MockScreen:
    """Minimal stdscr stand-in that enforces the lower-right curses rule."""

    def __init__(self, max_y: int, max_x: int):
        self._max_y = max_y
        self._max_x = max_x
        self.writes: list[tuple[int, int, str, int]] = []

    def getmaxyx(self):
        return self._max_y, self._max_x

    def clear(self):
        pass

    def refresh(self):
        pass

    def addnstr(self, y, x, text, n):
        if y == self._max_y - 1 and x + n >= self._max_x:
            raise curses.error("addnstr() returned ERR")
        self.writes.append((y, x, text, n))


def _stress_state() -> MonitorState:
    """State that fills alerts, metrics, and traceroute sections."""
    set_language("en")
    state = MonitorState("www.youtube.com")
    state.show_controls = True
    state.traceroute_running = False
    state.traceroute_summary = (
        "Summary: 12 hops, max delay 45.2 ms, no timeouts"
    )
    state.last_traceroute_ts = 1_700_000_000.0
    state.traceroute_lines = [
        " 1    2 ms    2 ms    2 ms  192.168.0.1",
        " 2   10 ms   11 ms   12 ms  10.0.0.1",
    ]
    state.consecutive_rto = 5
    state.rto_burst_threshold = 3
    state.rto_history = [True] * 20
    for ms in (20.0, 25.0, 30.0, 500.0, 40.0, 35.0, 28.0, 22.0, 18.0, 15.0):
        state.ping_history.append(ms)
    state.bw_rx_mbps_history.extend([0.1, 0.1, 0.1, 50.0])
    state.bw_tx_mbps_history.extend([0.1, 0.1, 0.1, 5.0])
    state.total_sent = 50
    state.total_recv = 45
    state.last_ping_ms = 24.5
    return state


class SafeAddnstrTests(unittest.TestCase):
    def test_bottom_row_avoids_lower_right_corner(self):
        curses = _import_curses()
        screen = _MockScreen(25, 80)
        long_line = "x" * 80
        safe_addnstr(screen, 24, 0, long_line, 25, 80)
        self.assertEqual(len(screen.writes), 1)
        y, x, text, n = screen.writes[0]
        self.assertEqual(y, 24)
        self.assertLess(x + n, 80)

    def test_out_of_bounds_is_ignored(self):
        try:
            _import_curses()
        except unittest.SkipTest:
            self.skipTest("curses is not available on this platform")
        screen = _MockScreen(10, 40)
        safe_addnstr(screen, 10, 0, "overflow", 10, 40)
        self.assertEqual(screen.writes, [])


class DrawUiTests(unittest.TestCase):
    def test_draw_ui_small_and_default_terminals(self):
        try:
            _import_curses()
        except unittest.SkipTest:
            self.skipTest("curses is not available on this platform")
        state = _stress_state()
        for rows, cols in ((24, 80), (30, 100), (45, 120)):
            with self.subTest(rows=rows, cols=cols):
                screen = _MockScreen(rows, cols)
                draw_ui(screen, state)
                self.assertGreater(len(screen.writes), 0)


class PingTests(unittest.TestCase):
    def test_run_ping_localhost(self):
        ok, rtt = run_ping("127.0.0.1", timeout=3.0)
        self.assertTrue(ok)


class BatLauncherTests(unittest.TestCase):
    @unittest.skipIf(
        os.environ.get("GMS_BAT_TEST_CHILD"),
        "avoid recursive bat --test invocation",
    )
    def test_bat_test_mode_exits_zero(self):
        bat = os.path.join(SCRIPT_DIR, "run_gms_monitoring.bat")
        self.assertTrue(os.path.isfile(bat), "run_gms_monitoring.bat is missing")
        proc = subprocess.run(
            ["cmd", "/c", bat, "--test"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            sys.stderr.write(proc.stdout)
            sys.stderr.write(proc.stderr)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)


class StatsTests(unittest.TestCase):
    def test_compute_recent_stats(self):
        hist = [10.0, 20.0, None, 30.0]
        loss, avg, count, lost, _, _, jitter = compute_recent_stats(hist, 4)
        self.assertEqual(count, 4)
        self.assertEqual(lost, 1)
        self.assertAlmostEqual(loss, 25.0)
        self.assertAlmostEqual(avg, 20.0)
        self.assertIsNotNone(jitter)


class HostValidationTests(unittest.TestCase):
    def test_accepts_valid_hosts(self) -> None:
        self.assertEqual(validate_target_host("www.youtube.com"), "www.youtube.com")
        self.assertEqual(validate_target_host("127.0.0.1"), "127.0.0.1")

    def test_rejects_option_like_hosts(self) -> None:
        with self.assertRaises(ValueError):
            validate_target_host("-t")


if __name__ == "__main__":
    unittest.main(verbosity=2)
