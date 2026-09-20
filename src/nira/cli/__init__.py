"""Command-line interface for Nira (Click-based)."""

from __future__ import annotations

import sys

import click

import nira
from nira.cli.scan_cmd import scan


def _invoked_command(argv: list[str]) -> str:
    """Return the first positional CLI token after global flags."""
    for arg in argv:
        if arg.startswith("-"):
            continue
        return arg
    return ""


# A data-boundary scan must be able to diagnose an invalid NIRA_HOME.
# Importing the rest of the CLI eagerly would import core.config and resolve that
# path before the scan can turn the failure into a finding.
_DATA_BOUNDARY_BOOTSTRAP = (
    _invoked_command(sys.argv[1:]) == "scan" and "--data-boundaries" in sys.argv[1:]
)


def _should_skip_update_check(ctx: click.Context, argv: list[str]) -> bool:
    """Return true for commands whose diagnostics should remain local-only."""
    if "--research" in argv:
        return True
    return ctx.invoked_subcommand == "scan" and "--data-boundaries" in argv


@click.group(
    help="Nira — modular AI assistant backend",
    invoke_without_command=True,
)
@click.version_option(version=nira.__version__, prog_name="nira")
@click.option("--verbose", is_flag=True, default=False, help="Enable debug logging")
@click.option("--quiet", is_flag=True, default=False, help="Suppress non-error output")
@click.option(
    "--pick-model",
    "pick_model_bare",
    is_flag=True,
    default=False,
    help=(
        "Bare ``nira``: force interactive model list (overrides NIRA_SKIP_MODEL_PICK)."
    ),
)
@click.pass_context
def cli(ctx: click.Context, verbose: bool, quiet: bool, pick_model_bare: bool) -> None:
    """Top-level CLI group."""
    from nira.cli.log_config import setup_logging

    # Adopt a pre-rename ``~/.openjarvis`` root before anything can read or
    # create config. Runs ahead of setup_logging because logging itself writes
    # under the home directory — migrating after that would strand the log file
    # in a directory we are about to move. No-ops on every run but the first.
    from nira.core.paths import migrate_legacy_home

    _migrated = migrate_legacy_home()
    if _migrated is not None and not quiet:
        click.echo(
            f"Copied your OpenJarvis settings and data to {_migrated}\n"
            "Your previous OpenJarvis install was left in place and still works.",
            err=True,
        )

    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    ctx.obj["pick_model_bare"] = pick_model_bare
    setup_logging(verbose=verbose, quiet=quiet)

    # Check for updates on interactive commands. The banner is noise in
    # demo recordings of ``nira ask --research``, so skip it whenever
    # the research flag is in argv (cheap argv sniff — Click hasn't
    # parsed the subcommand's args yet at this point). Also skip
    # ``nira scan --data-boundaries`` because it is intended to be a
    # local application-data diagnostic with no outbound calls.
    import sys

    skip_update_check = _should_skip_update_check(ctx, sys.argv[1:])
    if not quiet and ctx.invoked_subcommand and not skip_update_check:
        import threading

        from nira.cli._version_check import check_for_updates

        # Run the PyPI version poll off the hot path: on a cache miss it does
        # a blocking urlopen (up to 3s) that otherwise delays every command,
        # notably `nira serve` startup (#263). It's best-effort and never
        # raises, and the nudge prints to stderr, so a daemon thread is safe —
        # for long-lived commands (serve) it finishes; for short commands that
        # exit first, the check is simply skipped this run (same as a miss).
        threading.Thread(
            target=check_for_updates,
            args=(ctx.invoked_subcommand,),
            daemon=True,
        ).start()

    # First-run guard — routes bare `nira` to chat or init.
    if ctx.invoked_subcommand is None:
        from nira.cli._first_run import check_and_route

        check_and_route(ctx)


cli.add_command(scan, "scan")
if not _DATA_BOUNDARY_BOOTSTRAP:
    from nira.cli._bootstrap import bootstrap_cmd
    from nira.cli.add_cmd import add
    from nira.cli.agent_cmd import agent
    from nira.cli.ask import ask
    from nira.cli.bench_cmd import bench
    from nira.cli.channel_cmd import channel
    from nira.cli.channels_cmd import channels
    from nira.cli.chat_cmd import chat, talk
    from nira.cli.compose_cmd import compose
    from nira.cli.config_cmd import config
    from nira.cli.connect_cmd import connect
    from nira.cli.daemon_cmd import restart, start, status, stop
    from nira.cli.digest_cmd import digest
    from nira.cli.doctor_cmd import doctor
    from nira.cli.eval_cmd import eval_group
    from nira.cli.feedback_cmd import feedback_group
    from nira.cli.gateway_cmd import gateway
    from nira.cli.host_cmd import host
    from nira.cli.init_cmd import init
    from nira.cli.memory_cmd import memory
    from nira.cli.mine_cmd import mine
    from nira.cli.model import model
    from nira.cli.operators_cmd import operators
    from nira.cli.optimize_cmd import optimize_group
    from nira.cli.pearl_cmd import pearl
    from nira.cli.project_cmd import project
    from nira.cli.quickstart_cmd import quickstart
    from nira.cli.registry_cmd import registry
    from nira.cli.scheduler_cmd import scheduler
    from nira.cli.self_update_cmd import self_update
    from nira.cli.serve import serve
    from nira.cli.skill_cmd import skill
    from nira.cli.telemetry_cmd import telemetry
    from nira.cli.tool_cmd import tool
    from nira.cli.vault_cmd import vault
    from nira.cli.workflow_cmd import workflow

    cli.add_command(init, "init")
    cli.add_command(ask, "ask")
    cli.add_command(chat, "chat")
    cli.add_command(talk, "talk")
    cli.add_command(serve, "serve")
    cli.add_command(model, "model")
    cli.add_command(memory, "memory")
    cli.add_command(mine, "mine")
    cli.add_command(pearl, "pearl")
    cli.add_command(telemetry, "telemetry")
    cli.add_command(bench, "bench")
    cli.add_command(channel, "channel")
    cli.add_command(channels, "channels")
    cli.add_command(scheduler, "scheduler")
    cli.add_command(doctor, "doctor")
    cli.add_command(agent, "agents")
    cli.add_command(workflow, "workflow")
    cli.add_command(skill, "skill")
    cli.add_command(start, "start")
    cli.add_command(stop, "stop")
    cli.add_command(restart, "restart")
    cli.add_command(status, "status")
    cli.add_command(vault, "vault")
    cli.add_command(add, "add")
    cli.add_command(operators, "operators")
    cli.add_command(eval_group, "eval")
    cli.add_command(host, "host")
    cli.add_command(quickstart, "quickstart")
    cli.add_command(optimize_group, "optimize")
    cli.add_command(feedback_group, "feedback")
    cli.add_command(compose, "compose")
    cli.add_command(gateway, "gateway")
    cli.add_command(tool, "tool")
    cli.add_command(registry, "registry")
    cli.add_command(config, "config")
    cli.add_command(connect, "connect")
    cli.add_command(digest, "digest")
    cli.add_command(project, "project")

    # Deep Research setup pulls the ingestion pipeline (embeddings/numpy). Guard
    # it so an import-time dependency failure cannot take down the whole CLI.
    try:
        from nira.cli.deep_research_setup_cmd import deep_research_setup

        cli.add_command(deep_research_setup, "deep-research-setup")
        cli.add_command(deep_research_setup, "research")
    except Exception as _dr_exc:
        import logging as _logging

        _logging.getLogger(__name__).debug(
            "deep-research command unavailable: %s", _dr_exc
        )
    cli.add_command(self_update, "self-update")
    cli.add_command(bootstrap_cmd, "_bootstrap")

    # Gateway CLI commands (lazy import to avoid pulling starlette)
    try:
        from nira.cli.auth_cmd import auth

        cli.add_command(auth, "auth")
    except ImportError:
        pass

    try:
        from nira.cli.tunnel_cmd import tunnel

        cli.add_command(tunnel, "tunnel")
    except ImportError:
        pass


def main() -> None:
    """Entry point registered as ``nira`` console script."""
    import sys

    if sys.platform == "win32":
        for _stream in (sys.stdout, sys.stderr):
            if hasattr(_stream, "reconfigure"):
                try:
                    _stream.reconfigure(encoding="utf-8", errors="replace")
                except (AttributeError, OSError):
                    pass
    cli()


__all__ = ["cli", "main"]
