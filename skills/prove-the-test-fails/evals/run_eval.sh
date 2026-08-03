#!/bin/bash
# The agentic eval for the prove-the-test-fails skill. Costs LLM tokens.
#
# Copies the fixture into a scratch git repository, makes the skill available to a
# headless Claude Code run as a project skill, and asks the question the skill exists to
# answer: can this test fail? Grading is on behaviour, not prose:
#
#   1. the verdict is UNGUARDED, which is only knowable by breaking a strategy
#   2. the tracked files are byte-identical to the starting commit, so any mutation the
#      agent applied was reverted
#   3. the suite is green again at the end
#
# --control runs the same task with the skill absent, which is how the eval shows the
# guidance changed anything.
#
# Usage: run_eval.sh [--control] [--model <name>]
set -euo pipefail

EVALS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$EVALS_DIR")"
SKILL_NAME="$(basename "$SKILL_DIR")"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
PYTEST=(uv run --no-project --with pytest pytest -q --tb=no -p no:cacheprovider)

with_skill=1
model=""
while [ $# -gt 0 ]; do
    case "$1" in
        --control) with_skill=0 ;;
        --model) model="$2"; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done

# The transcript lives beside the repository rather than in it, so the agent never sees
# its own output as a file in the tree it is auditing.
run_dir="$(mktemp -d)"
work="$run_dir/repo"
log="$run_dir/agent.log"
mkdir -p "$work"
cp -R "$EVALS_DIR/fixture/." "$work/"

git -C "$work" init -q
git -C "$work" add -A
git -C "$work" -c user.name=eval -c user.email=eval@localhost \
    commit -qm "the fixture, green"
base="$(git -C "$work" rev-parse HEAD)"

# The skill is on disk but outside git, so a dirty tree can only mean the agent left
# something behind.
if [ "$with_skill" -eq 1 ]; then
    mkdir -p "$work/.claude/skills/$SKILL_NAME"
    cp "$SKILL_DIR/SKILL.md" "$work/.claude/skills/$SKILL_NAME/SKILL.md"
    echo ".claude/" >> "$work/.git/info/exclude"
    echo "==> running with the skill available"
else
    echo "==> control run: the skill is absent"
fi

claude_args=(-p "$(cat "$EVALS_DIR/prompt.md")"
             --permission-mode acceptEdits
             --allowedTools "Bash Read Edit Write Grep Glob")
if [ -n "$model" ]; then
    claude_args+=(--model "$model")
fi

(cd "$work" && "$CLAUDE_BIN" "${claude_args[@]}") 2>&1 | tee "$log" || true

echo
echo "==> grading"
status=0
check() {
    local what=$1
    shift
    if "$@" > /dev/null 2>&1; then
        echo "  ok   $what"
    else
        echo "  FAIL $what"
        status=1
    fi
}

verdict="$(head -n 1 "$work/VERDICT.txt" 2>/dev/null | tr -d '[:space:]' || true)"
check "verdict is UNGUARDED (got: '${verdict:-<no VERDICT.txt>}')" \
    test "$verdict" = UNGUARDED
check "tracked files are unchanged, so any mutation was reverted" \
    git -C "$work" diff --quiet "$base" -- src tests pyproject.toml
suite_green() { (cd "$work" && "${PYTEST[@]}"); }
check "the suite is green again" suite_green

if [ "$status" -ne 0 ]; then
    echo "FAIL: transcript and repository left at $run_dir" >&2
    exit 1
fi

rm -rf "$run_dir"
echo "PASS"
