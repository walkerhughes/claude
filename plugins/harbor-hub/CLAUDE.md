# harbor-hub

MCP server over the Harbor hub: inspect evaluation jobs, trials, and uploads,
and publish tasks, datasets, and job archives when writes are enabled.

Repo-wide plugin and eval conventions live in the root `CLAUDE.md`. This file is
the plugin-specific part.

## Resources

| What | Where |
| --- | --- |
| Harbor framework source | https://github.com/harbor-framework/harbor |
| The hub itself | https://www.harborframework.com |
| **rewardkit**, how verifiers and criteria are defined | https://www.harborframework.com/docs/rewardkit |
| rewardkit on PyPI (`harbor-rewardkit`) | https://pypi.org/project/harbor-rewardkit/ |
| Claude Code plugin manifest reference | https://code.claude.com/docs/en/plugins-reference |
| MCP specification | https://modelcontextprotocol.io |
| uv | https://docs.astral.sh/uv/ |

`github.com/laude-institute/harbor` is the old URL and 301-redirects to the
`harbor-framework` one above. Use the new one.

The rewardkit page is the one to read before touching anything under `evals/`.
The rule that bites is that **every criterion in a reward directory aggregates by
weighted mean**, so an extra criterion silently dilutes the others rather than
adding a check.

## Commands

```
make test              unit tests
make test-integration  hits the live hub, needs HARBOR_API_KEY
make test-e2e          needs Modal credentials
make lint              ruff check + ruff format --check
make format            apply formatting
make validate-process  score the eval process criteria, no hub or model needed
make eval-safety       oracle solves every eval, nop solves none. Needs the hub
make evals             the merge gate: a real agent over all three evals
```

`validate-process` is the one to run while editing verifiers. It needs no
network, no Docker, and no model, and it catches the failure the gate cannot
afford to discover late.

## What is specific here

**No mock.** Unlike fred and tastytrade, the evals grade against the live hub.
That is why there is no `job.yaml`, no `generate_tasks.py`, and no mock scripts,
and why eval tasks sit at `evals/<name>/` rather than `evals/tasks/<name>/`.
Verifiers are self-truthing: they recompute ground truth from the hub with the
harbor CLI rather than comparing against a planted constant.

**The bypass is the CLI.** The harbor CLI is on PATH in the eval image because
the oracle and the verifiers both need it, so an agent can answer correctly
without ever calling an MCP tool. That is what the `process` reward exists to
catch, and why its check greps shell calls specifically rather than matching a
port the way the mock-backed plugins do.

**Writes are gated.** `HARBOR_MCP_ENABLE_WRITES=true` is required for
`upload_job`, `publish_task`, `publish_dataset`, `download_job`,
`set_job_visibility`, `share_job`, and `delete_job`. `delete_job` additionally
requires `confirm=true`, and it is permanent.

**Python 3.12.** fred and tastytrade require 3.13. `target-version` in
`pyproject.toml` tracks that, which is why it is not in the shared `ruff.toml`.

**Eval images build from a git ref.** `run_evals.sh` pins the Dockerfiles to
`HARBOR_MCP_REF` in a throwaway copy of the tree, and CI passes the PR head sha.
Without that a PR gate builds from main and greenlights code it never tested.
