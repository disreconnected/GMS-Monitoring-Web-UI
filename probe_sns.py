#!/usr/bin/env python3
"""Read-only diagnostic probe for a Stormshield SNS firewall.

Connects with stormshield.sns.sslclient and runs three read-only commands
(SYSTEM PROPERTY, MONITOR INTERFACE, MONITOR HOST iface=<name>), printing each
raw reply. MONITOR HOST is always filtered to one LAN interface (--host-iface,
default CoreSwitch): an unfiltered query never returns on busy firewalls and
WAN interfaces hang. No MODIFY or other write command is ever sent. TLS
certificate checks are disabled (sslverifypeer/sslverifyhost=False).

The password is read only from the GMS_SNS_PASSWORD environment variable.
Set it in the shell, then run:

    set GMS_SNS_PASSWORD=...          (cmd)
    $env:GMS_SNS_PASSWORD = "..."     (PowerShell)
    py -3.13 probe_sns.py --host 10.5.1.1
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from stormshield.sns.sslclient import SSLClient

COMMANDS = ["SYSTEM PROPERTY", "MONITOR INTERFACE"]
HOST_MAX_LINES = 40


def scrub(text: object) -> str:
    """Hide API session ids that requests exceptions embed in URLs."""
    return re.sub(r"sessionid=[^&\s'\"]+", "sessionid=***", str(text))


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only SNS diagnostic probe.")
    parser.add_argument("--host", required=True, help="firewall address, e.g. 10.5.1.1")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--user", default="gmsmonitoring")
    parser.add_argument("--timeout", type=float, default=15, help="seconds")
    parser.add_argument(
        "--host-iface",
        default="CoreSwitch",
        help="LAN interface name for MONITOR HOST iface=<name> (default CoreSwitch)",
    )
    args = parser.parse_args()

    password = os.environ.get("GMS_SNS_PASSWORD", "")
    if not password:
        print("error: GMS_SNS_PASSWORD is not set; set it in this shell and rerun", file=sys.stderr)
        return 2

    try:
        client = SSLClient(
            host=args.host,
            port=args.port,
            user=args.user,
            password=password,
            sslverifypeer=False,
            sslverifyhost=False,
            timeout=args.timeout,
        )
    except Exception as exc:  # noqa: BLE001 - report any connect or auth failure
        print(f"error: connect to {args.host}:{args.port} failed: {scrub(repr(exc))}", file=sys.stderr)
        return 1

    try:
        commands = COMMANDS + [f"MONITOR HOST iface={args.host_iface}"]
        for command in commands:
            try:
                resp = client.send_command(command)
                lines = (resp.output or "").splitlines()
                limit = HOST_MAX_LINES if command.startswith("MONITOR HOST") else len(lines)
                print(
                    f"=== {command} === ret={resp.ret} code={resp.code} "
                    f"msg={resp.msg} format={resp.format}"
                )
                print("\n".join(lines[:limit]))
                if len(lines) > limit:
                    print(f"... ({len(lines) - limit} more lines)")
            except Exception as exc:  # noqa: BLE001 - keep probing the remaining commands
                print(f"=== {command} === EXCEPTION {scrub(repr(exc))}")
    finally:
        client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
