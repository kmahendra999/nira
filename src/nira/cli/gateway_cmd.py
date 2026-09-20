"""``nira gateway start|stop|status|logs`` — multi-channel gateway management."""

from __future__ import annotations

import subprocess
from pathlib import Path

import click


@click.group()
def gateway() -> None:
    """Manage the Nira multi-channel gateway."""


@gateway.command()
@click.option(
    "--install",
    is_flag=True,
    help="Generate and enable systemd/launchd service",
)
def start(install: bool) -> None:
    """Start the gateway daemon."""
    if install:
        import platform as plat

        from nira.daemon.service import (
            generate_launchd_plist,
            generate_systemd_service,
        )

        if plat.system() == "Darwin":
            plist_path = Path.home() / "Library/LaunchAgents/com.nira.gateway.plist"
            generate_launchd_plist(plist_path)
            click.echo(f"Wrote {plist_path}")
            subprocess.run(
                ["launchctl", "load", str(plist_path)],
                check=False,
            )
        else:
            service_path = Path.home() / ".config/systemd/user/nira-gateway.service"
            generate_systemd_service(service_path)
            click.echo(f"Wrote {service_path}")
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                check=False,
            )
            subprocess.run(
                ["systemctl", "--user", "enable", "--now", "nira-gateway"],
                check=False,
            )
    else:
        from nira.daemon.gateway import GatewayDaemon

        click.echo("Starting Nira gateway (foreground)... Press Ctrl+C to stop.")
        daemon = GatewayDaemon()
        try:
            # Blocks. This used to print "Gateway started" and return
            # immediately without starting anything.
            daemon.run_forever()
        except KeyboardInterrupt:
            daemon.stop()
            click.echo("\nGateway stopped.")


@gateway.command()
def stop() -> None:
    """Stop the gateway daemon."""
    import platform as plat

    if plat.system() == "Darwin":
        subprocess.run(
            ["launchctl", "remove", "com.nira.gateway"],
            check=False,
        )
    else:
        subprocess.run(
            ["systemctl", "--user", "stop", "nira-gateway"],
            check=False,
        )
    click.echo("Gateway stopped.")


@gateway.command()
def status() -> None:
    """Check gateway status."""
    import platform as plat

    if plat.system() == "Darwin":
        subprocess.run(
            ["launchctl", "list", "com.nira.gateway"],
            check=False,
        )
    else:
        subprocess.run(
            ["systemctl", "--user", "status", "nira-gateway"],
            check=False,
        )


@gateway.command()
def logs() -> None:
    """View gateway logs."""
    import platform as plat

    if plat.system() == "Darwin":
        click.echo("Check ~/Library/Logs/com.nira.gateway.log")
    else:
        subprocess.run(
            ["journalctl", "--user", "-u", "nira-gateway", "-f"],
            check=False,
        )
