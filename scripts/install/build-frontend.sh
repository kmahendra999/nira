#!/usr/bin/env bash
# build-frontend.sh — build the web UI into the package's static/ directory.
#
# Without this a fresh install has a REST API and no web UI: `nira serve`
# answers /health and /v1/*, and GET / returns 404, because
# src/nira/server/static/ is build output and is not in the repository. The
# quickstart, the install guide and the docs index all end by telling the
# reader to open http://localhost:8000.
#
# Background work, because `npm ci` on this tree takes minutes and nothing
# else in the install depends on it. Skips cleanly when node is absent —
# the CLI is fully usable without a web UI, and refusing to finish an
# install over it would be the wrong trade.
#
# State files under $NIRA_HOME/.state/:
#   frontend-built    — atomic marker written on success
#   frontend-failed   — written on failure or skip, with the reason
#   frontend-build.log

set -euo pipefail

NIRA_HOME="${NIRA_HOME:-$HOME/.nira}"
SRC_DIR="$NIRA_HOME/src"
STATE_DIR="$NIRA_HOME/.state"
LOG="$STATE_DIR/frontend-build.log"
BUILT="$STATE_DIR/frontend-built"
FAILED="$STATE_DIR/frontend-failed"
FRONTEND="$SRC_DIR/frontend"
# vite writes here; it is the directory app.py mounts when it exists.
STATIC="$SRC_DIR/src/nira/server/static"

mkdir -p "$STATE_DIR"

if [[ ! -d "$FRONTEND" ]]; then
    echo "build-frontend.sh: no frontend at $FRONTEND" > "$FAILED"
    exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
    {
        echo "build-frontend.sh: npm is not installed, so the web UI was not built."
        echo "The CLI and the REST API work without it. To add the web UI later:"
        echo "  cd $FRONTEND && npm ci && npm run build"
    } > "$FAILED"
    exit 0   # A missing web UI is not a failed install.
fi

cd "$FRONTEND"
if npm ci --no-audit --no-fund >>"$LOG" 2>&1 && npm run build >>"$LOG" 2>&1; then
    # Same lesson as the Rust extension: a build tool reporting success is
    # not evidence the artefact landed where the server looks for it.
    if [[ ! -f "$STATIC/index.html" ]]; then
        {
            echo "build-frontend.sh: npm run build succeeded but there is no"
            echo "index.html at $STATIC — the server mounts that directory, so"
            echo "GET / would still 404."
            tail -n 30 "$LOG" 2>/dev/null || true
        } > "$FAILED"
        rm -f "$BUILT"
        exit 1
    fi
    tmp="$BUILT.tmp"
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "$tmp"
    mv "$tmp" "$BUILT"
    rm -f "$FAILED"
    exit 0
else
    {
        echo "build-frontend.sh: the web UI did not build. The CLI and the"
        echo "REST API are unaffected."
        tail -n 30 "$LOG" 2>/dev/null || true
    } > "$FAILED"
    rm -f "$BUILT"
    exit 1
fi
