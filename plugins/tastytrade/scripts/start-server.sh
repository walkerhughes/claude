#!/usr/bin/env bash
# Launch the tastytrade MCP server.
#
# Exists because "command": "uv" in .mcp.json assumes uv is on whatever PATH the
# MCP client spawns with. It often is not: a Homebrew uv lives in
# /opt/homebrew/bin, which is missing from the minimal PATH some launch contexts
# provide, and the failure surfaces only as an opaque JSON-RPC -32000.
#
# Diagnostics go to stderr. stdout is the JSON-RPC channel and must stay clean.
set -euo pipefail

# Resolve the plugin root from this script's own location rather than
# CLAUDE_PLUGIN_ROOT, so it works however the server is launched.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

find_uv() {
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return
  fi
  # ponytail: fixed candidate list beats parsing shell profiles. Covers Homebrew
  # on Apple Silicon and Intel, the standalone installer, and cargo install.
  local candidate
  for candidate in \
    /opt/homebrew/bin/uv \
    /usr/local/bin/uv \
    "$HOME/.local/bin/uv" \
    "$HOME/.cargo/bin/uv"
  do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  return 1
}

if ! UV="$(find_uv)"; then
  echo "tastytrade-mcp: cannot find the 'uv' executable." >&2
  echo "  Searched PATH plus /opt/homebrew/bin, /usr/local/bin, ~/.local/bin, ~/.cargo/bin." >&2
  echo "  Install it (https://docs.astral.sh/uv/) or symlink it into /usr/local/bin." >&2
  exit 127
fi

# Drop any inherited VIRTUAL_ENV. uv already ignores a mismatched one, but it
# warns loudly on stderr about "does not match the project environment path",
# which reads like the cause of a failure.
unset VIRTUAL_ENV

# cd into the project rather than using the `tastytrade-mcp` console script.
# That script is currently broken: pyproject flattens src/ via
# sources = { "src" = "" }, but every internal import is relative, so the
# installed package cannot import itself and the entry point still names
# `src.server`. Running as a module from the project root is the only working
# invocation. Credentials resolve from ~/.tastytrade-mcp/credentials.json or the
# environment, both absolute, so this cd does not affect them.
cd "$ROOT"
exec "$UV" run --project "$ROOT" python -m src.server
