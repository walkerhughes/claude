#!/bin/bash
# Proves the eval fixture is still a trap. No agent, no LLM, no network beyond
# fetching pytest.
#
# The agentic eval is only meaningful while `test_routers_satisfy_the_same_contract`
# genuinely cannot fail. This applies the mutation the eval expects an agent to find,
# stubbing `regex_router` to return nothing, and asserts the exact shape of the
# resulting run: the contract test survives, the regex case of the parameter test dies,
# the segment case lives, and the empty-path test survives for its own good reason. If
# someone repairs the fixture's assertion, this goes red and says so.
#
# Runs on a copy: the checked-in fixture is never mutated.
set -euo pipefail

EVALS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTEST=(uv run --no-project --with pytest pytest -v --tb=no -p no:cacheprovider)

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp -R "$EVALS_DIR/fixture/." "$work/"

report="$work/report.txt"

echo "==> baseline: the fixture suite must be green"
(cd "$work" && "${PYTEST[@]}") > "$report" 2>&1 || {
    cat "$report"
    echo "FAIL: the untouched fixture suite is not green." >&2
    exit 1
}

echo "==> mutation: stub regex_router to return nothing"
(cd "$work" && python3 - <<'PY'
import pathlib

source = pathlib.Path("src/routing.py")
text = source.read_text()
anchor = '    """Compiled patterns: each route becomes a regex the whole path must match."""\n'
if anchor not in text:
    raise SystemExit("FAIL: regex_router no longer looks the way this check expects.")
source.write_text(text.replace(anchor, anchor + "    return []\n", 1))
PY
)

echo "==> the mutated suite must fail in one specific shape"
(cd "$work" && "${PYTEST[@]}") > "$report" 2>&1 || true

status=0
expect() {
    local node=$1 want=$2 why=$3
    if grep -qF "::${node} ${want}" "$report"; then
        echo "  ok   ${node} ${want}"
    else
        echo "  FAIL ${node} expected ${want}: ${why}" >&2
        status=1
    fi
}

# The trap itself: the one test that claims to guard the shared contract does not
# notice that an implementation stopped returning anything.
expect "test_routers_satisfy_the_same_contract" PASSED \
    "the fixture's contract test can fail now, so the eval no longer poses the question it was written to pose"

# Blast radius: the mutation is confined to one of the two implementations.
expect "test_matches_a_route_with_a_parameter[regex]" FAILED \
    "the mutation stopped reaching the code the test covers"
expect "test_matches_a_route_with_a_parameter[segment]" PASSED \
    "the mutation leaked into the other implementation, so the fixture no longer shows a blast radius"

# The legitimate survivor: asserting emptiness is satisfied by an empty implementation.
expect "test_empty_path_matches_nothing[regex]" PASSED \
    "the fixture no longer contains a test that correctly survives the mutation"

if [ "$status" -ne 0 ]; then
    echo
    cat "$report"
    echo "FAIL: the fixture is no longer the trap the eval needs." >&2
    exit 1
fi

echo "PASS: the fixture's contract test still cannot fail."
