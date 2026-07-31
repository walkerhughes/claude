# Shared helpers for the eval runners. Sourced, not executed.
#
# Requires in the environment: HARBOR_API_KEY, HARBOR_TEST_ENV (docker|modal),
# and REPO_ROOT (repo root path). `harbor` must be on PATH.

# The task the bootstrap runs to mint hub jobs: the shared hello-world fixture
# (modal-compatible; see its README). It lives under tests/e2e/fixtures, NOT
# evals/, because the gate runs `harbor run -p evals/` and this canary is a
# seeding fixture, not an MCP eval.
BOOTSTRAP_TASK="${BOOTSTRAP_TASK:-$REPO_ROOT/tests/e2e/fixtures/hello-world}"

# bootstrap_job <out_dir> [job_name]
# Runs BOOTSTRAP_TASK with the oracle agent (no LLM cost) and uploads it,
# creating a fresh hub job. Job artifacts land under <out_dir>. Echoes the new
# hub job id on stdout. Harbor's progress tables are seeding noise, so they go
# to <out_dir>/bootstrap.log and are only dumped (to stderr) on failure --
# keeping the runners' output to one result table per eval run.
bootstrap_job() {
    local out=$1 name=${2:-harbor-mcp-evals}
    mkdir -p "$out"
    if ! harbor run \
        -y \
        -p "$BOOTSTRAP_TASK" \
        -a oracle \
        -e "$HARBOR_TEST_ENV" \
        -o "$out" \
        --job-name "$name" \
        --upload \
        -q > "$out/bootstrap.log" 2>&1; then
        cat "$out/bootstrap.log" >&2
        return 1
    fi
    python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["id"])' \
        "$out/$name/result.json"
}

# drop_job <job_id>
# Best-effort delete of a hub job (idempotent; no-op on empty id).
drop_job() {
    [ -n "${1:-}" ] || return 0
    harbor hub job delete "$1" -y > /dev/null 2>&1 || true
}
