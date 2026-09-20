"""``nira project`` — register the codebases Nira can be asked to work on."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from nira.core.paths import get_config_dir
from nira.projects import ProjectStore


def _store() -> ProjectStore:
    return ProjectStore(get_config_dir() / "projects.db")


@click.group()
def project() -> None:
    """Manage the projects Nira can work on.

    Registering a directory is what makes "work on <name>" resolvable: it
    gives the request a path to run in and a session to continue, instead of
    an agent starting cold in whatever directory the server happens to be in.
    """


@project.command("add")
@click.argument("name")
@click.argument("path", type=click.Path(exists=True, file_okay=False), default=".")
@click.option(
    "--agent",
    "default_agent",
    default="claude_code",
    help="Agent used for this project by default.",
)
def add_project(name: str, path: str, default_agent: str) -> None:
    """Register PATH (default: the current directory) as project NAME."""
    console = Console()
    store = _store()
    try:
        registered = store.add(name, path, default_agent=default_agent)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from exc
    finally:
        store.close()

    console.print(
        f"Registered [bold]{registered.name}[/bold] ([dim]{registered.id}[/dim]) "
        f"-> {registered.path}"
    )


@project.command("list")
def list_projects() -> None:
    """Show every registered project."""
    console = Console()
    store = _store()
    try:
        projects = store.list()
    finally:
        store.close()

    if not projects:
        console.print(
            "[dim]No projects registered. Add one with: nira project add[/dim]"
        )
        return

    table = Table(title="Projects")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Path")
    table.add_column("Agent")
    table.add_column("Session")
    for entry in projects:
        # A path that has moved or been deleted is worth seeing at a glance:
        # the failure would otherwise surface inside an agent run.
        location = entry.path if entry.exists else f"[red]{entry.path} (missing)[/red]"
        table.add_row(
            entry.id,
            entry.name,
            location,
            entry.default_agent,
            entry.last_session_id or "[dim]—[/dim]",
        )
    console.print(table)


@project.command("remove")
@click.argument("project_id")
def remove_project(project_id: str) -> None:
    """Forget a project. The directory itself is untouched."""
    console = Console()
    store = _store()
    try:
        removed = store.remove(project_id)
    finally:
        store.close()

    if removed:
        console.print(f"Removed [bold]{project_id}[/bold]")
    else:
        console.print(f"[yellow]No project with id {project_id!r}[/yellow]")
        raise SystemExit(1)


@project.command("show")
@click.argument("reference")
def show_project(reference: str) -> None:
    """Resolve REFERENCE the way a spoken request would."""
    console = Console()
    store = _store()
    try:
        found = store.resolve(reference)
    finally:
        store.close()

    if found is None:
        console.print(
            f"[yellow]Could not resolve {reference!r} to a single project.[/yellow]"
        )
        raise SystemExit(1)

    console.print(f"[bold]{found.name}[/bold] ([dim]{found.id}[/dim])")
    console.print(f"  path    {found.path}")
    console.print(f"  agent   {found.default_agent}")
    console.print(f"  session {found.last_session_id or '—'}")
    if not found.exists:
        console.print("  [red]directory is missing[/red]")


__all__ = ["project"]
