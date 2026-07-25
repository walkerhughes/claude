# harbor-mcp

An [MCP](https://modelcontextprotocol.io) server for the [Harbor](https://www.harborframework.com) hub. It exposes your evaluation jobs, trials, uploads, and published packages as tools an agent (Claude Code, etc.) can call directly, so you can ask "did my upload work?" or "what was the mean reward on job X?" without leaving the chat.

It wraps Harbor's own async client classes (`HubClient`, `UploadDB`, `RegistryDB`, `Uploader`, `Downloader`, `Publisher`), so there is no separate API layer to maintain. Harbor reads `HARBOR_API_KEY` and handles token exchange itself.

This lives in the [`mcps`](../) monorepo, consolidated from a standalone repo with full commit history preserved (`git log`/`git blame` resolve inside this directory).

## Install as a Claude Code plugin

```
/plugin marketplace add walkerhughes/mcps
/plugin install harbor-mcp
```

Requires [`uv`](https://docs.astral.sh/uv/) on your PATH; the plugin builds its own environment from the checked-in `uv.lock` on first launch.

Then run `/harbor-mcp:setup`, which checks your credentials and walks you through whichever path you need.

## Credentials

The server resolves a key from the first source that has one:

| | Source | How |
|---|--------|-----|
| 1 | `HARBOR_API_KEY` in the environment | Export it in your shell |
| 2 | `.env` in your project root | `HARBOR_API_KEY=sk-harbor-...` (searched in the working directory and up to three parents) |
| 3 | `~/.harbor/credentials.json` | `harbor auth login` |

So if you have already run `harbor auth login`, the plugin works with no configuration at all. A missing `.env` is normal, not an error. Nothing here ever writes your key back to disk or logs it, and `whoami` reports only the key *id* and its source.

Verify with `whoami`. Restart the server after changing credentials.

## Local development

```bash
uv sync
cp .env.example .env      # then set HARBOR_API_KEY
```

The same [`.mcp.json`](.mcp.json) serves both cases: it launches `uv run --project ${CLAUDE_PLUGIN_ROOT:-.}`, which resolves to the installed plugin directory when loaded as a plugin and to this directory when Claude Code is started from here.

## Tools

Read tools work with any valid `HARBOR_API_KEY`. Write tools are gated (see below).

| Tool | What it does |
|------|--------------|
| `whoami` | Confirm credentials; returns the user id and key source (never the key) |
| `list_jobs` | List your hub jobs with trial counts, cost, and reward |
| `get_job_overview` | Roll up one job: counts, retries, tokens, cost, reward, models |
| `get_job_trials` | List a job's trials (task, status, reward, error, duration) |
| `get_trial_detail` | One trial's full record |
| `check_job_upload` | Verify an upload: row exists, archive present, per-status counts, missing archives |
| `check_task_published` | Whether a task version exists in the registry (missing → `published: false`) |
| `resolve_dataset` | Resolve a dataset version and list its member tasks |
| `upload_job` | Upload a local job directory (idempotent, resumable) |
| `publish_task` / `publish_dataset` | Publish a local task/dataset to the registry |
| `download_job` | Download and extract a job's archive locally |
| `set_job_visibility` | Flip a job public/private |
| `share_job` | Grant read access to orgs/users |
| `delete_job` | Delete a job's rows (permanent; requires `confirm`) |

## Write gating

Read-only is the default. Every write tool refuses unless `HARBOR_MCP_ENABLE_WRITES=true` in the server environment, which you set the same way as your key (shell export or `.env`), then restart the server. `delete_job` additionally requires `confirm=true` per call, which the agent should pass only after you explicitly approve deleting a specific job. This keeps read-only use the safe default.

## Testing

| Tier | Command | Needs | Uses an LLM? |
|------|---------|-------|--------------|
| unit | `make test` | nothing (harbor clients mocked) | no |
| integration | `make test-integration` | `HARBOR_API_KEY` | no (tools driven directly over MCP stdio) |
| e2e | `make test-e2e` | `HARBOR_API_KEY` + `HARBOR_TEST_ENV` | no (oracle agent runs `solve.sh`) |
| evals | `make evals` | `HARBOR_API_KEY` + `ANTHROPIC_API_KEY` + `EVAL_*` | yes (agent rollouts) |

`HARBOR_TEST_ENV` selects where harbor runs the fixture job: `docker` (default) or `modal`. Modal needs its own credentials (`modal token new`) and the `modal` extra (`uv sync --dev --extra modal`), which pulls in harbor's modal support; the base install omits it. The integration and e2e tiers are deterministic (no agent decisions), so they gate PRs without spending on model calls; the `evals/` agent rollouts run separately once tool use is proven at the lower tiers.

The `harbor` dependency is pinned exactly because this server imports Harbor internals, which are not a stable public API. Bump it deliberately.
