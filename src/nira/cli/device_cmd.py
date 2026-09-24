"""``nira device`` — pair, inspect and revoke the clients that may reach Nira."""

from __future__ import annotations

import json

import click
from rich.console import Console
from rich.table import Table

from nira.core.paths import get_config_dir
from nira.devices import DeviceStore
from nira.devices.store import ALL_SCOPES, DEFAULT_SCOPES, normalize_scopes


def _store() -> DeviceStore:
    return DeviceStore(get_config_dir() / "devices.db")


def _pairing_target(port: int):
    """The URL for the pairing payload, and the candidate it came from.

    A phone needs somewhere to send the enrollment token. This used to resolve
    Tailscale or fall back to ``http://localhost`` — which in a QR code is the
    phone talking to itself, so pairing could not work and nothing said why.
    The resolver now covers tailnet, LAN and an address the user pinned
    themselves, and reports which one it picked so the caller can say what it
    costs (see ``nira.server.advertise``).
    """
    from nira.core.config import load_config
    from nira.server.advertise import resolve_advertise_url

    return resolve_advertise_url(load_config(), port)


def _render_qr(payload: str, console: Console) -> bool:
    """Draw *payload* as a QR code, if a renderer is available."""
    try:
        import qrcode  # type: ignore[import-not-found]
    except ImportError:
        return False
    code = qrcode.QRCode(border=1)
    code.add_data(payload)
    code.make(fit=True)
    code.print_ascii(out=console.file, invert=True)
    return True


@click.group()
def device() -> None:
    """Manage the devices paired with this Nira.

    Each paired device gets its own key rather than sharing the machine's, so
    a phone can be revoked without cutting off everything else, and the audit
    trail can say which device did what.
    """


@device.command("pair")
@click.argument("name")
@click.option("--port", default=8000, show_default=True, help="Port Nira serves on.")
@click.option(
    "--scope",
    "scopes",
    multiple=True,
    type=click.Choice(ALL_SCOPES),
    help=f"Repeatable. Default: {', '.join(DEFAULT_SCOPES)}.",
)
def pair_device(name: str, port: int, scopes: tuple[str, ...]) -> None:
    """Start pairing a device called NAME.

    Prints a short-lived, single-use invitation for the device to redeem. It
    expires in ten minutes because it is briefly visible on screen.
    """
    console = Console()

    # Resolve the address first: an enrollment token is single-use and expires
    # in ten minutes, so burning one before discovering there is no reachable
    # address would cost the user a token and tell them nothing.
    try:
        url, candidate = _pairing_target(port)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        console.print("[dim]See `nira network status` for what is available.[/dim]")
        raise SystemExit(1) from exc

    store = _store()
    try:
        store.purge_expired_enrollments()
        enrollment = store.create_enrollment(
            name, scopes=list(scopes) if scopes else None
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
    finally:
        store.close()

    payload = json.dumps(
        {"url": url, "token": enrollment.token, "name": name},
        separators=(",", ":"),
    )

    console.print(
        f"Pairing [bold]{name}[/bold] — scopes: {', '.join(enrollment.scopes)}"
    )
    console.print()
    if not _render_qr(payload, console):
        console.print("[dim](install `qrcode` to show a scannable code)[/dim]")
    console.print()
    console.print(f"  URL   {url}")
    console.print(f"  Token {enrollment.token}")
    console.print()
    console.print("[dim]Single use, expires in 10 minutes.[/dim]")

    if not candidate.reachable_off_machine:
        console.print()
        console.print(
            "[red]This address points at this machine only[/red] — the device "
            "you are pairing cannot reach it. No tailnet and no local network "
            "address was found. Set one yourself:"
        )
        console.print("    [bold]nira network set --host <address>[/bold]")
        console.print("[dim]Or see `nira network status` for the options.[/dim]")
    elif not candidate.stable:
        console.print()
        console.print(f"[yellow]{candidate.note}[/yellow]")

    if not candidate.secure_context:
        console.print()
        console.print(
            "[yellow]This is a plain http:// address.[/yellow] A browser treats "
            "it as an insecure context, so the web app cannot install as a PWA "
            "or work offline there. To get a real certificate for this "
            "machine's tailnet name:"
        )
        console.print(f"    [bold]tailscale serve --bg {port}[/bold]")
        console.print(
            "[dim]Then pair again — the QR will carry the https address.[/dim]"
        )


@device.command("list")
@click.option("--all", "include_revoked", is_flag=True, help="Include revoked devices.")
def list_devices(include_revoked: bool) -> None:
    """Show paired devices."""
    console = Console()
    store = _store()
    try:
        devices = store.list(include_revoked=include_revoked)
    finally:
        store.close()

    if not devices:
        console.print("[dim]No devices paired. Pair one with: nira device pair[/dim]")
        return

    table = Table(title="Devices")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Platform")
    table.add_column("Scopes")
    table.add_column("Last seen")
    for entry in devices:
        label = f"[strike]{entry.name}[/strike]" if entry.revoked else entry.name
        table.add_row(
            entry.id,
            label,
            entry.platform,
            ", ".join(entry.scopes) or "[dim]none[/dim]",
            entry.last_seen_at or "[dim]never[/dim]",
        )
    console.print(table)


@device.command("revoke")
@click.argument("device_id")
def revoke_device(device_id: str) -> None:
    """Revoke a device's key immediately."""
    console = Console()
    store = _store()
    try:
        revoked = store.revoke(device_id)
    finally:
        store.close()

    if revoked:
        console.print(f"Revoked [bold]{device_id}[/bold]")
    else:
        console.print(f"[yellow]No active device with id {device_id!r}[/yellow]")
        raise SystemExit(1)


@device.command("scopes")
@click.argument("device_id")
@click.argument("scopes", nargs=-1, required=True)
def set_device_scopes(device_id: str, scopes: tuple[str, ...]) -> None:
    """Replace what DEVICE_ID is allowed to do."""
    console = Console()
    store = _store()
    try:
        granted = normalize_scopes(list(scopes))
        updated = store.set_scopes(device_id, granted)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
    finally:
        store.close()

    if updated:
        console.print(f"{device_id} -> {', '.join(granted) or 'no scopes'}")
    else:
        console.print(f"[yellow]No active device with id {device_id!r}[/yellow]")
        raise SystemExit(1)


__all__ = ["device"]
