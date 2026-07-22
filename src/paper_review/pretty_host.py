"""Pretty local hostname: register paper-review.local via mDNS (macOS dns-sd).

Deliberately advertises 127.0.0.1 only — the pretty URL is a convenience for
THIS Mac and must not widen network exposure (the loopback address is useless
to other devices). Best effort: returns None on non-mac / missing dns-sd; the
caller keeps working with plain IP URLs.
"""

from __future__ import annotations

import subprocess
import sys

HOSTNAME = "paper-review.local"


def start_mdns_proxy() -> subprocess.Popen | None:
    """Spawn `dns-sd -P` advertising paper-review.local → 127.0.0.1."""
    if sys.platform != "darwin":
        return None
    try:
        return subprocess.Popen(
            ["dns-sd", "-P", "paper-review", "_http._tcp", "local", "80",
             HOSTNAME, "127.0.0.1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
