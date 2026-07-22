"""Pretty local hostname: register paper-review.local via mDNS (macOS dns-sd).

Advertises the LAN IP when available (so phones on the same Wi-Fi resolve it
too — the server binds 0.0.0.0), else 127.0.0.1. Best effort: returns None on
non-mac / missing dns-sd; the caller keeps working with plain IP URLs.
"""

from __future__ import annotations

import socket
import subprocess
import sys

HOSTNAME = "paper-review.local"


def lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # no packet sent — just picks the route
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def start_mdns_proxy() -> subprocess.Popen | None:
    """Spawn `dns-sd -P` advertising paper-review.local. Caller terminates it."""
    if sys.platform != "darwin":
        return None
    ip = lan_ip() or "127.0.0.1"
    try:
        return subprocess.Popen(
            ["dns-sd", "-P", "paper-review", "_http._tcp", "local", "80",
             HOSTNAME, ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
