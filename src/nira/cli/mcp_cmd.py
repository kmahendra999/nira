"""``nira mcp`` — expose Nira's tools to MCP clients."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click


@click.group()
def mcp() -> None:
    """Serve Nira's tools over the Model Context Protocol.

    Nira has always been an MCP *client*, consuming tools from other servers.
    This is the other direction: letting a client such as Claude Desktop use
    Nira's own tools, memory and connectors.
    """


@mcp.command("serve")
def serve_mcp() -> None:
    """Serve on stdio (the transport desktop MCP clients launch).

    Speaks newline-delimited JSON-RPC on stdin/stdout. Run it by hand only to
    check that it starts; normally a client spawns it. Nothing may be printed
    to stdout but protocol — see `nira mcp install` for the client config.
    """
    from nira.mcp.stdio import main

    raise SystemExit(main())


@mcp.command("install")
@click.option(
    "--print-only",
    is_flag=True,
    default=False,
    help="Show the config block instead of writing it.",
)
def install_mcp(print_only: bool) -> None:
    """Print the JSON to add Nira to an MCP client's config.

    Deliberately does not edit the file. A client's config holds every other
    server the user has connected, and silently rewriting it is a poor trade
    for saving one copy and paste.
    """
    console_entry = {
        "mcpServers": {
            "nira": {
                "command": sys.executable,
                "args": ["-m", "nira.mcp.stdio"],
            }
        }
    }
    click.echo(json.dumps(console_entry, indent=2))
    click.echo("", err=True)
    click.echo("Add the block above to your MCP client's config file.", err=True)
    click.echo(f"Claude Desktop (macOS): {_claude_desktop_config()}", err=True)
    click.echo("Then restart the client.", err=True)


def _claude_desktop_config() -> str:
    """Best-effort path to Claude Desktop's config, for the hint above."""
    import platform

    system = platform.system()
    if system == "Darwin":
        return str(
            Path.home()
            / "Library/Application Support/Claude/claude_desktop_config.json"
        )
    if system == "Windows":
        return r"%APPDATA%\Claude\claude_desktop_config.json"
    return str(Path.home() / ".config/Claude/claude_desktop_config.json")


__all__ = ["mcp"]
