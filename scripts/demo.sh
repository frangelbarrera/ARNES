#!/usr/bin/env bash
# scripts/demo.sh — Produce a clean, narrated demo of ARNES for screenshots / GIFs.
#
# Usage:
#   scripts/demo.sh                 # Run the demo, print to terminal
#   scripts/demo.sh --record tape   # Also record to demo.tape (for `vhs`)
#   scripts/demo.sh --save out.txt  # Save transcript to out.txt
#
# Recording a GIF from this demo
# ------------------------------
# Two supported paths (see CONTRIBUTING.md for full instructions):
#
#   1. vhs (recommended, deterministic):
#        brew install vhs            # or: go install github.com/charmbracelet/vhs@latest
#        scripts/demo.sh --record demo.tape
#        vhs demo.tape               # produces demo.gif
#
#   2. agg (asciinema → gif):
#        cargo install --git https://github.com/nathanbabcock/agg
#        asciinema rec demo.cast -c "scripts/demo.sh"
#        agg demo.cast demo.gif --speed 1.5 --font-family "JetBrains Mono"
#
# Requirements: a working ARNES install (uv sync --all-extras --dev) and
# `arnes` available on PATH (or run through `uv run`).

set -euo pipefail

# --- Configuration ----------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Prefer `uv run` so the demo works without an active venv.
if command -v uv >/dev/null 2>&1; then
  ARNES=(uv run arnes)
else
  ARNES=(arnes)
fi

RECORD_TAPE=""
SAVE_TRANSCRIPT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --record)
      RECORD_TAPE="${2:-demo.tape}"
      shift 2
      ;;
    --save)
      SAVE_TRANSCRIPT="${2:-demo.txt}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,28p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

# --- Helpers ----------------------------------------------------------------

# Pretty-print a section header.
header() {
  local title="$1"
  printf '\n\033[1;36m'
  printf '=%.0s' {1..70}
  printf '\n# %s\n' "$title"
  printf '%.0s' {1..70}
  printf '\033[0m\n\n'
}

# Run a command and echo the command line first.
run() {
  printf '\033[2m$\033[0m %s\n' "$*"
  printf '\n'
  "$@"
  printf '\n'
}

# ARNES ASCII art banner.
banner() {
  cat <<'EOF'
    ___
   /   |  _________ ___   _______
  / /| | / ___/ __ `__ \ / ___/ /
 / ___ |/ /  / / / / / // /__/ /
/_/  |_/_/  /_/ /_/ /_/ \____/_/
        The Open Agent Harness
EOF
}

# --- Transcript capture -----------------------------------------------------

if [[ -n "$SAVE_TRANSCRIPT" ]]; then
  exec > >(tee "$SAVE_TRANSCRIPT") 2>&1
fi

if [[ -n "$RECORD_TAPE" ]]; then
  {
    echo 'Output "demo.gif"'
    echo 'Set FontSize 14'
    echo 'Set Width 1200'
    echo 'Set Height 700'
    echo 'Set Theme "Dracula"'
    echo 'Set Padding 20'
    echo 'Type "scripts/demo.sh"'
    echo 'Enter'
    echo 'Sleep 5s'
  } > "$RECORD_TAPE"
  printf 'Wrote vhs tape to %s — run `vhs %s` to render the GIF.\n\n' \
    "$RECORD_TAPE" "$RECORD_TAPE" >&2
fi

# --- Demo flow --------------------------------------------------------------

banner
echo
echo "Repo:  $(git rev-parse --show-toplevel 2>/dev/null || echo "$REPO_ROOT")"
echo "Commit: $(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
"${ARNES[@]}" --version
echo

# 1. Hello world with mock LLM ------------------------------------------------

header "1. Run a manual with the mock LLM (no network, \$0 cost)"

run "${ARNES[@]}" run manuals/hello-world.yaml --mock

# Show the bitácora that was just produced.
LATEST_BITACORA="$(ls -t bitacora-hello-world-*.md 2>/dev/null | head -1 || true)"
if [[ -n "$LATEST_BITACORA" ]]; then
  header "2. The bitácora — an auditable markdown trail"
  printf '\033[2m# Showing first 40 lines of %s\033[0m\n' "$LATEST_BITACORA"
  echo
  sed -n '1,40p' "$LATEST_BITACORA"
  echo
  printf '\033[2m# ... (%s has the full audit trail)\033[0m\n' "$LATEST_BITACORA"
else
  echo "No bitácora was produced — check that arnes run succeeded."
fi

# 2. List specialists --------------------------------------------------------

header "3. List available specialists"

run "${ARNES[@]}" list specialists

# 3. Lint a manual -----------------------------------------------------------

header "4. Lint a playbook (validate without executing)"

run "${ARNES[@]}" lint manuals/audit-pr.yaml

# --- Wrap up ----------------------------------------------------------------

header "Done"
echo "Next steps:"
echo "  - Read the README:    https://github.com/frangelbarrera/ARNES#readme"
echo "  - Browse the manuals: ls manuals/"
echo "  - Record a GIF:       scripts/demo.sh --record demo.tape && vhs demo.tape"
echo
