"""Resolving this machine's Tailscale address.

For a mesh of personal devices, the tailnet interface is a better bind target
than ``0.0.0.0``. Binding every interface exposes an agent with shell, file and
browser tools to whatever network the laptop is currently on — a cafe, a hotel,
a conference — and the exposure follows the machine around. A tailnet address
is reachable from the user's own devices and from nothing else, and WireGuard
encrypts the hop, which plain HTTP on a LAN does not.

What it does *not* do is authenticate anyone. A tailnet can be shared with
other accounts, so reaching the port still proves nothing about who is
knocking; per-device keys remain mandatory (see ``nira.devices``).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Where Tailscale puts its CLI when the installer does not put it on PATH.
#
# This matters on macOS in particular: the App Store and standalone builds ship
# the binary inside the .app bundle and never touch PATH, so a Mac that is
# happily on a tailnet looks to `shutil.which` exactly like one without
# Tailscale installed. The consequence is not an error message — pairing
# quietly falls back to a LAN address that stops working the moment the laptop
# moves, which is the failure this whole module exists to avoid.
_FALLBACK_PATHS = {
    "darwin": (
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
        "/opt/homebrew/bin/tailscale",
        "/usr/local/bin/tailscale",
    ),
    "win32": (
        r"C:\Program Files\Tailscale\tailscale.exe",
        r"C:\Program Files (x86)\Tailscale\tailscale.exe",
    ),
    "linux": (
        "/usr/bin/tailscale",
        "/usr/local/bin/tailscale",
    ),
}


@dataclass
class TailnetIdentity:
    """This machine's place on the tailnet."""

    ipv4: str
    dns_name: str
    tailnet: str = ""

    @property
    def url(self) -> str:
        """The address to hand a device, preferring the stable name.

        MagicDNS over the raw IP: the name keeps resolving as the machine
        moves between networks, which is exactly the situation a paired phone
        has to survive.
        """
        return f"http://{self.dns_name}" if self.dns_name else f"http://{self.ipv4}"


def tailscale_binary() -> Optional[str]:
    """The tailscale CLI, looked up on PATH and then where installers put it.

    Returns the path so callers invoke the binary they found rather than the
    bare name: a Mac where only the bundled copy exists would otherwise pass
    the availability check and then fail every command.
    """
    override = os.environ.get("NIRA_TAILSCALE_BIN", "").strip()
    if override:
        return override if Path(override).exists() else None

    found = shutil.which("tailscale")
    if found:
        return found

    for candidate in _FALLBACK_PATHS.get(sys.platform, ()):
        if Path(candidate).exists():
            return candidate
    return None


def tailscale_available() -> bool:
    return tailscale_binary() is not None


def get_identity(timeout: float = 5.0) -> Optional[TailnetIdentity]:
    """Return this machine's tailnet identity, or None if unavailable.

    None covers every "not on a tailnet" case — not installed, not logged in,
    daemon down — because the caller's decision is the same for all of them.
    """
    binary = tailscale_binary()
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [binary, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("tailscale status failed: %s", exc)
        return None
    if completed.returncode != 0:
        logger.debug("tailscale status exited %d", completed.returncode)
        return None

    try:
        status = json.loads(completed.stdout)
    except ValueError:
        logger.debug("tailscale status returned unparseable JSON")
        return None

    self_node = status.get("Self") or {}
    addresses = self_node.get("TailscaleIPs") or []
    ipv4 = next((addr for addr in addresses if _is_ipv4(addr)), "")
    if not ipv4:
        return None

    return TailnetIdentity(
        ipv4=ipv4,
        dns_name=(self_node.get("DNSName") or "").rstrip("."),
        tailnet=((status.get("CurrentTailnet") or {}).get("Name") or ""),
    )


def _is_ipv4(address: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(address), ipaddress.IPv4Address)
    except ValueError:
        return False


def https_serve_target(timeout: float = 5.0) -> Optional[str]:
    """Return the https:// origin `tailscale serve` is fronting, if any.

    This is not a nicety. A browser treats a plain ``http://`` MagicDNS origin
    as an insecure context, and an insecure context may not register a service
    worker — so the PWA will not install on a phone and will not work offline,
    however reachable the port is. ``tailscale serve`` terminates TLS with a
    real certificate for the node's ``*.ts.net`` name, which is what turns the
    address into something a phone will actually install from.
    """
    binary = tailscale_binary()
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [binary, "serve", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        config = json.loads(completed.stdout)
    except ValueError:
        return None

    # Keys look like "host.tailnet.ts.net:443".
    for target in config.get("Web") or {}:
        host = str(target).split(":", 1)[0]
        if host:
            return f"https://{host}"
    return None


def is_tailnet_address(host: str) -> bool:
    """Whether *host* is in Tailscale's 100.64.0.0/10 CGNAT range."""
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


__all__ = [
    "tailscale_binary",
    "TailnetIdentity",
    "get_identity",
    "https_serve_target",
    "is_tailnet_address",
    "tailscale_available",
]
