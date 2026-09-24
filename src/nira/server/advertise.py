"""Deciding which address to hand this machine's other devices.

Pairing a phone needs an address the *phone* can reach. That was resolved one
way — Tailscale, or ``http://localhost:8000`` — and localhost in a QR code is
the phone talking to itself: pairing could not work and nothing on screen said
why.

Networks differ, so this module offers the candidates and lets the person
choose. It ranks them by how long the address keeps working:

1. ``tailscale serve`` https origin — a real certificate, so the PWA installs,
   and it follows the machine between networks.
2. Tailnet MagicDNS name — follows the machine, but plain http.
3. Tailnet IPv4 — same, minus the stable name.
4. LAN address — works on this network and stops at its edge. A DHCP lease
   also changes, so this is offered with that said out loud.
5. localhost — this machine only. Listed last, and marked as unreachable from
   anywhere else, because presenting it as a pairing address is the bug.

Nothing here authenticates anyone; reaching the port still proves nothing
about who is knocking. Per-device keys remain mandatory (see ``nira.devices``).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass, field
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "AdvertiseCandidate",
    "MODES",
    "candidates",
    "lan_address",
    "resolve_advertise_url",
    "resolve_bind_host",
]

MODES = ("auto", "tailscale", "lan", "manual")


@dataclass
class AdvertiseCandidate:
    """One address this machine could hand out, and what it costs the user."""

    kind: str  # "tailscale-serve" | "tailnet-dns" | "tailnet-ip" | "lan" | "loopback"
    host: str
    scheme: str = "http"
    # Whether a device other than this one can reach it at all.
    reachable_off_machine: bool = True
    # Whether a browser will treat it as a secure context — no service worker,
    # so no installable PWA and no offline, without one.
    secure_context: bool = False
    # Whether it keeps working when this machine changes networks.
    stable: bool = False
    note: str = ""
    port_from_server: bool = True
    _explicit_port: Optional[int] = field(default=None, repr=False)

    def url(self, port: int) -> str:
        """The address to hand out, with *port* unless this one carries its own."""
        if self._explicit_port is not None:
            port = self._explicit_port
        # `tailscale serve` fronts 443, so naming a port would send the device
        # past the TLS terminator to a port that is not listening.
        if not self.port_from_server:
            return f"{self.scheme}://{self.host}"
        return f"{self.scheme}://{self.host}:{port}"


def lan_address() -> Optional[str]:
    """This machine's address on the network it is currently attached to.

    Asks the routing table which source address would be used to reach a
    public IP, by opening a UDP socket — which sends nothing, it just makes
    the kernel pick a route. That is the only reliable way to choose among
    several interfaces; ``gethostbyname(gethostname())`` famously answers
    ``127.0.1.1`` on Debian and a stale interface on a multi-homed machine.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.settimeout(0.5)
        # 192.0.2.0/24 is TEST-NET-1 (RFC 5737): reserved for documentation
        # and guaranteed never routed, so nothing is contacted even if the
        # kernel were to send. Any address works for route selection.
        probe.connect(("192.0.2.1", 9))
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()

    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return None
    if parsed.is_loopback or parsed.is_unspecified:
        return None
    return address


def _tailnet_candidates(timeout: float = 5.0) -> List[AdvertiseCandidate]:
    from nira.server.tailnet import get_identity, https_serve_target

    found: List[AdvertiseCandidate] = []

    secure = https_serve_target(timeout=timeout)
    if secure:
        host = secure.split("://", 1)[-1]
        found.append(
            AdvertiseCandidate(
                kind="tailscale-serve",
                host=host,
                scheme="https",
                secure_context=True,
                stable=True,
                port_from_server=False,
                note=(
                    "Real certificate via `tailscale serve` — the web app "
                    "can install as a PWA."
                ),
            )
        )

    identity = get_identity(timeout=timeout)
    if identity is not None:
        if identity.dns_name:
            found.append(
                AdvertiseCandidate(
                    kind="tailnet-dns",
                    host=identity.dns_name,
                    stable=True,
                    note=(
                        "Follows this machine between networks. Plain http, "
                        "so no PWA install."
                    ),
                )
            )
        if identity.ipv4:
            found.append(
                AdvertiseCandidate(
                    kind="tailnet-ip",
                    host=identity.ipv4,
                    stable=True,
                    note="Tailnet IP. Works anywhere on the tailnet.",
                )
            )
    return found


def candidates(timeout: float = 5.0) -> List[AdvertiseCandidate]:
    """Every address this machine could advertise, best first."""
    found = _tailnet_candidates(timeout=timeout)

    lan = lan_address()
    if lan:
        found.append(
            AdvertiseCandidate(
                kind="lan",
                host=lan,
                note=(
                    "Reachable from this network only, and the address can "
                    "change when the DHCP lease renews."
                ),
            )
        )

    found.append(
        AdvertiseCandidate(
            kind="loopback",
            host="127.0.0.1",
            reachable_off_machine=False,
            secure_context=True,  # browsers treat loopback as secure
            note="This machine only — another device cannot reach it.",
        )
    )
    return found


def _manual_candidate(config: Any) -> AdvertiseCandidate:
    host = str(config.network.advertise_host or "").strip()
    scheme = str(config.network.advertise_scheme or "").strip() or "http"
    port = int(config.network.advertise_port or 0)
    return AdvertiseCandidate(
        kind="manual",
        host=host,
        scheme=scheme,
        secure_context=scheme == "https",
        stable=True,
        note="Set by you in [network] advertise_host.",
        _explicit_port=port or None,
    )


def resolve_advertise_url(
    config: Any,
    port: int,
    *,
    timeout: float = 5.0,
) -> tuple[str, AdvertiseCandidate]:
    """Return the URL to hand a device, and the candidate it came from.

    Raises ``ValueError`` when the configured mode cannot be satisfied —
    ``manual`` with no host, or ``tailscale`` on a machine that is not on a
    tailnet. Falling back silently is what produced a QR code pointing at
    localhost; a caller that wants a fallback should ask for ``auto``.
    """
    mode = str(getattr(config.network, "mode", "auto") or "auto").strip().lower()
    if mode not in MODES:
        raise ValueError(
            f"Unknown network mode {mode!r}. Use one of: {', '.join(MODES)}"
        )

    if mode == "manual":
        chosen = _manual_candidate(config)
        if not chosen.host:
            raise ValueError(
                "[network] mode is 'manual' but advertise_host is empty. "
                "Set the address this machine should hand out, e.g. "
                "`nira network set --host 192.168.1.20`."
            )
        return chosen.url(port), chosen

    available = candidates(timeout=timeout)

    if mode == "tailscale":
        for candidate in available:
            if candidate.kind.startswith("tailscale") or candidate.kind.startswith(
                "tailnet"
            ):
                return candidate.url(port), candidate
        raise ValueError(
            "[network] mode is 'tailscale' but this machine is not on a "
            "tailnet. Is tailscaled running and logged in? (`tailscale status`)"
        )

    if mode == "lan":
        for candidate in available:
            if candidate.kind == "lan":
                return candidate.url(port), candidate
        raise ValueError(
            "[network] mode is 'lan' but no local network address was found."
        )

    # auto: the ranking in `candidates` is the preference order, and the
    # loopback entry at the end means this cannot raise.
    chosen = available[0]
    return chosen.url(port), chosen


def resolve_bind_host(config: Any, *, timeout: float = 5.0) -> str:
    """The interface to listen on so the advertised address actually answers.

    An address is only useful if something is listening on the interface it
    names. The default 127.0.0.1 bind means a correct tailnet URL in the QR
    code still refuses the connection.
    """
    explicit = str(getattr(config.network, "bind_host", "") or "").strip()
    if explicit:
        return explicit

    mode = str(getattr(config.network, "mode", "auto") or "auto").strip().lower()
    if mode == "auto":
        # Do not widen the bind on the strength of a guess: "auto" is the
        # default, and a default must not start listening on a cafe's wifi.
        return str(config.server.host)

    if mode == "tailscale":
        from nira.server.tailnet import get_identity

        identity = get_identity(timeout=timeout)
        if identity is not None and identity.ipv4:
            return identity.ipv4
        raise ValueError(
            "[network] mode is 'tailscale' but no tailnet address was found "
            "to bind to. (`tailscale status`)"
        )

    if mode == "lan":
        lan = lan_address()
        if lan:
            return lan
        raise ValueError("[network] mode is 'lan' but no LAN address was found.")

    # manual: the advertised host may be a name this machine cannot bind, so
    # bind it only when it is one of our own addresses.
    host = str(config.network.advertise_host or "").strip()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return str(config.server.host)
    return host if host in _own_addresses() else str(config.server.host)


def _own_addresses() -> set[str]:
    addresses = {"127.0.0.1"}
    lan = lan_address()
    if lan:
        addresses.add(lan)
    try:
        from nira.server.tailnet import get_identity

        identity = get_identity()
        if identity is not None and identity.ipv4:
            addresses.add(identity.ipv4)
    except Exception:  # pragma: no cover - tailscale absent
        logger.debug("tailnet lookup failed while listing own addresses")
    return addresses
