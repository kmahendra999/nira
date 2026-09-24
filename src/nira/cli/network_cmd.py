"""``nira network`` — choose the address this machine hands its other devices.

Everyone's network is different: some people have a tailnet, some have a
router with a reserved lease, some have neither and a hostname that only
their LAN resolves. This command shows what is actually available on *this*
machine and lets the person pin the one they want, so pairing a phone stops
depending on a detector guessing right.
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from nira.core.config import load_config
from nira.server.advertise import MODES, candidates, resolve_advertise_url


def _console() -> Console:
    return Console()


@click.group()
def network() -> None:
    """Inspect and set how this machine is reachable from your other devices."""


@network.command("status")
@click.option("--port", default=0, help="Port to show in the URLs (default: config).")
def network_status(port: int) -> None:
    """Show every address this machine could advertise, and the one in use."""
    console = _console()
    config = load_config()
    port = port or config.server.port

    table = Table(title="Addresses this machine could advertise")
    table.add_column("Source")
    table.add_column("URL")
    table.add_column("Reachable")
    table.add_column("Stable")
    table.add_column("PWA")

    def mark(value: bool) -> str:
        return "[green]yes[/green]" if value else "[yellow]no[/yellow]"

    found = candidates()
    for candidate in found:
        table.add_row(
            candidate.kind,
            candidate.url(port),
            mark(candidate.reachable_off_machine),
            mark(candidate.stable),
            mark(candidate.secure_context),
        )
    console.print(table)
    console.print(
        "[dim]Reachable = another device can reach it. "
        "Stable = survives changing networks. "
        "PWA = a browser will install the web app from it.[/dim]"
    )
    console.print()

    console.print(f"Mode: [bold]{config.network.mode}[/bold]")
    if config.network.advertise_host:
        console.print(f"Pinned host: [bold]{config.network.advertise_host}[/bold]")

    try:
        url, chosen = resolve_advertise_url(config, port)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc

    console.print(f"In use: [cyan]{url}[/cyan]  [dim]({chosen.kind})[/dim]")
    if chosen.note:
        console.print(f"[dim]{chosen.note}[/dim]")
    if not chosen.reachable_off_machine:
        console.print(
            "[red]No other device can reach this address.[/red] "
            "Set one with `nira network set --host <address>`."
        )


@network.command("set")
@click.option(
    "--mode",
    type=click.Choice(MODES),
    default=None,
    help="auto (prefer tailnet, then LAN), tailscale, lan, or manual.",
)
@click.option("--host", default=None, help="Exact address to advertise (sets manual).")
@click.option(
    "--port", type=int, default=None, help="Port to advertise, if not the server's."
)
@click.option(
    "--scheme",
    type=click.Choice(["http", "https"]),
    default=None,
    help="Scheme to advertise. Use https only when something terminates TLS.",
)
@click.option(
    "--bind",
    default=None,
    help="Interface to listen on, when it differs from the advertised address.",
)
def network_set(
    mode: str | None,
    host: str | None,
    port: int | None,
    scheme: str | None,
    bind: str | None,
) -> None:
    """Write network settings to config.toml."""
    console = _console()
    from nira.core.config_writer import update_config_section

    values: dict[str, object] = {}
    if host is not None:
        values["advertise_host"] = host
        # Naming a host and leaving the mode on "auto" would save the setting
        # and then ignore it, which is the class of bug this command exists to
        # end. Choosing --host is choosing manual unless told otherwise.
        if mode is None:
            mode = "manual"
    if mode is not None:
        values["mode"] = mode
    if port is not None:
        values["advertise_port"] = port
    if scheme is not None:
        values["advertise_scheme"] = scheme
    if bind is not None:
        values["bind_host"] = bind

    if not values:
        console.print(
            "[yellow]Nothing to change.[/yellow] See `nira network set --help`."
        )
        raise SystemExit(1)

    if values.get("mode") == "manual" and not (
        host or load_config().network.advertise_host
    ):
        console.print("[red]mode 'manual' needs an address.[/red] Pass --host too.")
        raise SystemExit(1)

    path = update_config_section("network", values)
    console.print(f"Wrote {path}")
    for key, value in values.items():
        console.print(f"  {key} = {value!r}")

    # Show the result rather than asserting it worked.
    config = load_config()
    try:
        url, chosen = resolve_advertise_url(config, config.server.port)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
    console.print(
        f"Devices will be given: [cyan]{url}[/cyan] [dim]({chosen.kind})[/dim]"
    )
    console.print(
        "[dim]Restart `nira serve` for the bind address to take effect.[/dim]"
    )


@network.command("reset")
def network_reset() -> None:
    """Go back to automatic detection."""
    console = _console()
    from nira.core.config_writer import update_config_section

    update_config_section(
        "network",
        {
            "mode": "auto",
            "advertise_host": None,
            "advertise_port": None,
            "advertise_scheme": None,
            "bind_host": None,
        },
    )
    console.print("Network settings reset to automatic detection.")


__all__ = ["network"]
