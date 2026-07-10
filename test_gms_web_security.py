#!/usr/bin/env python3
"""Security tests for gms_web_server."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from fastapi.testclient import TestClient  # noqa: E402

from gms_web_server import (  # noqa: E402
    MonitorService,
    ServerSecurity,
    VALID_WS_ACTIONS,
    WS_APP_PROTOCOL,
    WS_TOKEN_PREFIX,
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
        security = ServerSecurity("127.0.0.1", 8765)
        self.assertGreater(len(security.token), 20)
        self.assertIn("#token=", security.dashboard_url())

    def test_remote_mode_requires_access_token(self) -> None:
        with self.assertRaises(SystemExit):
            ServerSecurity("0.0.0.0", 8765, allow_remote=True, access_token=None)
        with self.assertRaises(SystemExit):
            ServerSecurity("0.0.0.0", 8765, allow_remote=True, access_token="short")

    def test_remote_mode_omits_token_from_url(self) -> None:
        security = ServerSecurity(
            "0.0.0.0",
            8765,
            allow_remote=True,
            access_token="a" * 16,
        )
        self.assertNotIn("#token=", security.dashboard_url())

    def test_token_verification(self) -> None:
        security = ServerSecurity("127.0.0.1", 8765)
        self.assertTrue(security.verify_token(security.token))
        self.assertFalse(security.verify_token("wrong-token"))
        self.assertFalse(security.verify_token(None))

    def test_origin_validation(self) -> None:
        security = ServerSecurity(
            "127.0.0.1",
            8765,
            allowed_origins=["http://localhost:5173"],
        )
        self.assertTrue(security.verify_origin("http://127.0.0.1:8765"))
        self.assertTrue(security.verify_origin("http://localhost:5173"))
        self.assertTrue(security.verify_origin(None, "127.0.0.1"))
        self.assertFalse(security.verify_origin("http://evil.example"))
        self.assertFalse(security.verify_origin(None))
        self.assertFalse(security.verify_origin(None, "192.168.1.1"))

    def test_remote_mode_rejects_missing_origin(self) -> None:
        security = ServerSecurity(
            "0.0.0.0",
            8765,
            allow_remote=True,
            access_token="a" * 16,
        )
        self.assertFalse(security.verify_origin(None, "127.0.0.1"))

    def test_ws_client_limit(self) -> None:
        security = ServerSecurity("127.0.0.1", 8765, max_ws_clients=1)
        self.assertTrue(security.try_acquire_ws_slot())
        self.assertFalse(security.try_acquire_ws_slot())
        security.release_ws_slot()
        self.assertTrue(security.try_acquire_ws_slot())
        security.release_ws_slot()

    def test_traceroute_throttle(self) -> None:
        security = ServerSecurity("127.0.0.1", 8765, traceroute_cooldown=60.0)
        self.assertTrue(security.can_trigger_traceroute())
        self.assertFalse(security.can_trigger_traceroute())


class HandleWsActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.monitor = MonitorService("127.0.0.1")
        self.security = ServerSecurity("127.0.0.1", 8765)

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


class ApiSecurityIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.security = ServerSecurity("127.0.0.1", 8765)
        self.monitor = MonitorService("127.0.0.1")
        self.app = create_app(self.monitor, self.security)
        self.origin = "http://127.0.0.1:8765"

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

    def test_websocket_enforces_client_limit(self) -> None:
        limited = ServerSecurity("127.0.0.1", 8765, max_ws_clients=1)
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
