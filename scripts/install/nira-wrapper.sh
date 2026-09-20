#!/usr/bin/env bash
# nira-wrapper.sh — symlinked to ~/.local/bin/nira.
# Activates the managed venv and execs the real nira CLI.

NIRA_HOME="${NIRA_HOME:-$HOME/.nira}"
VENV="$NIRA_HOME/.venv"

if [[ ! -d "$VENV" ]]; then
    echo "nira: venv not found at $VENV" >&2
    echo "Re-run the installer: curl -fsSL https://nira-ai.github.io/nira/install.sh | bash" >&2
    exit 1
fi

exec "$VENV/bin/nira" "$@"
