# harbor-mcp agentic evals

Agentic [Harbor](https://github.com/harbor-framework/harbor) tasks that gate on
whether the **harbor-mcp capability surface works against the hub** for a real
agent (claude-code). Each task declares this repo's MCP server (`harbor-mcp`) in
`task.toml` via `[[environment.mcp_servers]]` with `transport = "stdio"`, so the
server runs in the main container and the evals work on both the docker and
modal environments (no docker-only compose sidecar).

Each task's `environment/Dockerfile` installs `harbor-mcp` from GitHub so the
stdio command resolves on PATH. Secrets are never baked into images:
`HARBOR_API_KEY` (and, for write tools, `HARBOR_MCP_ENABLE_WRITES`) are passed
at runtime with `harbor run --ae`.

## The evals

The set is deliberately minimal -- one eval per capability bucket, covering
reads and writes against the hub. Every task directory in `evals/` is an eval:
the runners execute them all with a single `harbor run -p evals/`, in parallel,
so nothing else may live here as a task directory.

| Eval | Bucket | The agent must | Expected tool | Answer in `/app/answer.txt` |
| --- | --- | --- | --- | --- |
| `read-job` | job reads | report the mean reward of job `$EVAL_READ_JOB_ID` | `get_job_overview` | a plain decimal, e.g. `1.0` |
| `delete-job` | job writes | delete job `$EVAL_DELETE_JOB_ID` (writes enabled; confirm-gated) | `delete_job` | `deleted` |
| `check-published-task` | registry reads | decide whether `$EVAL_TASK_REF` is published | `check_task_published` | `yes` or `no` |

The "expected tool" column is what the `process` reward asserts. It is
**not** in `instruction.md` -- see below.

`read-job` and `delete-job` take separate seeded jobs so the parallel run has
no read/delete race. `delete-job` enables the MCP write tools for itself via
its own `[environment.env]`, so the read-only evals keep a read-only server.

Auth (`whoami`) is exercised implicitly -- nothing reads or writes without it.
Deliberately **out of scope** for a per-PR gate: `publish_task` /
`publish_dataset` (published versions are immutable/content-addressed, not
cleanly reversible) and `set_job_visibility` / `share_job` (niche).

## Two rewards: `outcome` and `process`

Each eval scores two rewards, both computed by
[rewardkit](https://harborframework.com/docs/rewardkit) (baked into the image,
so verification needs no network of its own; `tests/test.sh` is just
`rewardkit /tests`). rewardkit's nested layout gives one reward per
subdirectory of `tests/`:

| Reward | `tests/` dir | Grades |
| --- | --- | --- |
| `outcome` | `outcome/check.py` | the answer, against ground truth recomputed live from the hub |
| `process` | `process/check.py` | that the answer came **through the harbor-hub MCP server** |

`outcome` on its own cannot gate the MCP. The `harbor` CLI is on PATH in the
eval image (the oracle and the verifiers both need it), so an agent that never
touches the MCP -- or one that calls it, gets an error, and quietly falls back
to the CLI -- still produces a correct answer and still scores 1.0. That
fallback is exactly the regression these evals exist to catch, so `process`
grades the agent's ATIF trajectory at `/logs/agent/trajectory.json`:

- `criteria.trajectory_tool_used("mcp__harbor-hub__<tool>")` -- the eval's
  expected tool was actually called. Claude Code names MCP tools
  `mcp__<server>__<tool>`, where `<server>` is the
  `[[environment.mcp_servers]]` name from `task.toml`.
- `no_harbor_cli` (local `@criterion`) -- no `Bash` tool call in the trajectory
  invoked the `harbor` CLI. `trajectory_tool_not_used("Bash")` would be wrong
  here: the agent legitimately needs Bash to read `$EVAL_*` and write the
  answer.

Both trajectory criteria **fail closed**: a missing or unreadable trajectory
scores 0, never a silent pass.

> Gotcha, if you add more trajectory criteria: rewardkit's built-ins default to
> `path="/logs/trajectory.json"`, but Harbor agents write
> `/logs/agent/trajectory.json`. The wrong path is not an error -- the file is
> just missing and the criterion returns 0. Always pass `path` explicitly.

## The instructions must not name the tool

Each `instruction.md` states the **intent** and the answer format, and stops
there. It does not name the tool to call, does not enumerate the server's
tools, and does not say "don't use the `harbor` CLI".

That is the whole point. The plugin exists to offload tool selection from the
caller onto the agent, so an instruction that names the tool tests reading
comprehension and proves nothing about the plugin. The `process` reward asserts
the behaviour; making that behaviour happen is the plugin's job.

So when an eval fails on `process`, the fix is upstream, in this order:

1. **The tool description** (`src/harbor_mcp/tools/*.py` docstrings). Does it
   say when to reach for this tool rather than a neighbouring one? `read-job`
   is the sharp case: `list_jobs`, `get_job_overview`, and `get_job_trials` all
   surface a reward, so `get_job_overview` has to say that its `reward` is the
   already-aggregated mean and that averaging `get_job_trials` yourself is the
   wrong move.
2. **The server instructions** (`INSTRUCTIONS` in `src/harbor_mcp/server.py`),
   which carry the cross-tool routing and the convention that these tools are
   preferred over shelling out to the `harbor` CLI.
3. Only then, the eval -- and only if the intent genuinely reads ambiguously.

Supplying something the tool's own contract requires is not a hint:
`delete-job` says "treat this instruction as the user's explicit approval to
delete this specific job" because `delete_job` refuses without approval, by
design. That is the eval standing in for the user, not telling the agent which
tool to call.

## Self-truthing verifiers

Verifiers do not rely on planted expected values. `HARBOR_API_KEY` is threaded
into each verifier through `[verifier.env]` (`${HARBOR_API_KEY:-}`, resolved
from the host at `harbor run` time), so every `tests/test.sh` recomputes the
ground truth live from the hub with the `harbor` CLI and compares:

| Eval | How the `outcome` reward self-truths |
| --- | --- |
| `read-job` | `harbor hub job show $EVAL_READ_JOB_ID --json` -> `.stats.avg_reward`, matched within 1e-6 |
| `delete-job` | `harbor hub job show $EVAL_DELETE_JOB_ID --json` must be empty (job gone) |
| `check-published-task` | `harbor download $EVAL_TASK_REF` succeeds iff published |

Oracles (`solution/solve.sh`) answer the same questions independently, also via
the `harbor` CLI.

## Running

```bash
export HARBOR_API_KEY=hk_...
export ANTHROPIC_API_KEY=sk-ant-...   # or CLAUDE_CODE_OAUTH_TOKEN
make evals          # the merge gate: drives the evals with claude-code
```

`make evals` (backed by `evals/run_evals.sh`) is self-contained, in three
phases:

1. **Seed** -- mints two fresh hub jobs with the oracle agent (no LLM cost) by
   running the `tests/e2e/fixtures/hello-world` fixture with `--upload`: one
   job for `read-job` (`EVAL_READ_JOB_ID`) and one for `delete-job`
   (`EVAL_DELETE_JOB_ID`). Fresh ids per run mean no cross-run collisions; two
   jobs mean the parallel evals cannot race each other.
2. **Run** -- a single `harbor run -a claude-code` executes all the evals in
   parallel, then the runner gates on every reward being `1.0`
   (`evals/check_reward.py`) -- `harbor run` exits 0 regardless of reward, so
   the runner inspects the result itself. `check-published-task` checks the
   pinned public task `hello-world/hello-world@1`.
3. **Cleanup** -- drops any seeded job that still exists on the hub
   (`delete-job` removes its own on success; the read job always needs
   dropping).

`HARBOR_TEST_ENV` selects `docker` (default; needs a local Docker daemon) or
`modal` (needs Modal credentials); CI's gate uses modal.

`HARBOR_MCP_REF` (default `main`) is the git ref the eval images
pip-install `harbor-mcp` from. It matters more than it looks: the images do not
build from your checkout, so by default a run exercises whatever is on `main`,
not the code in front of you. CI passes the PR head sha, without which the gate
would build main's server and greenlight a PR that breaks the MCP. Set it
locally to test a branch:

```bash
HARBOR_MCP_REF="$(git rev-parse HEAD)" make evals   # must be pushed first
```

The runner pins the ref in a throwaway copy of `evals/` rather than rewriting
the checkout, so an interrupted run leaves no pinned Dockerfile behind.

## Eval-safety check

```bash
make eval-safety    # oracle must pass, nop must fail -- no LLM cost
```

`evals/run_eval_safety.sh` mirrors the gate runner's seed/run/cleanup shape
twice: once with the `oracle` agent (every eval must reach reward 1.0 -- the
evals are solvable) and once with the `nop` agent, which produces no answer
(every eval must score 0 -- the evals are not trivially passable). Each agent
gets its own seeded job pair; all seeds are dropped afterward.

The oracle is gated on `outcome` only (`check_reward.py --only outcome`). It is
a shell script, not an agent: it leaves no trajectory and cannot call MCP tools,
so `process` is not oracle-solvable by construction. The nop agent is gated on
both rewards, which is strictly stronger. This runs in CI
via [`harbor-hub-eval-safety.yml`](../../../.github/workflows/harbor-hub-eval-safety.yml)
on every PR that touches `evals/**`, so the evals stay honest independently of
the merge gate.

## In CI

Both live in [`harbor-hub.yml`](../../../.github/workflows/harbor-hub.yml) and
[`harbor-hub-eval-safety.yml`](../../../.github/workflows/harbor-hub-eval-safety.yml):

| Job | Agent | Costs tokens | Runs on |
| --- | --- | --- | --- |
| `lint-unit` | -- | no | every PR touching the plugin |
| `integration` | -- | no | same, needs `HARBOR_API_KEY` |
| `e2e` | oracle | no | same, needs Modal |
| `eval-safety` | oracle + nop | no | PRs touching `evals/**` |
| `evals` | **claude-code** | **yes** | same-repo PRs and pushes to main |

`evals` is the merge gate on the MCP capability surface. It `needs: [lint-unit]`
so a formatting slip does not burn tokens, and is guarded to same-repo events
because a fork PR gets no secrets.

Every secret-dependent job here skips silently when its secret is absent, so a
green check is not by itself proof the job ran -- check the log if it returned
suspiciously fast.

To make `evals` binding, mark it a required status check in the repo's branch
protection for `main`.
