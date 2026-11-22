#!/usr/bin/env python3
"""Unit tests for Stormshield MONITOR parsing and poller snapshot state."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
from collections import deque
from unittest import mock

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from gms_stormshield import (  # noqa: E402
    AUTH_BLOCKED_ERROR,
    AUTH_FAILED_ERROR,
    AUTH_RETRY_SECONDS,
    HOST_IFACE_BACKOFF_MAX_SECONDS,
    HOST_IFACE_BACKOFF_SECONDS,
    LOGIN_STALL_BACKOFF_MAX_SECONDS,
    LOGIN_STALL_BACKOFF_SECONDS,
    STOP_JOIN_SECONDS,
    TOTP_NEEDED_ERROR,
    AuthenticationError,
    CommandTimeout,
    LoginBlocked,
    LoginTimeout,
    StormshieldConfig,
    StormshieldPoller,
    TOTPNeededError,
    _parse_kv_line,
    _sanitize_error,
    apply_host_rate_deltas,
    bits_to_mbps,
    compute_rate_bps,
    parse_monitor_host,
    parse_monitor_interface,
    rank_top_hosts,
)

try:
    from stormshield.sns.sslclient import Response
except ImportError:  # the optional SNS client package is not installed
    Response = None

needs_sns_client = unittest.skipUnless(
    Response is not None, "stormshield.sns.sslclient is not installed"
)

INTERFACE_FIXTURE = """
101 code=00a01000 msg="Begin" format="section_line"
[Result]
name=sslvpn_udp,sslvpn1 addr=172.16.2.1/255.255.255.255 type=sslvpn color=000000 throughput=0,0,0,0 throughput_out=0,0,0,0 packet=0,0,0,0,0,0 byte=0,0,0,0 byte_out=0,0,0,0 tcpconn=0 udpconn=0 tcpconncount=0 udpconncount=0 state=1 plugged=0 protected=1
name=CoreSwitch,Ethernet3 addr=10.5.1.1/255.255.255.240 type=Ethernet color=000000 throughput=1000000000,12783536,88095080,0 throughput_out=1000000000,25213328,174171544,0 packet=2568205,50239,0,2487553,79734,918 byte=645932471,636862687,9010569,59215 byte_out=2390801768,2331192391,44716197,382164 tcpconn=29475 udpconn=21630 tcpconncount=4789 udpconncount=2682 state=1 plugged=1 protected=1 fullduplex=1
name=Fibernet,Ethernet2 addr=203.0.113.38/255.255.255.252 type=Ethernet color=FF8040 throughput=100000000,4800,448496,0 throughput_out=100000000,3096,644488,0 packet=5157,441,0,4891,98,168 byte=672017,654146,11411,6460 byte_out=965333,952831,6570,5168 tcpconn=0 udpconn=1 tcpconncount=0 udpconncount=1 state=1 plugged=1 protected=0 fullduplex=1
name=dmz6,Ethernet7 type=Ethernet color=000000 throughput=0,0,0,0 throughput_out=0,0,0,0 packet=0,0,0,0,0,0 byte=0,0,0,0 byte_out=0,0,0,0 tcpconn=0 udpconn=0 tcpconncount=0 udpconncount=0 state=0 plugged=0 protected=0
name=iForte,Ethernet1 addr=203.0.113.118/255.255.255.252 type=Ethernet color=408080 throughput=1000000000,25054432,82056712,0 throughput_out=1000000000,13740344,90731880,0 packet=2312973,94277,0,2282798,29996,179 byte=2383241681,2365969482,17264831,7368 byte_out=726656383,630163245,5560647,61040 tcpconn=0 udpconn=0 tcpconncount=0 udpconncount=0 state=1 plugged=1 protected=0 fullduplex=1
name=CBN,Ethernet0 addr=203.0.113.26/255.255.255.252 type=Ethernet color=800040 throughput=1000000000,249000,80086560,0 throughput_out=1000000000,17179000,26854560,0 packet=567757,243,0,534204,27486,6067 byte=67372574,39223144,27740297,409133 byte_out=1634000088,1630498436,3465116,34688 tcpconn=0 udpconn=0 tcpconncount=0 udpconncount=0 state=1 plugged=1 protected=0 fullduplex=1
name=BackupLine,Ethernet5 addr=10.5.1.1/255.255.255.240 type=Ethernet color=000000 throughput=0,0,0,0 throughput_out=0,0,0,0 packet=0,0,0,0,0,0 byte=0,0,0,0 byte_out=0,0,0,0 tcpconn=0 udpconn=0 tcpconncount=0 udpconncount=0 state=1 plugged=0 protected=1
name=BWP,Ethernet4 addr=10.5.1.1/255.255.255.240 type=Ethernet color=000000 throughput=1000000000,17110728,34238040,0 throughput_out=1000000000,220368,248744,0 packet=1203032,0,0,1203014,18,0 byte=1626235999,1626234763,1236,0 byte_out=20485254,20483634,1620,0 tcpconn=0 udpconn=18 tcpconncount=1 udpconncount=0 state=1 plugged=1 protected=1 fullduplex=1
name=ipsec,ipsec type=ipsec color=000000 throughput=0,0,0,0 throughput_out=0,0,0,0 packet=0,0,0,0,0,0 byte=0,0,0,0 byte_out=0,0,0,0 tcpconn=0 udpconn=0 tcpconncount=0 udpconncount=0 state=1 plugged=0 protected=0
100 code=00a00100 msg="Ok"
"""

HOST_FIXTURE = """
101 code=00a01000 msg="Begin" format="section_line"
[Result]
addr=10.5.3.188 mac_addr=02:00:00:00:6e:00 name=10.5.3.188 interface=CoreSwitch protected=1 packet=1536 byte=1311071 byte_out=347910 throughput=3152,4181768 throughput_out=704,621168 hostrep=0
addr=10.5.2.187 mac_addr=02:00:00:00:6e:00 name=10.5.2.187 interface=CoreSwitch protected=1 packet=1835 byte=2314727 byte_out=132195 throughput=0,3077624 throughput_out=72,197424 hostrep=0
addr=10.5.1.7 mac_addr=02:00:00:00:ed:d3 name=BWP interface=BWP protected=1 packet=257441 byte=10465721 byte_out=831960113 throughput=52520,235368 throughput_out=17432296,18353448 hostrep=0
addr=10.5.3.40 mac_addr=02:00:00:00:3c:40 name=nas-store interface=CoreSwitch protected=1 packet=98211 byte=402331870 byte_out=1650044 throughput=9421800,31220000 throughput_out=210400,8800000 hostrep=0
addr=10.5.3.91 mac_addr=02:00:00:00:51:91 name=10.5.3.91 interface=CoreSwitch protected=1 packet=12 byte=1480 byte_out=960 throughput=0,0 throughput_out=0,0 hostrep=0
addr=10.5.1.22 mac_addr=02:00:00:00:b1:22 name=printer-hall interface=BWP protected=1 packet=904 byte=120330 byte_out=88210 throughput=1250000,2400000 throughput_out=96000,410000 hostrep=0
100 code=00a00100 msg="Ok"
"""


def _host_output(iface: str) -> str:
    """HOST_FIXTURE limited to one interface, like ``MONITOR HOST iface=<name>``."""
    return "\n".join(
        line
        for line in HOST_FIXTURE.splitlines()
        if "addr=" not in line or f"interface={iface} " in line
    )


def _make_fake_send(calls: list[str], failing: tuple[str, ...] = ()):
    """Fake ``_send_command`` that records commands and refuses unfiltered host queries."""

    def fake_send(command: str) -> str:
        calls.append(command)
        if command == "MONITOR INTERFACE":
            return INTERFACE_FIXTURE
        prefix = "MONITOR HOST iface="
        if command.startswith(prefix):
            iface = command[len(prefix):]
            if iface in failing:
                raise RuntimeError(f"{command} failed: Command processing failed")
            return _host_output(iface)
        raise AssertionError(f"unexpected command: {command}")

    return fake_send


def _install_fake_send(
    poller: StormshieldPoller, calls: list[str], failing: tuple[str, ...] = ()
) -> None:
    """Route both API sessions (interface and host) to one recording fake."""
    fake = _make_fake_send(calls, failing)
    poller._send_command = fake  # type: ignore[method-assign]
    poller._send_host_command = fake  # type: ignore[method-assign]


def _blocking_client(release: threading.Event) -> mock.Mock:
    """Fake SSLClient whose send_command hangs until ``release`` is set."""
    client = mock.Mock()
    client.send_command.side_effect = lambda command: release.wait()
    return client


def _wait_until(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


class _RecordingEvent(threading.Event):
    """Real Event that records every wait() timeout."""

    def __init__(self) -> None:
        super().__init__()
        self.timeouts: list[float | None] = []

    def wait(self, timeout: float | None = None) -> bool:
        self.timeouts.append(timeout)
        return super().wait(timeout)


class _FakeClock:
    """Stand-in for time.monotonic that only moves when a test advances it."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _ScriptedStopEvent:
    """Event stand-in that never blocks and stops the poller after ``max_waits`` waits."""

    def __init__(self, poller: StormshieldPoller, max_waits: int) -> None:
        self.poller = poller
        self.max_waits = max_waits
        self.timeouts: list[float | None] = []

    def set(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> bool:
        self.timeouts.append(timeout)
        if len(self.timeouts) >= self.max_waits:
            self.poller._running = False
        return False


class ThroughputParsingTests(unittest.TestCase):
    def test_bits_to_mbps(self) -> None:
        self.assertAlmostEqual(bits_to_mbps(25_000_000), 25.0)
        self.assertAlmostEqual(bits_to_mbps(1_000_000), 1.0)

    def test_compute_rate_bps(self) -> None:
        # 1_250_000 bytes over 1s = 10_000_000 bits/s
        self.assertAlmostEqual(compute_rate_bps(0, 1_250_000, 1.0), 10_000_000.0)
        self.assertIsNone(compute_rate_bps(None, 100, 1.0))
        self.assertIsNone(compute_rate_bps(200, 100, 1.0))  # counter reset
        self.assertIsNone(compute_rate_bps(0, 100, 0.0))


class InterfaceParseTests(unittest.TestCase):
    def test_parses_interfaces(self) -> None:
        ifaces = parse_monitor_interface(INTERFACE_FIXTURE)
        self.assertEqual(len(ifaces), 9)

        core = next(i for i in ifaces if i["name"] == "CoreSwitch")
        self.assertEqual(core["real_name"], "Ethernet3")
        self.assertEqual(core["type"], "Ethernet")
        self.assertEqual(core["addr"], "10.5.1.1/255.255.255.240")
        self.assertEqual(core["state"], 1)
        self.assertEqual(core["plugged"], 1)
        self.assertEqual(core["protected"], 1)
        self.assertEqual(core["link_mbps"], 1000.0)
        self.assertEqual(core["rx_bps"], 12_783_536)
        self.assertAlmostEqual(core["rx_mbps"], 12.783536, places=3)
        self.assertAlmostEqual(core["tx_mbps"], 25.213328, places=3)
        self.assertEqual(core["tcp_conn"], 4789)
        self.assertEqual(core["udp_conn"], 2682)
        self.assertEqual(core["bytes_in"], 645_932_471)
        self.assertEqual(core["bytes_out"], 2_390_801_768)

    def test_interface_link_and_cabling_flags(self) -> None:
        by_name = {i["name"]: i for i in parse_monitor_interface(INTERFACE_FIXTURE)}

        wan = by_name["Fibernet"]
        self.assertEqual((wan["plugged"], wan["protected"]), (1, 0))
        self.assertEqual(wan["link_mbps"], 100.0)

        cbn = by_name["CBN"]
        self.assertAlmostEqual(cbn["rx_mbps"], 0.249)
        self.assertEqual(cbn["link_mbps"], 1000.0)

        unplugged_lan = by_name["BackupLine"]
        self.assertEqual((unplugged_lan["plugged"], unplugged_lan["protected"]), (0, 1))
        self.assertEqual(unplugged_lan["link_mbps"], 0.0)

        down = by_name["dmz6"]
        self.assertEqual(down["state"], 0)
        self.assertEqual(down["addr"], "")
        self.assertEqual(down["rx_mbps"], 0.0)

        self.assertEqual(by_name["ipsec"]["link_mbps"], 0.0)

    def test_parse_kv_line_handles_quoted_values(self) -> None:
        self.assertEqual(
            _parse_kv_line('addr=10.0.0.9 name="My PC" interface=LAN'),
            {"addr": "10.0.0.9", "name": "My PC", "interface": "LAN"},
        )
        # Unbalanced quote falls back to whitespace splitting instead of raising.
        self.assertEqual(_parse_kv_line('name="My x=1'), {"name": '"My', "x": "1"})

    def test_interface_flags_default_when_absent(self) -> None:
        ifaces = parse_monitor_interface("name=x,eth0 state=1 throughput=5")
        self.assertEqual(len(ifaces), 1)
        self.assertEqual(ifaces[0]["plugged"], 0)
        self.assertEqual(ifaces[0]["protected"], 0)
        self.assertEqual(ifaces[0]["link_mbps"], 0.0)


class HostParseTests(unittest.TestCase):
    def test_parses_hosts(self) -> None:
        hosts = parse_monitor_host(HOST_FIXTURE)
        self.assertEqual(len(hosts), 6)
        first = hosts[0]
        self.assertEqual(first["addr"], "10.5.3.188")
        self.assertEqual(first["mac"], "02:00:00:00:6e:00")
        self.assertEqual(first["name"], "10.5.3.188")
        self.assertEqual(first["interface"], "CoreSwitch")
        self.assertEqual(first["protected"], 1)
        self.assertEqual(first["packets"], 1536)
        self.assertEqual(first["bytes_in"], 1_311_071)
        self.assertEqual(first["bytes_out"], 347_910)
        self.assertEqual(first["rx_bps"], 3152)
        self.assertEqual(first["tx_bps"], 704)
        self.assertEqual(first["reputation"], 0)
        self.assertEqual(first["geo"], "")
        self.assertEqual(first["state"], "")

        bwp = hosts[2]
        self.assertEqual(bwp["name"], "BWP")
        self.assertEqual(bwp["interface"], "BWP")
        self.assertEqual(bwp["bytes_out"], 831_960_113)
        self.assertAlmostEqual(bwp["tx_mbps"], 17.432, places=3)

    def test_host_bytes_out_fallback_and_optional_fields(self) -> None:
        legacy = parse_monitor_host(
            "addr=203.0.113.9 name=ext interface=iForte packet=1 byte=10 byte_count=7 "
            "throughput=0,0 hostrep=5 geo=US state=host"
        )[0]
        self.assertEqual(legacy["bytes_out"], 7)
        self.assertEqual(legacy["mac"], "")
        self.assertEqual(legacy["protected"], 0)
        self.assertEqual(legacy["geo"], "US")
        self.assertEqual(legacy["state"], "host")
        self.assertEqual(legacy["reputation"], 5)

        both = parse_monitor_host("addr=10.0.0.1 byte=10 byte_out=20 byte_count=30")[0]
        self.assertEqual(both["bytes_out"], 20)

    def test_rank_top_hosts(self) -> None:
        hosts = parse_monitor_host(HOST_FIXTURE)
        ranked = rank_top_hosts(hosts, limit=2)
        self.assertEqual(len(ranked), 2)
        # Ranked by rx + tx: 10.5.1.7 uploads 17.4 Mbps, 10.5.3.40 moves 9.6 Mbps in total.
        self.assertEqual(ranked[0]["addr"], "10.5.1.7")
        self.assertEqual(ranked[1]["addr"], "10.5.3.40")

        tie = rank_top_hosts(
            [
                {"addr": "a", "rx_mbps": 1.0, "tx_mbps": 1.0, "bytes_in": 1, "bytes_out": 1},
                {"addr": "b", "rx_mbps": 0.5, "tx_mbps": 1.5, "bytes_in": 5, "bytes_out": 5},
            ]
        )
        self.assertEqual([h["addr"] for h in tie], ["b", "a"])

    def test_rate_from_byte_deltas(self) -> None:
        hosts = parse_monitor_host(HOST_FIXTURE)
        phone = next(h for h in hosts if h["addr"] == "10.5.2.187")
        self.assertEqual(phone["rx_mbps"], 0.0)

        t0 = 1_000.0
        previous = {
            "10.5.2.187": (50_000, 25_000, t0),
        }
        # +125_000 bytes in over 1s → 1 Mbps
        phone["bytes_in"] = 175_000
        phone["bytes_out"] = 50_000
        apply_host_rate_deltas([phone], previous, t0 + 1.0)
        self.assertAlmostEqual(phone["rx_mbps"], 1.0)
        self.assertAlmostEqual(phone["tx_mbps"], 0.2)


class PollerSnapshotTests(unittest.TestCase):
    def test_snapshot_without_live_client(self) -> None:
        poller = StormshieldPoller(
            StormshieldConfig(
                host="192.168.1.1",
                user="admin",
                password="secret-password",
                interval=5.0,
            )
        )
        now = time.time()
        with poller.lock:
            poller.connected = True
            poller.model = "SN510"
            poller.version = "4.8.13"
            poller.last_poll_at = now
            poller.interfaces = [
                i for i in parse_monitor_interface(INTERFACE_FIXTURE) if i["name"] == "CoreSwitch"
            ]
            poller.hosts = rank_top_hosts(parse_monitor_host(HOST_FIXTURE), limit=3)
            poller.host_interfaces = ["CoreSwitch", "BWP"]
            name = poller.interfaces[0]["name"]
            from gms_stormshield import _InterfaceHistory

            hist = _InterfaceHistory(deque(maxlen=poller.config.history_points))
            hist.history.append({"t": now, "rx_mbps": 12.784, "tx_mbps": 25.213})
            poller._iface_histories[name] = hist

        snap = poller.snapshot()
        self.assertTrue(snap["connected"])
        self.assertIsNone(snap["error"])
        self.assertEqual(snap["model"], "SN510")
        self.assertEqual(snap["version"], "4.8.13")
        self.assertEqual(len(snap["interfaces"]), 1)
        self.assertEqual(snap["interfaces"][0]["name"], "CoreSwitch")
        self.assertEqual(snap["interfaces"][0]["plugged"], 1)
        self.assertEqual(snap["interfaces"][0]["protected"], 1)
        self.assertEqual(snap["interfaces"][0]["link_mbps"], 1000.0)
        self.assertEqual(len(snap["interfaces"][0]["history"]), 1)
        self.assertEqual(len(snap["hosts"]), 3)
        self.assertEqual(snap["hosts"][0]["addr"], "10.5.1.7")
        self.assertEqual(snap["hosts"][0]["mac"], "02:00:00:00:ed:d3")
        self.assertEqual(snap["host_interfaces"], ["CoreSwitch", "BWP"])

    def test_error_state_in_snapshot(self) -> None:
        poller = StormshieldPoller(
            StormshieldConfig(host="fw", user="admin", password="x" * 16)
        )
        with poller.lock:
            poller.connected = False
            poller.last_error = "connection refused"
        snap = poller.snapshot()
        self.assertFalse(snap["connected"])
        self.assertEqual(snap["error"], "connection refused")
        self.assertEqual(snap["interfaces"], [])
        self.assertEqual(snap["hosts"], [])
        self.assertEqual(snap["host_interfaces"], [])
        self.assertIsNone(snap["hosts_error"])
        self.assertIsNone(snap["hosts_updated_at"])
        self.assertEqual(snap["hosts_slow"], [])
        self.assertEqual(snap["command_deadline"], 30.0)
        self.assertEqual(snap["host_command_deadline"], 60.0)
        json.dumps(snap)

    def test_poll_once_with_mock_client(self) -> None:
        poller = StormshieldPoller(
            StormshieldConfig(host="fw", user="admin", password="x" * 16)
        )

        calls: list[str] = []
        _install_fake_send(poller, calls)
        poller._poll_once()
        self.assertEqual(poller.snapshot()["hosts"], [])  # hosts have their own loop
        self.assertTrue(poller._poll_hosts_once())

        snap = poller.snapshot()
        self.assertEqual(len(snap["interfaces"]), 9)
        self.assertEqual(len(snap["hosts"]), 6)
        self.assertIsNotNone(snap["last_poll"])
        self.assertIsNotNone(snap["hosts_updated_at"])
        self.assertIsNone(snap["hosts_error"])
        json.dumps(snap)

    def test_poll_once_queries_only_plugged_lan_interfaces(self) -> None:
        poller = StormshieldPoller(
            StormshieldConfig(host="fw", user="admin", password="x" * 16)
        )
        calls: list[str] = []
        _install_fake_send(poller, calls)
        self.assertFalse(poller._poll_hosts_once())  # no interface list yet: no query
        self.assertEqual(calls, [])
        poller._poll_once()
        poller._poll_hosts_once()

        # Never an unfiltered MONITOR HOST, never a WAN / unplugged / VPN interface.
        self.assertEqual(
            calls,
            [
                "MONITOR INTERFACE",
                "MONITOR HOST iface=CoreSwitch",
                "MONITOR HOST iface=BWP",
            ],
        )
        snap = poller.snapshot()
        self.assertEqual(snap["host_interfaces"], ["CoreSwitch", "BWP"])
        self.assertEqual(
            {h["interface"] for h in snap["hosts"]}, {"CoreSwitch", "BWP"}
        )
        self.assertEqual(snap["hosts"][0]["addr"], "10.5.1.7")

    def test_failed_host_query_does_not_abort_poll(self) -> None:
        poller = StormshieldPoller(
            StormshieldConfig(host="fw", user="admin", password="x" * 16)
        )
        calls: list[str] = []
        _install_fake_send(poller, calls, failing=("CoreSwitch",))
        with self.assertLogs("gms_stormshield", level="WARNING") as logs:
            poller._poll_once()
            poller._poll_hosts_once()

        self.assertTrue(any("iface=CoreSwitch" in line for line in logs.output))
        self.assertEqual(
            calls,
            [
                "MONITOR INTERFACE",
                "MONITOR HOST iface=CoreSwitch",
                "MONITOR HOST iface=BWP",
            ],
        )
        snap = poller.snapshot()
        self.assertEqual(len(snap["interfaces"]), 9)
        self.assertIsNotNone(snap["last_poll"])
        self.assertEqual({h["interface"] for h in snap["hosts"]}, {"BWP"})
        self.assertEqual(snap["host_interfaces"], ["BWP"])

    def test_host_interfaces_config_overrides_automatic_set(self) -> None:
        poller = StormshieldPoller(
            StormshieldConfig(
                host="fw",
                user="admin",
                password="x" * 16,
                host_interfaces=["BWP", "iForte", "NoSuchIface"],
            )
        )
        calls: list[str] = []
        _install_fake_send(poller, calls)
        with self.assertLogs("gms_stormshield", level="WARNING") as logs:
            poller._poll_once()
            poller._poll_hosts_once()

        # iForte is a WAN interface (protected=0): skipped with one warning.
        # Names the firewall does not list are skipped silently.
        self.assertEqual(
            calls,
            [
                "MONITOR INTERFACE",
                "MONITOR HOST iface=BWP",
            ],
        )
        self.assertEqual(len(logs.records), 1)
        self.assertIn("iForte", logs.output[0])
        snap = poller.snapshot()
        self.assertEqual(snap["host_interfaces"], ["BWP"])
        self.assertEqual({h["interface"] for h in snap["hosts"]}, {"BWP"})

        with self.assertNoLogs("gms_stormshield", level="WARNING"):
            poller._poll_once()
            poller._poll_hosts_once()  # the warning is only emitted once per name

    def test_history_capped_to_one_hour_of_polls(self) -> None:
        poller = StormshieldPoller(
            StormshieldConfig(host="fw", user="admin", password="x" * 16, interval=5.0)
        )
        self.assertEqual(poller.config.history_points, 720)

        poller._send_command = _make_fake_send([])  # type: ignore[method-assign]
        for _ in range(800):
            poller._poll_once()

        snap = poller.snapshot()
        self.assertTrue(snap["interfaces"])
        for iface in snap["interfaces"]:
            self.assertEqual(len(iface["history"]), 720 if iface["plugged"] == 1 else 0)

        fast = StormshieldConfig(host="fw", user="admin", password="x" * 16, interval=1.0)
        self.assertEqual(fast.history_points, 3600)

    def test_snapshot_history_only_for_plugged_interfaces(self) -> None:
        poller = StormshieldPoller(
            StormshieldConfig(host="fw", user="admin", password="x" * 16)
        )
        poller._send_command = _make_fake_send([])  # type: ignore[method-assign]
        poller._poll_once()

        by_name = {i["name"]: i for i in poller.snapshot()["interfaces"]}
        core_history = by_name["CoreSwitch"]["history"]
        self.assertEqual(len(core_history), 1)
        self.assertIsInstance(core_history[0]["t"], int)
        for name in ("BackupLine", "dmz6", "ipsec", "sslvpn_udp"):
            self.assertEqual(by_name[name]["history"], [])

    def test_config_repr_hides_password(self) -> None:
        config = StormshieldConfig(host="fw", user="admin", password="secret-password")
        self.assertNotIn("secret-password", repr(config))

    def test_config_timeout_default_and_passed_to_client(self) -> None:
        config = StormshieldConfig(host="fw", user="admin", password="x" * 16)
        self.assertEqual(config.timeout, 10.0)

        poller = StormshieldPoller(config)
        with mock.patch("stormshield.sns.sslclient.SSLClient") as client_cls:
            poller._ensure_client()
        self.assertEqual(client_cls.call_args.kwargs["timeout"], 10.0)

    def test_build_snapshot_includes_stormshield(self) -> None:
        from gms_monitor import MonitorState
        from gms_web_server import build_snapshot

        poller = StormshieldPoller(
            StormshieldConfig(host="fw", user="admin", password="x" * 16)
        )
        with poller.lock:
            poller.connected = True
            poller.hosts = [{"addr": "1.2.3.4", "name": "h", "rx_mbps": 1.0, "tx_mbps": 0.1,
                             "bytes_in": 10, "bytes_out": 5, "packets": 1, "interface": "in",
                             "reputation": 0, "geo": ""}]

        state = MonitorState("www.example.com")
        snap = build_snapshot(state, stormshield=poller)
        self.assertIn("stormshield", snap)
        self.assertTrue(snap["stormshield"]["connected"])
        self.assertEqual(snap["stormshield"]["hosts"][0]["addr"], "1.2.3.4")

        snap_plain = build_snapshot(state)
        self.assertNotIn("stormshield", snap_plain)

    def test_shutdown_endpoint_stops_poller_and_waits(self) -> None:
        from fastapi.testclient import TestClient

        from gms_web_server import MonitorService, ServerSecurity, create_app

        poller = StormshieldPoller(
            StormshieldConfig(host="fw", user="admin", password="x" * 16)
        )
        security = ServerSecurity("127.0.0.1", 9847)
        app = create_app(MonitorService("127.0.0.1"), security, poller)
        with mock.patch.object(
            security, "verify_loopback_peer", return_value=True
        ), mock.patch.object(poller, "stop") as stop:
            with TestClient(app) as client:
                response = client.post(
                    "/api/shutdown", headers={"X-GMS-Token": security.token}
                )
        self.assertEqual(response.status_code, 200)
        stop.assert_called_once_with(True)


class SanitizeErrorTests(unittest.TestCase):
    def test_strips_session_id_and_truncates(self) -> None:
        exc = RuntimeError("GET /api/command?sessionid=abc123XYZ&cmd=MONITOR%20INTERFACE failed")
        text = _sanitize_error(exc)
        self.assertNotIn("abc123XYZ", text)
        self.assertIn("sessionid=***&cmd=", text)
        self.assertEqual(len(_sanitize_error(RuntimeError("x" * 500))), 200)

    @needs_sns_client
    def test_requests_errors_get_short_text(self) -> None:
        from requests import exceptions as rx

        msg = "Max retries exceeded with url: /api/command?sessionid=abc123"
        self.assertEqual(_sanitize_error(rx.ConnectTimeout(msg)), "connection timed out")
        self.assertEqual(_sanitize_error(rx.ReadTimeout(msg)), "connection timed out")
        self.assertEqual(
            _sanitize_error(rx.ConnectionError(msg)), "connection refused/unreachable"
        )
        self.assertNotIn("abc123", _sanitize_error(rx.SSLError(msg)))


class PollerRunLoopTests(unittest.TestCase):
    def _poller(self) -> StormshieldPoller:
        return StormshieldPoller(
            StormshieldConfig(host="fw", user="admin", password="x" * 16)
        )

    def test_auth_failure_stops_retrying_until_stopped(self) -> None:
        poller = self._poller()
        stop_event = _RecordingEvent()
        poller._stop_event = stop_event  # type: ignore[assignment]
        with mock.patch.object(
            poller, "_ensure_client", side_effect=AuthenticationError("Authentication failed")
        ) as ensure, mock.patch.object(poller, "_poll_once") as poll, mock.patch.object(
            poller, "_run_hosts"  # this test is about the interface loop's waits only
        ), self.assertLogs(
            "gms_stormshield", level="WARNING"
        ) as logs:
            poller.start()
            try:
                deadline = time.time() + 5
                while not stop_event.timeouts and time.time() < deadline:
                    time.sleep(0.01)
                snap = poller.snapshot()
            finally:
                poller.stop(wait=True)

        self.assertFalse(poller._thread.is_alive())
        self.assertEqual(ensure.call_count, 1)  # no reconnect attempt while waiting
        poll.assert_not_called()
        self.assertEqual(stop_event.timeouts, [AUTH_RETRY_SECONDS])
        self.assertFalse(snap["connected"])
        self.assertEqual(snap["error"], AUTH_FAILED_ERROR)
        self.assertEqual(len(logs.records), 1)

    def test_auth_failure_texts_and_waits(self) -> None:
        cases = [
            (TOTPNeededError("TOTP is needed"), TOTP_NEEDED_ERROR, AUTH_RETRY_SECONDS),
            (
                AuthenticationError("Brut force detected, try again after 300 seconds."),
                AUTH_BLOCKED_ERROR,
                300.0,
            ),
            (
                AuthenticationError("Brut force detected, try again after 5 seconds."),
                AUTH_BLOCKED_ERROR,
                60.0,
            ),
        ]
        for exc, error, wait in cases:
            with self.subTest(error=error, wait=wait):
                poller = self._poller()
                event = _ScriptedStopEvent(poller, max_waits=1)
                poller._stop_event = event  # type: ignore[assignment]
                with mock.patch.object(
                    poller, "_ensure_client", side_effect=exc
                ), self.assertLogs("gms_stormshield", level="WARNING"):
                    poller._run()
                self.assertEqual(event.timeouts, [wait])
                snap = poller.snapshot()
                self.assertFalse(snap["connected"])
                self.assertEqual(snap["error"], error)

    def test_other_failures_back_off_and_reset_after_success(self) -> None:
        poller = self._poller()
        event = _ScriptedStopEvent(poller, max_waits=7)
        poller._stop_event = event  # type: ignore[assignment]
        outcomes = iter([RuntimeError("down")] * 5 + [None, RuntimeError("down")])

        def ensure() -> None:
            outcome = next(outcomes)
            if outcome is not None:
                raise outcome

        with mock.patch.object(poller, "_ensure_client", side_effect=ensure), mock.patch.object(
            poller, "_poll_once"
        ), self.assertLogs("gms_stormshield", level="WARNING"):
            poller._run()
        self.assertEqual(event.timeouts, [15.0, 30.0, 60.0, 120.0, 120.0, 5.0, 15.0])

    def test_poll_failure_error_is_sanitized(self) -> None:
        poller = self._poller()
        poller._stop_event = _ScriptedStopEvent(poller, max_waits=1)  # type: ignore[assignment]
        exc = RuntimeError("GET /api/command?sessionid=SECRET123&cmd=x failed")
        with mock.patch.object(
            poller, "_ensure_client", side_effect=exc
        ), self.assertLogs("gms_stormshield", level="WARNING") as logs:
            poller._run()
        self.assertNotIn("SECRET123", poller.snapshot()["error"])
        self.assertNotIn("SECRET123", "\n".join(logs.output))

    def test_run_logs_out_when_stopped(self) -> None:
        poller = self._poller()
        polled = threading.Event()
        with mock.patch.object(poller, "_ensure_client"), mock.patch.object(
            poller, "_poll_once", side_effect=polled.set
        ), mock.patch.object(poller, "_disconnect") as disconnect:
            poller.start()
            try:
                self.assertTrue(polled.wait(5))
                disconnect.assert_not_called()
            finally:
                poller.stop(wait=True)

        self.assertFalse(poller._thread.is_alive())
        disconnect.assert_called_once_with()

    @needs_sns_client
    def test_ensure_client_disconnects_when_stopped_during_login(self) -> None:
        poller = self._poller()
        client = mock.Mock()

        def login(**_kwargs):
            poller.stop()  # stop() arrives while the login is in flight
            return client

        with mock.patch(
            "stormshield.sns.sslclient.SSLClient", side_effect=login
        ), mock.patch.object(poller, "_fetch_system_property") as fetch:
            poller._ensure_client()
        client.disconnect.assert_called_once_with()
        fetch.assert_not_called()
        self.assertIsNone(poller._client)


class DeadlineAndSessionSplitTests(unittest.TestCase):
    def _poller(self, **kwargs) -> StormshieldPoller:
        return StormshieldPoller(
            StormshieldConfig(host="fw", user="admin", password="x" * 16, **kwargs)
        )

    def _fake_host_login(self, poller: StormshieldPoller, client: mock.Mock):
        def ensure_host() -> None:
            if poller._host_session.client is None:
                poller._host_session.client = client

        return ensure_host

    def test_send_command_deadline_abandons_session_and_reaps_it(self) -> None:
        poller = self._poller(command_deadline=0.3)
        release = threading.Event()
        stuck = _blocking_client(release)
        poller._client = stuck
        try:
            started = time.monotonic()
            with self.assertRaises(CommandTimeout) as ctx:
                poller._send_command("MONITOR HOST iface=CoreSwitch")
            elapsed = time.monotonic() - started
            self.assertGreaterEqual(elapsed, 0.25)
            self.assertLess(elapsed, 1.3)
            self.assertEqual(
                str(ctx.exception),
                "MONITOR HOST iface=CoreSwitch exceeded 0.3s (firewall busy)",
            )
            self.assertIsNone(poller._client)
            stuck.disconnect.assert_not_called()

            # The next connection gets a fresh worker, not one queued behind the stuck call.
            healthy = mock.Mock()
            healthy.send_command.return_value = mock.Mock(output="ok")
            poller._client = healthy
            self.assertEqual(poller._send_command("MONITOR INTERFACE"), "ok")
        finally:
            release.set()
        self.assertTrue(_wait_until(lambda: stuck.disconnect.called, 2))
        stuck.disconnect.assert_called_once_with()

    def test_stuck_host_query_keeps_interface_loop_polling(self) -> None:
        poller = self._poller(interval=0.2, host_command_deadline=0.5)
        previous = rank_top_hosts(parse_monitor_host(HOST_FIXTURE), limit=2)
        poller.hosts = list(previous)
        poller._send_command = _make_fake_send([])  # type: ignore[method-assign]
        release = threading.Event()
        stuck = _blocking_client(release)

        def history_len() -> int:
            with poller.lock:
                hist = poller._iface_histories.get("CoreSwitch")
                return len(hist.history) if hist else 0

        with mock.patch.object(poller, "_ensure_client"), mock.patch.object(
            poller, "_ensure_host_client", side_effect=self._fake_host_login(poller, stuck)
        ), mock.patch("gms_stormshield.HOST_IFACE_WAIT_SECONDS", 0.05), self.assertLogs(
            "gms_stormshield", level="WARNING"
        ):
            poller.start()
            try:
                self.assertTrue(
                    _wait_until(lambda: poller.snapshot()["hosts_error"] is not None, 5)
                )
                before = history_len()
                self.assertTrue(_wait_until(lambda: history_len() > before, 5))
                snap = poller.snapshot()
            finally:
                poller.stop(wait=True)
                release.set()

        # Every interface timed out: nothing to publish, the previous list is kept.
        self.assertEqual(snap["hosts_error"], "CoreSwitch, BWP: exceeded 0.5s (firewall busy)")
        self.assertEqual([s["name"] for s in snap["hosts_slow"]], ["CoreSwitch", "BWP"])
        self.assertEqual([h["addr"] for h in snap["hosts"]], [h["addr"] for h in previous])
        self.assertIsNone(snap["hosts_updated_at"])
        self.assertTrue(snap["connected"])
        self.assertIsNone(snap["error"])
        self.assertEqual(snap["command_deadline"], 30.0)
        self.assertEqual(snap["host_command_deadline"], 0.5)
        self.assertTrue(_wait_until(lambda: stuck.disconnect.called, 2))

    def test_stop_returns_while_host_call_is_stuck(self) -> None:
        poller = self._poller(interval=0.2)  # default 30 s deadline: stop lands mid-call
        poller._send_command = _make_fake_send([])  # type: ignore[method-assign]
        release = threading.Event()
        stuck = _blocking_client(release)
        with mock.patch.object(poller, "_ensure_client"), mock.patch.object(
            poller, "_ensure_host_client", side_effect=self._fake_host_login(poller, stuck)
        ), mock.patch("gms_stormshield.HOST_IFACE_WAIT_SECONDS", 0.05), self.assertLogs(
            "gms_stormshield", level="WARNING"
        ):
            poller.start()
            try:
                self.assertTrue(_wait_until(lambda: stuck.send_command.called, 5))
                started = time.monotonic()
                poller.stop(wait=True)
                elapsed = time.monotonic() - started
            finally:
                poller.stop(wait=True)
                release.set()

        self.assertLess(elapsed, STOP_JOIN_SECONDS + 1)
        for thread in (poller._thread, poller._host_thread):
            self.assertTrue(not thread.is_alive() or thread.daemon)
        self.assertFalse(poller._host_thread.is_alive())
        self.assertEqual(
            {poller._thread.name, poller._host_thread.name},
            {"stormshield-ifaces", "stormshield-hosts"},
        )
        self.assertTrue(_wait_until(lambda: stuck.disconnect.called, 2))

    def test_host_auth_failure_blocks_interface_login(self) -> None:
        poller = self._poller()
        poller.interfaces = parse_monitor_interface(INTERFACE_FIXTURE)
        with mock.patch("gms_stormshield.AUTH_RETRY_SECONDS", 0.3):
            poller._stop_event = _ScriptedStopEvent(poller, max_waits=1)  # type: ignore[assignment]
            with mock.patch.object(
                poller,
                "_ensure_host_client",
                side_effect=AuthenticationError("Authentication failed"),
            ), self.assertLogs("gms_stormshield", level="WARNING"):
                poller._run_hosts()
            self.assertEqual(poller.snapshot()["hosts_error"], AUTH_FAILED_ERROR)

            # The interface loop must not try its own login while the block lasts.
            poller._running = True
            event = _ScriptedStopEvent(poller, max_waits=1)
            poller._stop_event = event  # type: ignore[assignment]
            with mock.patch.object(poller, "_ensure_client") as ensure, mock.patch.object(
                poller, "_poll_once"
            ) as poll:
                poller._run()
            ensure.assert_not_called()
            poll.assert_not_called()
            self.assertEqual(len(event.timeouts), 1)
            self.assertGreater(event.timeouts[0], 0.0)
            self.assertLessEqual(event.timeouts[0], 0.3)
            snap = poller.snapshot()
            self.assertFalse(snap["connected"])
            self.assertEqual(snap["error"], AUTH_FAILED_ERROR)

            # Once the block expires the interface loop logs in again.
            self.assertTrue(_wait_until(lambda: poller._auth_block_remaining() <= 0, 2))
            poller._running = True
            event = _ScriptedStopEvent(poller, max_waits=1)
            poller._stop_event = event  # type: ignore[assignment]
            with mock.patch.object(poller, "_ensure_client") as ensure, mock.patch.object(
                poller, "_poll_once"
            ) as poll:
                poller._run()
            ensure.assert_called_once_with()
            poll.assert_called_once_with()
            self.assertEqual(event.timeouts, [5.0])
            self.assertTrue(poller.snapshot()["connected"])

    CORE_CMD = "MONITOR HOST iface=CoreSwitch"
    BWP_CMD = "MONITOR HOST iface=BWP"
    CORE_SLOW_ERROR = (
        "CoreSwitch: exceeded 60s (firewall busy); showing hosts from BWP"
    )

    def _slow_core_poller(self, **kwargs):
        """Poller whose CoreSwitch host query times out, on a controllable clock.

        Returns ``(poller, calls, slow, clock, ensure)``: ``slow`` is the set of interfaces
        that time out (edit it to let one recover), ``ensure`` the mocked host re-login.
        """
        poller = self._poller(**kwargs)
        poller.interfaces = parse_monitor_interface(INTERFACE_FIXTURE)
        calls: list[str] = []
        slow = {"CoreSwitch"}
        clock = _FakeClock()

        def send(command: str) -> str:
            calls.append(command)
            iface = command[len("MONITOR HOST iface="):]
            if iface in slow:
                raise CommandTimeout(f"{command} exceeded 60s (firewall busy)")
            return _host_output(iface)

        poller._send_host_command = send  # type: ignore[method-assign]
        ensure = self.enterContext(mock.patch.object(poller, "_ensure_host_client"))
        self.enterContext(mock.patch("gms_stormshield.time.monotonic", clock))
        self.enterContext(self.assertLogs("gms_stormshield", level="WARNING"))
        return poller, calls, slow, clock, ensure

    def test_host_timeout_keeps_hosts_from_other_interfaces(self) -> None:
        poller, calls, _slow, _clock, ensure = self._slow_core_poller()
        self.assertTrue(poller._poll_hosts_once())

        # CoreSwitch (never timed out yet) goes first; the timeout abandoned the session,
        # so BWP is queried after a transparent re-login.
        self.assertEqual(calls, [self.CORE_CMD, self.BWP_CMD])
        ensure.assert_called_once_with()
        snap = poller.snapshot()
        self.assertEqual({h["addr"] for h in snap["hosts"]}, {"10.5.1.7", "10.5.1.22"})
        self.assertEqual({h["interface"] for h in snap["hosts"]}, {"BWP"})
        self.assertEqual(snap["host_interfaces"], ["BWP"])
        self.assertEqual(snap["hosts_error"], self.CORE_SLOW_ERROR)
        self.assertIsNotNone(snap["hosts_updated_at"])
        self.assertEqual([s["name"] for s in snap["hosts_slow"]], ["CoreSwitch"])
        self.assertAlmostEqual(
            snap["hosts_slow"][0]["retry_at"] - time.time(),
            HOST_IFACE_BACKOFF_SECONDS,
            delta=5,
        )
        json.dumps(snap)

    def test_all_interfaces_timing_out_keeps_previous_hosts(self) -> None:
        poller, calls, slow, _clock, _ensure = self._slow_core_poller()
        slow.add("BWP")
        previous = rank_top_hosts(parse_monitor_host(HOST_FIXTURE), limit=2)
        poller.hosts = list(previous)
        poller.host_interfaces = ["CoreSwitch", "BWP"]

        self.assertTrue(poller._poll_hosts_once())
        self.assertEqual(calls, [self.CORE_CMD, self.BWP_CMD])
        snap = poller.snapshot()
        self.assertEqual(snap["hosts_error"], "CoreSwitch, BWP: exceeded 60s (firewall busy)")
        self.assertEqual([h["addr"] for h in snap["hosts"]], [h["addr"] for h in previous])
        self.assertEqual(snap["host_interfaces"], ["CoreSwitch", "BWP"])
        self.assertIsNone(snap["hosts_updated_at"])

        # Both are backed off now: the next cycle sends nothing and keeps the list.
        del calls[:]
        self.assertTrue(poller._poll_hosts_once())
        self.assertEqual(calls, [])
        self.assertEqual(
            poller.snapshot()["hosts_error"], "CoreSwitch, BWP: exceeded 60s (firewall busy)"
        )

    def test_failed_relogin_after_timeout_still_publishes_earlier_hosts(self) -> None:
        poller, calls, _slow, _clock, ensure = self._slow_core_poller(
            host_interfaces=["BWP", "CoreSwitch", "BackupLine"]
        )
        ensure.side_effect = RuntimeError("login down")

        with self.assertRaises(RuntimeError):  # the loop records it and backs off
            poller._poll_hosts_once()

        self.assertEqual(calls, [self.BWP_CMD, self.CORE_CMD])  # BackupLine not reached
        snap = poller.snapshot()
        self.assertEqual({h["interface"] for h in snap["hosts"]}, {"BWP"})
        self.assertEqual(snap["host_interfaces"], ["BWP"])
        self.assertEqual(snap["hosts_error"], self.CORE_SLOW_ERROR)

    def test_backed_off_interface_is_skipped_within_backoff_window(self) -> None:
        poller, calls, _slow, clock, ensure = self._slow_core_poller()
        poller._poll_hosts_once()
        del calls[:]

        clock.now += HOST_IFACE_BACKOFF_SECONDS - 1
        self.assertTrue(poller._poll_hosts_once())

        self.assertEqual(calls, [self.BWP_CMD])
        ensure.assert_called_once_with()  # the first cycle's re-login only
        snap = poller.snapshot()
        self.assertEqual(snap["host_interfaces"], ["BWP"])
        self.assertEqual(snap["hosts_error"], self.CORE_SLOW_ERROR)
        self.assertEqual([s["name"] for s in snap["hosts_slow"]], ["CoreSwitch"])
        self.assertAlmostEqual(
            snap["hosts_slow"][0]["retry_at"] - time.time(), 1.0, delta=3
        )

    def test_interface_is_queried_last_once_its_backoff_expires(self) -> None:
        poller, calls, _slow, clock, ensure = self._slow_core_poller()
        poller._poll_hosts_once()
        del calls[:]

        clock.now += HOST_IFACE_BACKOFF_SECONDS
        self.assertTrue(poller._poll_hosts_once())

        # BWP never timed out, so it goes first; the still-slow CoreSwitch goes last
        # (nothing follows it, so no re-login is needed this time).
        self.assertEqual(calls, [self.BWP_CMD, self.CORE_CMD])
        ensure.assert_called_once_with()
        snap = poller.snapshot()
        self.assertEqual(snap["host_interfaces"], ["BWP"])
        self.assertEqual(snap["hosts_error"], self.CORE_SLOW_ERROR)
        self.assertEqual([s["name"] for s in snap["hosts_slow"]], ["CoreSwitch"])

    def test_backoff_doubles_per_timeout_up_to_the_cap(self) -> None:
        poller, _calls, _slow, clock, _ensure = self._slow_core_poller()
        skips = []
        for _ in range(6):
            poller._poll_hosts_once()
            skip = poller._host_iface_backoff["CoreSwitch"] - clock.now
            skips.append(skip)
            clock.now += skip
        self.assertEqual(skips, [120.0, 240.0, 480.0, 600.0, 600.0, 600.0])
        self.assertEqual(HOST_IFACE_BACKOFF_MAX_SECONDS, 600.0)

    def test_success_resets_backoff_and_ordering(self) -> None:
        poller, calls, slow, clock, _ensure = self._slow_core_poller()
        poller._poll_hosts_once()
        self.assertEqual(poller.snapshot()["hosts_error"], self.CORE_SLOW_ERROR)

        slow.clear()  # the firewall recovered
        clock.now += HOST_IFACE_BACKOFF_SECONDS
        del calls[:]
        self.assertTrue(poller._poll_hosts_once())

        self.assertEqual(calls, [self.BWP_CMD, self.CORE_CMD])  # still last this cycle
        snap = poller.snapshot()
        self.assertEqual(snap["host_interfaces"], ["BWP", "CoreSwitch"])
        self.assertIsNone(snap["hosts_error"])
        self.assertEqual(snap["hosts_slow"], [])
        self.assertEqual(poller._host_iface_backoff, {})
        self.assertEqual(poller._host_iface_timeouts, {})

        # Back to the normal interface order ...
        del calls[:]
        poller._poll_hosts_once()
        self.assertEqual(calls, [self.CORE_CMD, self.BWP_CMD])
        # ... and a new timeout starts again from the base backoff, not the doubled one.
        slow.add("CoreSwitch")
        poller._poll_hosts_once()
        self.assertEqual(
            poller._host_iface_backoff["CoreSwitch"] - clock.now, HOST_IFACE_BACKOFF_SECONDS
        )

    def test_host_command_deadline_defaults_to_60s_and_is_used_for_hosts(self) -> None:
        poller = self._poller()
        self.assertEqual(poller.config.host_command_deadline, 60.0)
        self.assertEqual(poller.config.command_deadline, 30.0)
        self.assertEqual(poller.snapshot()["host_command_deadline"], 60.0)

        poller._iface_session.client = mock.Mock()
        poller._host_session.client = mock.Mock()
        response = mock.Mock(output="ok")
        with mock.patch.object(
            poller._host_session, "call", return_value=response
        ) as host_call, mock.patch.object(
            poller._iface_session, "call", return_value=response
        ) as iface_call:
            self.assertEqual(poller._send_host_command("MONITOR HOST iface=BWP"), "ok")
            self.assertEqual(poller._send_command("MONITOR INTERFACE"), "ok")
        self.assertEqual(host_call.call_args.kwargs["deadline"], 60.0)
        self.assertEqual(iface_call.call_args.kwargs["deadline"], 30.0)


@needs_sns_client
class LoginStallTests(unittest.TestCase):
    """A timed-out login backs both loops off for long, growing pauses."""

    STALL = "login exceeded 30s (firewall busy)"

    def _poller(self) -> StormshieldPoller:
        poller = StormshieldPoller(
            StormshieldConfig(host="fw", user="admin", password="x" * 16)
        )
        poller.interfaces = parse_monitor_interface(INTERFACE_FIXTURE)
        return poller

    def _stall(self, session) -> mock._patch:
        return mock.patch.object(session, "call", side_effect=CommandTimeout(self.STALL))

    def test_stalled_logins_wait_longer_each_time_up_to_the_cap(self) -> None:
        poller = self._poller()
        waits = []
        for _ in range(7):
            poller._note_login_stall(CommandTimeout(self.STALL))
            waits.append(round(poller._auth_block_remaining()))
        base = LOGIN_STALL_BACKOFF_SECONDS
        self.assertEqual(waits[:4], [base, base * 2, base * 4, base * 8])
        self.assertEqual(waits[-1], LOGIN_STALL_BACKOFF_MAX_SECONDS)

    def test_interface_loop_stall_sets_error_and_waits(self) -> None:
        poller = self._poller()
        event = _ScriptedStopEvent(poller, max_waits=1)
        poller._stop_event = event  # type: ignore[assignment]
        with self._stall(poller._iface_session), mock.patch.object(
            poller, "_poll_once"
        ) as poll, self.assertLogs("gms_stormshield", level="WARNING"):
            poller._run()
        poll.assert_not_called()
        self.assertAlmostEqual(event.timeouts[0], LOGIN_STALL_BACKOFF_SECONDS, delta=1)
        snap = poller.snapshot()
        self.assertFalse(snap["connected"])
        self.assertIn("not opening new API sessions", snap["error"])
        self.assertEqual(poller._login_stalls, 1)

    def test_host_loop_stall_blocks_interface_login(self) -> None:
        poller = self._poller()
        poller._stop_event = _ScriptedStopEvent(poller, max_waits=1)  # type: ignore[assignment]
        with self._stall(poller._host_session), self.assertLogs(
            "gms_stormshield", level="WARNING"
        ):
            poller._run_hosts()
        self.assertIn("not opening new API sessions", poller.snapshot()["hosts_error"])

        poller._running = True
        event = _ScriptedStopEvent(poller, max_waits=1)
        poller._stop_event = event  # type: ignore[assignment]
        with mock.patch.object(poller._iface_session, "call") as call:
            poller._run()
        call.assert_not_called()
        self.assertGreater(event.timeouts[0], LOGIN_STALL_BACKOFF_SECONDS - 5)
        self.assertIn("not opening new API sessions", poller.snapshot()["error"])

    def test_every_login_rechecks_the_block_inside_the_gate(self) -> None:
        # Covers the host loop's mid-poll re-login and a block set by the other loop
        # after this loop's top-of-loop check: _ensure_session refuses on its own.
        poller = self._poller()
        poller._note_login_stall(CommandTimeout(self.STALL))
        for session, ensure in (
            (poller._host_session, poller._ensure_host_client),
            (poller._iface_session, poller._ensure_client),
        ):
            with self.subTest(session=session.role), mock.patch.object(
                session, "call"
            ) as call:
                with self.assertRaises(LoginBlocked) as ctx:
                    ensure()
                call.assert_not_called()
                self.assertGreater(ctx.exception.remaining, 0)
        self.assertFalse(poller._login_gate.locked())

    def test_host_loop_handles_a_refused_mid_poll_relogin(self) -> None:
        poller = self._poller()
        poller._note_login_stall(CommandTimeout(self.STALL))
        poller._host_session.client = object()  # connected, so the loop skips its check
        event = _ScriptedStopEvent(poller, max_waits=1)
        poller._stop_event = event  # type: ignore[assignment]
        with mock.patch.object(
            poller, "_poll_hosts_once", side_effect=LoginBlocked(90.0)
        ):
            poller._run_hosts()
        self.assertEqual(event.timeouts, [90.0])
        self.assertIn("not opening new API sessions", poller.snapshot()["hosts_error"])

    def test_stall_keeps_a_longer_brute_force_block_and_its_text(self) -> None:
        poller = self._poller()
        with self.assertLogs("gms_stormshield", level="WARNING"):
            poller._record_auth_failure(
                AuthenticationError("Brut force detected, try again after 900 seconds.")
            )
        poller._note_login_stall(CommandTimeout(self.STALL))
        self.assertEqual(poller._auth_error, AUTH_BLOCKED_ERROR)
        self.assertGreater(poller._auth_block_remaining(), 800)

    def test_rejected_login_blocks_before_the_gate_is_released(self) -> None:
        poller = self._poller()
        with mock.patch.object(
            poller._iface_session,
            "call",
            side_effect=AuthenticationError("Authentication failed"),
        ):
            with self.assertRaises(AuthenticationError):
                poller._ensure_client()
        # Set by _ensure_session itself, before the loop's handler runs.
        self.assertGreater(poller._auth_block_remaining(), AUTH_RETRY_SECONDS - 5)
        self.assertEqual(poller._auth_error, AUTH_FAILED_ERROR)

    def test_host_stall_leaves_a_connected_interface_session_alone(self) -> None:
        poller = self._poller()
        poller._iface_session.client = object()  # already logged in
        with self.assertLogs("gms_stormshield", level="WARNING"):
            with self._stall(poller._host_session):
                with self.assertRaises(LoginTimeout) as ctx:
                    poller._ensure_host_client()
            poller._record_login_stall(ctx.exception, poller._host_session)
        poller.connected = True
        self.assertTrue(poller.snapshot()["connected"])
        event = _ScriptedStopEvent(poller, max_waits=1)
        poller._stop_event = event  # type: ignore[assignment]
        with mock.patch.object(poller, "_poll_once") as poll:
            poller._run()
        poll.assert_called_once()
        self.assertTrue(poller.snapshot()["connected"])

    def test_success_resets_the_streak(self) -> None:
        poller = self._poller()
        with self._stall(poller._iface_session):
            with self.assertRaises(LoginTimeout):
                poller._ensure_client()
        self.assertEqual(poller._login_stalls, 1)
        poller._auth_blocked_until = 0.0  # the block ran out
        with mock.patch.object(
            poller._iface_session, "call", return_value=object()
        ), mock.patch.object(poller, "_fetch_system_property"):
            poller._ensure_client()
        self.assertEqual(poller._login_stalls, 0)

    def test_no_login_starts_once_stopping_even_after_getting_the_gate(self) -> None:
        poller = self._poller()
        poller._running = False
        with mock.patch.object(poller._iface_session, "call") as call:
            with self.assertRaises(CommandTimeout):
                poller._ensure_client()
        call.assert_not_called()
        self.assertFalse(poller._login_gate.locked())

    def test_stop_during_login_is_not_counted_as_a_stall(self) -> None:
        poller = self._poller()
        poller._running = False
        with mock.patch.object(
            poller._iface_session,
            "call",
            side_effect=CommandTimeout("login abandoned (poller stopping)"),
        ):
            with self.assertRaises(CommandTimeout) as ctx:
                poller._ensure_client()
        self.assertNotIsInstance(ctx.exception, LoginTimeout)
        self.assertEqual(poller._login_stalls, 0)
        self.assertLessEqual(poller._auth_block_remaining(), 0)


@needs_sns_client
class RealResponseTests(unittest.TestCase):
    def _poller(self) -> StormshieldPoller:
        return StormshieldPoller(
            StormshieldConfig(host="fw", user="admin", password="x" * 16)
        )

    def test_fetch_system_property_reads_case_insensitive_response(self) -> None:
        response = Response(
            ret=100,
            code="00a00100",
            msg="Ok",
            output='100 code=00a00100 msg="Ok" format="section"\n'
            "[Result]\nModel=SN710\nVersion=4.8.11\n",
        )
        poller = self._poller()
        poller._client = mock.Mock()
        poller._client.send_command.return_value = response
        poller._fetch_system_property()
        self.assertEqual(poller.model, "SN710")
        self.assertEqual(poller.version, "4.8.11")

    def test_send_command_returns_output_text_of_real_response(self) -> None:
        response = Response(
            ret=100,
            code="00a00100",
            msg="Ok",
            output='101 code=00a01000 msg="Begin" format="section_line"\n'
            '[Result]\naddr=10.0.0.9 name="My PC" interface=LAN byte=1\n'
            '100 code=00a00100 msg="Ok"',
        )
        poller = self._poller()
        poller._client = mock.Mock()
        poller._client.send_command.return_value = response
        hosts = parse_monitor_host(poller._send_command("MONITOR HOST iface=LAN"))
        self.assertEqual(hosts[0]["addr"], "10.0.0.9")
        self.assertEqual(hosts[0]["name"], "My PC")


if __name__ == "__main__":
    unittest.main()
