#!/usr/bin/env python3
"""Tests for gms_sns_sites (saved sites file, candidate building, probe classification)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import requests  # noqa: E402

import gms_sns_sites  # noqa: E402
from gms_sns_sites import (  # noqa: E402
    default_candidates,
    forget_host,
    load_sites,
    parse_posix_gateways,
    parse_windows_gateways,
    probe_candidates,
    remember_host,
    save_sites,
)

WINDOWS_ROUTE_PRINT = """\
===========================================================================
Interface List
  8...00 e0 4c 68 01 02 ......Realtek PCIe GbE Family Controller
  1...........................Software Loopback Interface 1
===========================================================================

IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0       10.5.2.1      10.5.2.50     25
          0.0.0.0          0.0.0.0      192.168.43.1  192.168.43.7     50
          0.0.0.0          0.0.0.0         On-link      10.99.0.2    300
         10.5.2.0    255.255.254.0         On-link      10.5.2.50    281
        127.0.0.0        255.0.0.0         On-link       127.0.0.1    331
===========================================================================
Persistent Routes:
  Network Address          Netmask  Gateway Address  Metric
          0.0.0.0          0.0.0.0         10.5.2.1  Default
===========================================================================
"""

POSIX_ROUTE_OUTPUT = """\
default via 192.168.1.1 dev eth0 proto dhcp metric 100
default via 10.0.0.1 dev wlan0 proto dhcp metric 600
default dev ppp0 scope link
"""


def _response(text: str = "", headers: dict | None = None, url: str = "https://x/") -> SimpleNamespace:
    return SimpleNamespace(text=text, headers=headers or {}, url=url, close=lambda: None)


class SitesFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "gms_sns_sites.json"

    def test_missing_or_corrupt_file_loads_empty(self) -> None:
        empty = {"user": "gmsmonitoring", "hosts": [], "last_host": None}
        self.assertEqual(load_sites(self.path), empty)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(load_sites(self.path), empty)
        self.path.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(load_sites(self.path), empty)

    def test_round_trip_and_schema(self) -> None:
        data = load_sites(self.path)
        remember_host(data, "10.5.1.1", "Church A", now=1000.0)
        save_sites(self.path, data)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(
            raw,
            {
                "user": "gmsmonitoring",
                "hosts": [{"host": "10.5.1.1", "label": "Church A", "last_seen": 1000.0}],
                "last_host": "10.5.1.1",
            },
        )
        self.assertEqual(load_sites(self.path), raw)
        self.assertEqual(os.listdir(self._tmp.name), ["gms_sns_sites.json"])

    def test_save_never_writes_a_password(self) -> None:
        data = load_sites(self.path)
        remember_host(data, "10.5.1.1")
        data["password"] = "hunter2-secret"
        data["hosts"][0]["password"] = "hunter2-secret"
        save_sites(self.path, data)
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("hunter2-secret", text)
        self.assertNotIn("password", text)

    def test_remember_dedupes_moves_to_front_and_keeps_label(self) -> None:
        data = load_sites(self.path)
        remember_host(data, "10.5.1.1", "A", now=1.0)
        remember_host(data, "10.9.0.1", "B", now=2.0)
        remember_host(data, "10.5.1.1", "", now=3.0)
        self.assertEqual([h["host"] for h in data["hosts"]], ["10.5.1.1", "10.9.0.1"])
        self.assertEqual(data["hosts"][0]["label"], "A")
        self.assertEqual(data["hosts"][0]["last_seen"], 3.0)
        self.assertEqual(data["last_host"], "10.5.1.1")
        remember_host(data, "10.5.1.1", "Renamed", now=4.0)
        self.assertEqual(data["hosts"][0]["label"], "Renamed")
        self.assertEqual(len(data["hosts"]), 2)

    def test_remember_rejects_invalid_host(self) -> None:
        data = load_sites(self.path)
        with self.assertRaises(ValueError):
            remember_host(data, "https://evil.example/")

    def test_load_drops_invalid_and_duplicate_entries(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "user": "ops",
                    "hosts": [
                        {"host": "10.5.1.1", "label": "A", "last_seen": 5},
                        {"host": "10.5.1.1", "label": "dup"},
                        {"host": "bad host!", "label": "x"},
                        {"host": 42},
                        "fw.example.org",
                        7,
                    ],
                    "last_host": "fw.example.org",
                }
            ),
            encoding="utf-8",
        )
        data = load_sites(self.path)
        self.assertEqual(data["user"], "ops")
        self.assertEqual([h["host"] for h in data["hosts"]], ["10.5.1.1", "fw.example.org"])
        self.assertEqual(data["hosts"][0]["last_seen"], 5.0)
        self.assertIsNone(data["hosts"][1]["last_seen"])
        self.assertEqual(data["last_host"], "fw.example.org")

    def test_forget_updates_last_host(self) -> None:
        data = load_sites(self.path)
        remember_host(data, "10.5.1.1")
        remember_host(data, "10.9.0.1")
        forget_host(data, "10.9.0.1")
        self.assertEqual([h["host"] for h in data["hosts"]], ["10.5.1.1"])
        self.assertEqual(data["last_host"], "10.5.1.1")
        forget_host(data, "10.5.1.1")
        self.assertEqual(data["hosts"], [])
        self.assertIsNone(data["last_host"])

    def test_failed_write_leaves_no_temp_file_and_keeps_old_content(self) -> None:
        data = load_sites(self.path)
        remember_host(data, "10.5.1.1", now=1.0)
        save_sites(self.path, data)
        before = self.path.read_text(encoding="utf-8")
        with mock.patch("gms_sns_sites.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save_sites(self.path, data)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self.assertEqual(os.listdir(self._tmp.name), ["gms_sns_sites.json"])


class GatewayParsingTests(unittest.TestCase):
    def test_windows_route_print(self) -> None:
        self.assertEqual(
            parse_windows_gateways(WINDOWS_ROUTE_PRINT), ["10.5.2.1", "192.168.43.1"]
        )

    def test_posix_ip_route(self) -> None:
        self.assertEqual(
            parse_posix_gateways(POSIX_ROUTE_OUTPUT), ["192.168.1.1", "10.0.0.1"]
        )

    def test_empty_output(self) -> None:
        self.assertEqual(parse_windows_gateways(""), [])
        self.assertEqual(parse_posix_gateways(""), [])

    def test_default_gateways_uses_platform_command(self) -> None:
        with mock.patch.object(gms_sns_sites.sys, "platform", "win32"), mock.patch.object(
            gms_sns_sites, "_command_output", return_value=WINDOWS_ROUTE_PRINT
        ) as run:
            self.assertEqual(gms_sns_sites.default_gateways()[0], "10.5.2.1")
        run.assert_called_once_with(["route", "print", "-4"])
        with mock.patch.object(gms_sns_sites.sys, "platform", "linux"), mock.patch.object(
            gms_sns_sites, "_command_output", return_value=POSIX_ROUTE_OUTPUT
        ) as run:
            self.assertEqual(gms_sns_sites.default_gateways()[0], "192.168.1.1")
        run.assert_called_once_with(["ip", "route", "show", "default"])

    def test_default_gateways_swallows_failures(self) -> None:
        with mock.patch.object(
            gms_sns_sites, "_command_output", side_effect=FileNotFoundError("no ip")
        ):
            self.assertEqual(gms_sns_sites.default_gateways(), [])


class DefaultCandidatesTests(unittest.TestCase):
    def test_saved_hosts_then_gateways_then_guesses_deduped(self) -> None:
        sites = {
            "user": "gmsmonitoring",
            "hosts": [
                {"host": "10.9.0.1", "label": "", "last_seen": 1},
                {"host": "10.5.1.1", "label": "", "last_seen": 2},
            ],
            "last_host": "10.5.1.1",
        }
        with mock.patch.object(
            gms_sns_sites, "default_gateways", return_value=["10.5.2.1", "10.9.0.1"]
        ):
            self.assertEqual(
                default_candidates(sites),
                ["10.5.1.1", "10.9.0.1", "10.5.2.1"],
            )

    def test_guess_dot_one_is_added_for_other_last_octets(self) -> None:
        with mock.patch.object(
            gms_sns_sites, "default_gateways", return_value=["192.168.7.254"]
        ):
            self.assertEqual(
                default_candidates({"hosts": [], "last_host": None}),
                ["192.168.7.254", "192.168.7.1"],
            )

    def test_without_gateways_only_saved_hosts(self) -> None:
        sites = {"hosts": [{"host": "10.5.1.1"}], "last_host": None}
        with mock.patch.object(gms_sns_sites, "default_gateways", return_value=[]):
            self.assertEqual(default_candidates(sites), ["10.5.1.1"])


class ProbeCandidatesTests(unittest.TestCase):
    def test_classifies_stormshield_plain_and_timeout_in_input_order(self) -> None:
        responses = {
            "https://10.5.1.1:443/": _response("<title>Stormshield Network Security</title>"),
            "https://10.5.2.1:443/": _response("<html>router login</html>"),
        }

        def fake_get(url, **kwargs):
            self.assertIs(kwargs["verify"], False)
            self.assertIs(kwargs["allow_redirects"], True)
            self.assertEqual(kwargs["timeout"], 2.0)
            if url == "https://10.5.9.9:443/":
                raise requests.exceptions.ConnectTimeout("timed out")
            return responses[url]

        with mock.patch("gms_sns_sites.requests.get", side_effect=fake_get):
            result = probe_candidates(["10.5.1.1", "10.5.9.9", "10.5.2.1"])

        self.assertEqual([r["host"] for r in result], ["10.5.1.1", "10.5.9.9", "10.5.2.1"])
        self.assertEqual(
            [(r["reachable"], r["stormshield"]) for r in result],
            [(True, True), (False, False), (True, False)],
        )
        self.assertIsNone(result[1]["latency_ms"])
        self.assertIsInstance(result[0]["latency_ms"], float)

    def test_stormshield_detected_from_headers_final_url_and_auth_path(self) -> None:
        cases = {
            "10.0.0.1": _response("", {"Server": "Stormshield-SNS"}),
            "10.0.0.2": _response("", url="https://fw.stormshield.eu/login"),
            "10.0.0.3": _response("", url="https://10.0.0.3/auth/login.html"),
            "10.0.0.4": _response("", url="https://10.0.0.4/index.html"),
        }
        with mock.patch(
            "gms_sns_sites.requests.get",
            side_effect=lambda url, **kw: cases[url.split("//")[1].split(":")[0]],
        ):
            result = probe_candidates(list(cases))
        self.assertEqual(
            [r["stormshield"] for r in result], [True, True, True, False]
        )
        self.assertTrue(all(r["reachable"] for r in result))

    def test_probes_run_concurrently(self) -> None:
        def slow_get(url, **kwargs):
            time.sleep(0.2)
            return _response("ok")

        hosts = [f"10.0.0.{n}" for n in range(1, 9)]
        started = time.monotonic()
        with mock.patch("gms_sns_sites.requests.get", side_effect=slow_get):
            result = probe_candidates(hosts)
        self.assertEqual(len(result), 8)
        self.assertLess(time.monotonic() - started, 1.0)

    def test_ipv6_literal_is_bracketed_and_bad_hosts_are_not_requested(self) -> None:
        seen: list[str] = []

        def fake_get(url, **kwargs):
            seen.append(url)
            return _response("ok")

        with mock.patch("gms_sns_sites.requests.get", side_effect=fake_get):
            result = probe_candidates(["fd00::1", "evil.example/@x", ""], port=8443)
        self.assertEqual(seen, ["https://[fd00::1]:8443/"])
        self.assertEqual([r["reachable"] for r in result], [True, False, False])

    def test_empty_candidate_list(self) -> None:
        with mock.patch("gms_sns_sites.requests.get") as get:
            self.assertEqual(probe_candidates([]), [])
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
