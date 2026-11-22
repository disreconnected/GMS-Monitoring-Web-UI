#!/usr/bin/env python3
"""Security tests for gms_web_server."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from fastapi.testclient import TestClient  # noqa: E402

from gms_web_server import (  # noqa: E402
    MonitorService,
    ServerSecurity,
    SnsManager,
    VALID_WS_ACTIONS,
    WS_APP_PROTOCOL,
    WS_TOKEN_PREFIX,
    build_snapshot,
    create_app,
    extract_ws_token,
    handle_ws_action,
    is_loopback_address,
    validate_bind_address,
)


def _ws_headers(origin: str, token: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Sec-WebSocket-Protocol": f"{WS_APP_PROTOCOL}, {WS_TOKEN_PREFIX}{token}",
    }


class LoopbackTests(unittest.TestCase):
    def test_loopback_addresses(self) -> None:
        self.assertTrue(is_loopback_address("127.0.0.1"))
        self.assertTrue(is_loopback_address("::1"))
        self.assertFalse(is_loopback_address("192.168.1.1"))
        self.assertFalse(is_loopback_address(None))


class BindValidationTests(unittest.TestCase):
    def test_rejects_non_loopback_without_remote(self) -> None:
        with self.assertRaises(SystemExit):
            validate_bind_address("192.168.1.10", allow_remote=False)

    def test_rejects_wildcard_without_remote(self) -> None:
        with self.assertRaises(SystemExit):
            validate_bind_address("0.0.0.0", allow_remote=False)

    def test_allows_loopback(self) -> None:
        validate_bind_address("127.0.0.1", allow_remote=False)


class ServerSecurityTests(unittest.TestCase):
    def test_generates_token_in_local_mode(self) -> None:
        security = ServerSecurity("127.0.0.1", 9847)
        self.assertGreater(len(security.token), 20)
        self.assertIn("#token=", security.dashboard_url())

    def test_remote_mode_requires_access_token(self) -> None:
        with self.assertRaises(SystemExit):
            ServerSecurity("0.0.0.0", 9847, allow_remote=True, access_token=None)
        with self.assertRaises(SystemExit):
            ServerSecurity("0.0.0.0", 9847, allow_remote=True, access_token="short")

    def test_remote_mode_omits_token_from_url(self) -> None:
        security = ServerSecurity(
            "0.0.0.0",
            9847,
            allow_remote=True,
            access_token="a" * 16,
        )
        self.assertNotIn("#token=", security.dashboard_url())

    def test_token_verification(self) -> None:
        security = ServerSecurity("127.0.0.1", 9847)
        self.assertTrue(security.verify_token(security.token))
        self.assertFalse(security.verify_token("wrong-token"))
        self.assertFalse(security.verify_token(None))

    def test_origin_validation(self) -> None:
        security = ServerSecurity(
            "127.0.0.1",
            9847,
            allowed_origins=["http://localhost:5173"],
        )
        self.assertTrue(security.verify_origin("http://127.0.0.1:9847"))
        self.assertTrue(security.verify_origin("http://localhost:5173"))
        self.assertTrue(security.verify_origin(None, "127.0.0.1"))
        self.assertFalse(security.verify_origin("http://evil.example"))
        self.assertFalse(security.verify_origin(None))
        self.assertFalse(security.verify_origin(None, "192.168.1.1"))

    def test_remote_mode_rejects_missing_origin(self) -> None:
        security = ServerSecurity(
            "0.0.0.0",
            9847,
            allow_remote=True,
            access_token="a" * 16,
        )
        self.assertFalse(security.verify_origin(None, "127.0.0.1"))

    def test_ws_client_limit(self) -> None:
        security = ServerSecurity("127.0.0.1", 9847, max_ws_clients=1)
        self.assertTrue(security.try_acquire_ws_slot())
        self.assertFalse(security.try_acquire_ws_slot())
        security.release_ws_slot()
        self.assertTrue(security.try_acquire_ws_slot())
        security.release_ws_slot()

    def test_traceroute_throttle(self) -> None:
        security = ServerSecurity("127.0.0.1", 9847, traceroute_cooldown=60.0)
        self.assertTrue(security.can_trigger_traceroute())
        self.assertFalse(security.can_trigger_traceroute())


class HandleWsActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.monitor = MonitorService("127.0.0.1")
        self.security = ServerSecurity("127.0.0.1", 9847)

    def test_ignores_invalid_payloads(self) -> None:
        handle_ws_action(self.monitor, self.security, "not-json")
        handle_ws_action(self.monitor, self.security, {"action": "delete"})
        handle_ws_action(self.monitor, self.security, {"action": "set_window", "size": "bad"})

    def test_accepts_valid_actions(self) -> None:
        for action in VALID_WS_ACTIONS:
            if action == "set_window":
                handle_ws_action(self.monitor, self.security, {"action": action, "size": 80})
            else:
                handle_ws_action(self.monitor, self.security, {"action": action})


class FakePoller:
    """Stands in for StormshieldPoller: no threads, no network."""

    def __init__(self, config) -> None:
        self.config = config
        self.started = False
        self.stop_calls: list[bool] = []

    def start(self) -> None:
        self.started = True

    def stop(self, wait: bool = False) -> None:
        self.stop_calls.append(wait)

    def snapshot(self) -> dict:
        return {
            "connected": True,
            "error": None,
            "model": "SN-TEST",
            "version": "4.8.0",
            "host": self.config.host,
            "last_poll": None,
            "interfaces": [],
            "hosts": [],
            "host_interfaces": [],
            "hosts_error": None,
            "hosts_updated_at": None,
        }


class SnsActionTests(unittest.TestCase):
    ENV_PASSWORD = "env-password-xyz"
    WS_PASSWORD = "typed-password-abc"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.sites_path = Path(self._tmp.name) / "gms_sns_sites.json"
        self.monitor = MonitorService("127.0.0.1")
        self.security = ServerSecurity("127.0.0.1", 9847)
        self.pollers: list[FakePoller] = []

    def _factory(self, config) -> FakePoller:
        poller = FakePoller(config)
        self.pollers.append(poller)
        return poller

    def _sns(self, password: str = "") -> SnsManager:
        return SnsManager(
            sites_path=self.sites_path,
            password=password,
            poller_factory=self._factory,
        )

    def _send(self, sns: SnsManager, **msg) -> None:
        handle_ws_action(self.monitor, self.security, msg, sns)
        sns.join()

    def test_malformed_connect_payloads_are_ignored(self) -> None:
        sns = self._sns(self.ENV_PASSWORD)
        bad_payloads = [
            {"action": "sns_connect"},
            {"action": "sns_connect", "host": 123},
            {"action": "sns_connect", "host": ["10.5.1.1"]},
            {"action": "sns_connect", "host": None},
            {"action": "sns_connect", "host": "10.5.1.1", "password": 5},
            {"action": "sns_connect", "host": "10.5.1.1", "password": "x" * 300},
            {"action": "sns_connect", "host": "10.5.1.1", "label": {"a": 1}},
            {"action": "sns_forget"},
            {"action": "sns_forget", "host": 7},
        ]
        for payload in bad_payloads:
            handle_ws_action(self.monitor, self.security, payload, sns)
        sns.join()
        state = sns.snapshot()
        self.assertEqual(self.pollers, [])
        self.assertIsNone(state["active_host"])
        self.assertIsNone(state["message"])
        self.assertFalse(state["busy"])
        self.assertFalse(self.sites_path.exists())

    def test_invalid_host_string_sets_message_and_connects_nothing(self) -> None:
        sns = self._sns(self.ENV_PASSWORD)
        for host in ("", "   ", "http://10.5.1.1/", "-oProxy", "a b", "x" * 300):
            self._send(sns, action="sns_connect", host=host)
            self.assertEqual(sns.snapshot()["message"], "invalid firewall address")
        self.assertEqual(self.pollers, [])

    def test_password_rejected_when_env_password_is_set(self) -> None:
        sns = self._sns(self.ENV_PASSWORD)
        self._send(sns, action="sns_connect", host="10.5.1.1", password="other-pass-123")
        state = sns.snapshot()
        self.assertEqual(self.pollers, [])
        self.assertIsNone(state["active_host"])
        self.assertTrue(state["password_set"])
        self.assertIn("GMS_SNS_PASSWORD", state["message"])
        self.assertNotIn("other-pass-123", json.dumps(state))
        self.assertNotIn(self.ENV_PASSWORD, json.dumps(state))

    def test_connect_without_any_password_is_refused(self) -> None:
        sns = self._sns()
        self._send(sns, action="sns_connect", host="10.5.1.1")
        self.assertEqual(self.pollers, [])
        self.assertFalse(sns.snapshot()["password_set"])
        self.assertTrue(sns.snapshot()["message"])

    def test_valid_connect_starts_poller_and_snapshot_reflects_it(self) -> None:
        sns = self._sns(self.ENV_PASSWORD)
        self._send(sns, action="sns_connect", host="10.5.1.1", label="Church A")

        self.assertEqual(len(self.pollers), 1)
        poller = self.pollers[0]
        self.assertTrue(poller.started)
        self.assertEqual(poller.config.host, "10.5.1.1")
        self.assertEqual(poller.config.password, self.ENV_PASSWORD)
        self.assertEqual(poller.config.user, "gmsmonitoring")
        self.assertIs(sns.poller, poller)

        snapshot = build_snapshot(self.monitor.state, self.monitor, sns.poller, sns)
        self.assertEqual(snapshot["sns"]["active_host"], "10.5.1.1")
        self.assertTrue(snapshot["sns"]["password_set"])
        self.assertFalse(snapshot["sns"]["busy"])
        self.assertIsNone(snapshot["sns"]["message"])
        self.assertEqual(snapshot["sns"]["saved_hosts"][0]["host"], "10.5.1.1")
        self.assertEqual(snapshot["sns"]["saved_hosts"][0]["label"], "Church A")
        self.assertEqual(snapshot["stormshield"]["host"], "10.5.1.1")
        self.assertNotIn(self.ENV_PASSWORD, json.dumps(snapshot))

        saved = self.sites_path.read_text(encoding="utf-8")
        self.assertIn("10.5.1.1", saved)
        self.assertNotIn(self.ENV_PASSWORD, saved)

    def test_ws_password_stays_in_memory_and_disconnect_forgets_it(self) -> None:
        sns = self._sns()
        self._send(sns, action="sns_connect", host="10.5.1.1", password=self.WS_PASSWORD)
        state = sns.snapshot()
        self.assertEqual(state["active_host"], "10.5.1.1")
        self.assertTrue(state["password_set"])
        self.assertEqual(self.pollers[0].config.password, self.WS_PASSWORD)
        self.assertNotIn(self.WS_PASSWORD, json.dumps(state))
        self.assertNotIn(self.WS_PASSWORD, self.sites_path.read_text(encoding="utf-8"))

        # A later connect may omit the password and reuses the remembered one.
        self._send(sns, action="sns_connect", host="10.9.0.1")
        self.assertEqual(self.pollers[1].config.password, self.WS_PASSWORD)

        self._send(sns, action="sns_disconnect")
        state = sns.snapshot()
        self.assertIsNone(state["active_host"])
        self.assertFalse(state["password_set"])
        self.assertIsNone(sns.poller)

    def test_connect_replaces_poller_and_waits_for_the_old_one_to_stop(self) -> None:
        sns = self._sns(self.ENV_PASSWORD)
        self._send(sns, action="sns_connect", host="10.5.1.1")
        self._send(sns, action="sns_connect", host="10.9.0.1")
        first, second = self.pollers
        self.assertEqual(first.stop_calls, [True])
        self.assertEqual(second.stop_calls, [])
        self.assertIs(sns.poller, second)
        self.assertEqual(sns.snapshot()["active_host"], "10.9.0.1")
        self.assertEqual(
            [h["host"] for h in sns.snapshot()["saved_hosts"]], ["10.9.0.1", "10.5.1.1"]
        )

    def test_second_request_while_busy_is_refused(self) -> None:
        release = threading.Event()

        def slow_factory(config) -> FakePoller:
            release.wait(5)
            return self._factory(config)

        sns = SnsManager(
            sites_path=self.sites_path,
            password=self.ENV_PASSWORD,
            poller_factory=slow_factory,
        )
        self.assertTrue(sns.connect("10.5.1.1"))
        state = sns.snapshot()
        self.assertTrue(state["busy"])
        self.assertEqual(state["message"], "connecting to 10.5.1.1")
        self.assertFalse(sns.connect("10.9.0.1"))
        self.assertFalse(sns.detect())
        self.assertFalse(sns.disconnect())
        release.set()
        sns.join()
        self.assertEqual(len(self.pollers), 1)
        self.assertFalse(sns.snapshot()["busy"])

    def test_detect_stores_candidates(self) -> None:
        sns = self._sns(self.ENV_PASSWORD)
        results = [
            {"host": "10.5.1.1", "reachable": True, "stormshield": True, "latency_ms": 12.5},
            {"host": "10.5.2.1", "reachable": False, "stormshield": False, "latency_ms": None},
        ]
        with patch(
            "gms_web_server.default_candidates", return_value=["10.5.1.1", "10.5.2.1"]
        ), patch("gms_web_server.probe_candidates", return_value=results) as probe:
            self._send(sns, action="sns_detect")
        probe.assert_called_once_with(["10.5.1.1", "10.5.2.1"], port=443)
        state = sns.snapshot()
        self.assertEqual(state["candidates"], results)
        self.assertIsNotNone(state["probed_at"])
        self.assertIsNone(state["message"])
        self.assertEqual(self.pollers, [])

        with patch(
            "gms_web_server.default_candidates", return_value=["10.5.2.1"]
        ), patch("gms_web_server.probe_candidates", return_value=results[1:]):
            self._send(sns, action="sns_detect")
        self.assertEqual(
            sns.snapshot()["message"], "no Stormshield found among 1 candidates"
        )

    def test_forget_removes_saved_host(self) -> None:
        sns = self._sns(self.ENV_PASSWORD)
        self._send(sns, action="sns_connect", host="10.5.1.1")
        self._send(sns, action="sns_connect", host="10.9.0.1")
        self._send(sns, action="sns_forget", host="10.5.1.1")
        self.assertEqual([h["host"] for h in sns.snapshot()["saved_hosts"]], ["10.9.0.1"])
        saved = json.loads(self.sites_path.read_text(encoding="utf-8"))
        self.assertEqual([h["host"] for h in saved["hosts"]], ["10.9.0.1"])

    def test_autoconnect_connects_first_stormshield_candidate(self) -> None:
        self.sites_path.write_text(
            json.dumps({"hosts": [{"host": "10.9.0.1"}, {"host": "10.5.1.1"}]}),
            encoding="utf-8",
        )
        sns = self._sns(self.ENV_PASSWORD)
        results = [
            {"host": "10.9.0.1", "reachable": False, "stormshield": False, "latency_ms": None},
            {"host": "10.5.1.1", "reachable": True, "stormshield": True, "latency_ms": 9.0},
            {"host": "10.5.2.1", "reachable": True, "stormshield": True, "latency_ms": 9.0},
        ]
        lines: list[str] = []
        with patch(
            "gms_web_server.default_candidates", return_value=[r["host"] for r in results]
        ), patch("gms_web_server.probe_candidates", return_value=results):
            self.assertTrue(sns.autoconnect(announce=lines.append))
            sns.join()
        self.assertEqual(sns.snapshot()["active_host"], "10.5.1.1")
        self.assertEqual(len(self.pollers), 1)
        self.assertEqual(len(lines), 1)
        self.assertIn("10.5.1.1", lines[0])
        self.assertNotIn(self.ENV_PASSWORD, lines[0])

    def test_autoconnect_reports_when_nothing_is_reachable(self) -> None:
        self.sites_path.write_text(
            json.dumps({"hosts": [{"host": "10.5.1.1"}]}), encoding="utf-8"
        )
        sns = self._sns(self.ENV_PASSWORD)
        results = [
            {"host": "10.5.1.1", "reachable": False, "stormshield": False, "latency_ms": None}
        ]
        lines: list[str] = []
        with patch(
            "gms_web_server.default_candidates", return_value=["10.5.1.1"]
        ), patch("gms_web_server.probe_candidates", return_value=results):
            self.assertTrue(sns.autoconnect(announce=lines.append))
            sns.join()
        self.assertEqual(self.pollers, [])
        self.assertEqual(len(lines), 1)
        self.assertIn("no saved Stormshield site reachable", lines[0])

    def test_autoconnect_needs_password_and_saved_hosts(self) -> None:
        self.sites_path.write_text(
            json.dumps({"hosts": [{"host": "10.5.1.1"}]}), encoding="utf-8"
        )
        self.assertFalse(self._sns().autoconnect())  # no password
        self.sites_path.write_text(json.dumps({"hosts": []}), encoding="utf-8")
        self.assertFalse(self._sns(self.ENV_PASSWORD).autoconnect())  # no saved hosts

    def test_shutdown_stops_poller_once_and_refuses_new_connects(self) -> None:
        sns = self._sns(self.ENV_PASSWORD)
        self._send(sns, action="sns_connect", host="10.5.1.1")
        sns.shutdown()
        sns.shutdown()
        self.assertEqual(self.pollers[0].stop_calls, [True])
        self.assertFalse(sns.connect("10.9.0.1"))
        self.assertEqual(len(self.pollers), 1)

    def test_websocket_loop_sees_a_poller_started_after_connect(self) -> None:
        sns = self._sns(self.ENV_PASSWORD)
        app = create_app(self.monitor, self.security, sns=sns)
        origin = "http://127.0.0.1:9847"
        with TestClient(app) as client:
            with client.websocket_connect(
                "/ws", headers=_ws_headers(origin, self.security.token)
            ) as ws:
                first = ws.receive_json()
                self.assertNotIn("stormshield", first)
                self.assertIsNone(first["sns"]["active_host"])
                self.assertTrue(first["sns"]["password_set"])
                ws.send_json({"action": "sns_connect", "host": "10.5.1.1"})
                payload = first
                for _ in range(6):
                    payload = ws.receive_json()
                    if "stormshield" in payload:
                        break
        self.assertEqual(payload["sns"]["active_host"], "10.5.1.1")
        self.assertEqual(payload["stormshield"]["host"], "10.5.1.1")
        self.assertNotIn(self.ENV_PASSWORD, json.dumps(payload))


class ApiSecurityIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.security = ServerSecurity("127.0.0.1", 9847)
        self.monitor = MonitorService("127.0.0.1")
        self.app = create_app(self.monitor, self.security)
        self.origin = "http://127.0.0.1:9847"

    def test_shutdown_requires_token(self) -> None:
        with TestClient(self.app) as client:
            response = client.post("/api/shutdown")
            self.assertEqual(response.status_code, 403)

    def test_shutdown_rejects_non_loopback_even_with_token(self) -> None:
        with TestClient(self.app) as client:
            response = client.post(
                "/api/shutdown",
                headers={"X-GMS-Token": self.security.token},
            )
            self.assertEqual(response.status_code, 403)
            self.assertIn("loopback", response.json()["detail"].lower())

    def test_shutdown_accepts_valid_token_from_loopback(self) -> None:
        with patch.object(self.security, "verify_loopback_peer", return_value=True):
            with TestClient(self.app) as client:
                response = client.post(
                    "/api/shutdown",
                    headers={"X-GMS-Token": self.security.token},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "stopping")

    def test_websocket_rejects_missing_token(self) -> None:
        with TestClient(self.app) as client:
            with self.assertRaises(Exception):
                with client.websocket_connect("/ws", headers={"Origin": self.origin}):
                    pass

    def test_websocket_rejects_bad_origin(self) -> None:
        with TestClient(self.app) as client:
            with self.assertRaises(Exception):
                with client.websocket_connect(
                    "/ws",
                    headers=_ws_headers("http://evil.example", self.security.token),
                ):
                    pass

    def test_websocket_accepts_authorized_client(self) -> None:
        with TestClient(self.app) as client:
            with client.websocket_connect(
                "/ws",
                headers=_ws_headers(self.origin, self.security.token),
            ) as ws:
                payload = ws.receive_json()
                self.assertEqual(payload["host"], "127.0.0.1")
                self.assertIn("quality_code", payload)
                self.assertNotIn("stormshield", payload)
                self.assertIsNone(payload["sns"]["active_host"])
                self.assertEqual(payload["sns"]["saved_hosts"], [])

    def test_websocket_enforces_client_limit(self) -> None:
        limited = ServerSecurity("127.0.0.1", 9847, max_ws_clients=1)
        app = create_app(self.monitor, limited)
        with TestClient(app) as client:
            with client.websocket_connect(
                "/ws",
                headers=_ws_headers(self.origin, limited.token),
            ):
                with self.assertRaises(Exception):
                    with client.websocket_connect(
                        "/ws",
                        headers=_ws_headers(self.origin, limited.token),
                    ):
                        pass


if __name__ == "__main__":
    unittest.main()
