#!/usr/bin/env bash
# build-extension.sh — build the Rust maturin extension into the venv.
#
# State files under $NIRA_HOME/.state/:
#   extension-built   — atomic marker written on success
#   extension-failed  — written on failure with stderr tail
#   extension-build.log — captured stderr/stdout

set -euo pipefail

NIRA_HOME="${NIRA_HOME:-$HOME/.nira}"
# Self-heal PATH for cargo: install-rust.sh installs to ~/.cargo/bin, but
# its export doesn't propagate to subsequent subprocess invocations.
export PATH="$HOME/.cargo/bin:$PATH"
SRC_DIR="$NIRA_HOME/src"
STATE_DIR="$NIRA_HOME/.state"
LOG="$STATE_DIR/extension-build.log"
BUILT="$STATE_DIR/extension-built"
FAILED="$STATE_DIR/extension-failed"
MANIFEST="$SRC_DIR/rust/crates/nira-python/Cargo.toml"

mkdir -p "$STATE_DIR"

if [[ ! -f "$MANIFEST" ]]; then
    echo "build-extension.sh: manifest not found at $MANIFEST" > "$FAILED"
    exit 1
fi

# The venv `nira` actually runs from. Not $SRC_DIR/.venv — that one is
# created by `uv run` because the checkout has a pyproject.toml, and nothing
# ever executes out of it.
VENV_DIR="$NIRA_HOME/.venv"
VENV_PY="$VENV_DIR/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
    echo "build-extension.sh: no interpreter at $VENV_PY" > "$FAILED"
    exit 1
fi

cd "$SRC_DIR"
# Build a wheel and install it into the serving venv by path.
#
# Not `maturin develop`: that installs into whichever venv it considers
# active, and under `uv run` inside a checkout that is $SRC_DIR/.venv, which
# nothing ever executes out of. Naming the target interpreter is the only
# form of this that cannot pick the wrong one.
WHEEL_DIR="$STATE_DIR/wheel"
rm -rf "$WHEEL_DIR"

if uv run --with maturin maturin build --release \
        -m "$MANIFEST" --out "$WHEEL_DIR" \
        --interpreter "$VENV_PY" >>"$LOG" 2>&1 \
   && uv pip install --python "$VENV_PY" --reinstall \
        "$WHEEL_DIR"/nira_rust-*.whl >>"$LOG" 2>&1; then
    # Verify against the serving interpreter by path, not through `uv run`.
    #
    # There has been a check here since #502, and it asked `uv run python`,
    # which resolves to $SRC_DIR/.venv — the very venv the extension was being
    # misinstalled into. So it passed every time, including on installs where
    # `nira` could not import the module at all: the rate limiter fell back to
    # a no-op and said so once, in a warning, at startup.
    if ! "$VENV_PY" -c "import nira_rust" >>"$LOG" 2>&1; then
        # Not $? — that is the status of the negated test, which is 0 exactly
        # when the import failed, so the script used to exit 0 on this path
        # and the caller saw a success.
        {
            echo "build-extension.sh: the wheel installed but 'import nira_rust'"
            echo "failed in the serving venv ($VENV_DIR) — the extension is"
            echo "not where nira runs."
            tail -n 50 "$LOG" 2>/dev/null || true
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
    rc=$?
    {
        echo "build-extension.sh failed (exit=$rc)"
        tail -n 50 "$LOG" 2>/dev/null || true
    } > "$FAILED"
    rm -f "$BUILT"
    exit "$rc"
fi
