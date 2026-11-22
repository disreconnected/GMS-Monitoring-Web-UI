#!/usr/bin/env python3
"""Non-interactive tests for gms_monitor and run_gms_monitoring.bat."""

import os
import subprocess
import sys
import threading
import unittest
from unittest import mock

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


def _import_curses():
    try:
        import curses
    except ImportError:
        raise unittest.SkipTest("curses is not available on this platform")
    return curses


import gms_monitor  # noqa: E402
from gms_monitor import (  # noqa: E402
    MonitorState,
    _ipaddr,
    _windows_ipv4_flag,
    build_traceroute_summary,
    compute_recent_stats,
    draw_ui,
    get_net_io_totals,
    parse_traceroute_hops,
    ping_worker,
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

    def test_hostnames_force_ipv4_but_ipv6_literals_do_not(self):
        self.assertEqual(_windows_ipv4_flag("www.youtube.com"), ["-4"])
        self.assertEqual(_windows_ipv4_flag("10.5.1.1"), ["-4"])
        self.assertEqual(_windows_ipv4_flag("2001:4860::1"), [])

    @unittest.skipUnless(sys.platform == "win32", "ping -S is the Windows form")
    def test_run_ping_sends_from_the_given_source(self):
        done = subprocess.CompletedProcess([], 0, "Reply from 1.2.3.4: time=18ms", "")
        with mock.patch("gms_monitor.subprocess.run", return_value=done) as run:
            self.assertEqual(run_ping("www.youtube.com", source="10.5.2.194"), (True, 18.0))
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[cmd.index("-S") + 1], "10.5.2.194")


class SourceInterfaceTests(unittest.TestCase):
    def _state(self) -> MonitorState:
        set_language("en")
        state = MonitorState("www.youtube.com")
        state.source_interface = "Wi-Fi"
        return state

    def _one_ping(self, state: MonitorState) -> None:
        def stop_after_one(_seconds):
            state.running = False

        with mock.patch("gms_monitor.time.sleep", side_effect=stop_after_one):
            ping_worker(state, 1.0)

    def test_adapter_without_ipv4_is_a_lost_ping_never_another_adapter(self):
        state = self._state()
        with mock.patch("gms_monitor.interface_ipv4", return_value=None), mock.patch(
            "gms_monitor.run_ping"
        ) as ping:
            self._one_ping(state)
        ping.assert_not_called()
        self.assertEqual(list(state.ping_history), [None])
        self.assertIn('"Wi-Fi"', state.source_error)

    def test_pings_use_the_adapter_address_and_clear_the_error(self):
        state = self._state()
        state.source_error = "stale"
        with mock.patch("gms_monitor.interface_ipv4", return_value="10.5.2.194"), mock.patch(
            "gms_monitor.run_ping", return_value=(True, 18.0)
        ) as ping:
            self._one_ping(state)
        ping.assert_called_once_with("www.youtube.com", source="10.5.2.194")
        self.assertIsNone(state.source_error)

    def test_throughput_counts_only_the_named_adapter(self):
        counters = {"Wi-Fi": mock.Mock(bytes_recv=10, bytes_sent=20)}
        with mock.patch("psutil.net_io_counters", return_value=counters):
            self.assertEqual(get_net_io_totals("Wi-Fi"), (10, 20))
            self.assertIsNone(get_net_io_totals("Missing"))

    def test_failed_traceroute_reruns_when_the_adapter_comes_back(self):
        state = self._state()
        state.source_error = "no IPv4"
        state.last_traceroute_error = "no IPv4"
        with mock.patch("gms_monitor.interface_ipv4", return_value="10.5.2.194"), mock.patch(
            "gms_monitor.run_ping", return_value=(True, 18.0)
        ), mock.patch("gms_monitor.threading.Thread") as thread:
            self._one_ping(state)
        self.assertIs(thread.call_args.kwargs["target"], gms_monitor.traceroute_worker)
        thread.return_value.start.assert_called_once()

    def test_source_error_is_shown_as_an_alert(self):
        from gms_web_server import _collect_alerts

        state = self._state()
        state.source_error = 'Adapter "Wi-Fi" has no IPv4 address'
        alerts = _collect_alerts(state, {})
        self.assertIn(state.source_error, [a["msg"] for a in alerts])

    def test_ipaddr_is_network_byte_order_in_memory(self):
        self.assertEqual(_ipaddr("1.2.3.4"), 0x04030201)


@unittest.skipUnless(sys.platform == "win32", "uses the Windows ICMP API structures")
class IcmpTraceTests(unittest.TestCase):
    """icmp_trace_lines against a scripted IcmpSendEcho2Ex."""

    DEST = "142.251.153.4"
    HOP1 = "103.85.150.117"

    def _trace(self, script, cancel=None):
        import ctypes

        real_ctypes, _lib, options_t, reply_t = gms_monitor._icmp_api()
        replies = iter(script)
        lib = self.lib = mock.Mock()
        lib.IcmpCreateFile.return_value = 1234

        def send(handle, event, apc, ctx, src, dst, data, size, opts, buf, buf_size, timeout):
            count, status, addr, rtt, error = next(replies)
            if count:
                reply = reply_t.from_buffer(buf)
                reply.Status, reply.RoundTripTime = status, rtt
                reply.Address = gms_monitor._ipaddr(addr)
            else:
                ctypes.set_last_error(error)
            return count

        lib.IcmpSendEcho2Ex.side_effect = send
        api = (real_ctypes, lib, options_t, reply_t)
        with mock.patch.object(gms_monitor, "_icmp_api", return_value=api), mock.patch(
            "gms_monitor.socket.getaddrinfo", return_value=[(0, 0, 0, "", (self.DEST, 0))]
        ):
            lines = list(
                gms_monitor.icmp_trace_lines("www.youtube.com", "10.5.2.194", cancel or threading.Event())
            )
        return lines, lib

    def _hop(self, addr, status=11013, rtt=3):
        return (1, status, addr, rtt, 0)

    TIMEOUT = (0, 0, "0.0.0.0", 0, 11010)

    def test_trace_stops_at_the_destination_and_parses_like_tracert(self):
        lines, lib = self._trace(
            [self._hop(self.HOP1), self._hop(self.HOP1, rtt=0), self.TIMEOUT]
            + [self.TIMEOUT] * 3
            + [self._hop(self.DEST, status=0, rtt=19)] * 3
        )
        hops = parse_traceroute_hops(lines)
        self.assertEqual([h["hop"] for h in hops], [1, 2, 3])
        self.assertEqual(hops[0]["host"], self.HOP1)
        self.assertEqual(hops[0]["ms"], [3.0, 1.0])
        self.assertTrue(hops[1]["timeout"])
        self.assertEqual(hops[2]["host"], self.DEST)
        self.assertEqual(lines[-1], "Trace complete.")
        self.assertIn("3 hops", build_traceroute_summary(lines))
        lib.IcmpCloseHandle.assert_called_once_with(1234)

    def test_a_failed_send_is_an_error_not_a_lost_probe(self):
        # 1214: the source address is gone (adapter disconnected or renumbered).
        with self.assertRaises(OSError):
            self._trace([self._hop(self.HOP1), (0, 0, "0.0.0.0", 0, 1214)])
        self.lib.IcmpCloseHandle.assert_called_once_with(1234)

    def test_unreachable_reply_ends_the_trace_at_that_hop(self):
        lines, _lib = self._trace([(1, 11003, self.HOP1, 5, 0)] * 3)
        hops = parse_traceroute_hops(lines)
        self.assertEqual(len(hops), 1)
        self.assertIn("unreachable", hops[0]["host"])

    def test_cancel_stops_between_probes_and_closes_the_handle(self):
        cancel = threading.Event()
        cancel.set()
        lines, lib = self._trace([], cancel)
        self.assertEqual(parse_traceroute_hops(lines), [])
        lib.IcmpSendEcho2Ex.assert_not_called()
        lib.IcmpCloseHandle.assert_called_once_with(1234)


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
