# harbor-mcp

An [MCP](https://modelcontextprotocol.io) server for the [Harbor](https://www.harborframework.com) hub. It exposes your evaluation jobs, trials, uploads, and published packages as tools an agent (Claude Code, etc.) can call directly, so you can ask "did my upload work?" or "what was the mean reward on job X?" without leaving the chat.

It wraps Harbor's own async client classes (`HubClient`, `UploadDB`, `RegistryDB`, `Uploader`, `Downloader`, `Publisher`), so there is no separate API layer to maintain. Harbor reads `HARBOR_API_KEY` and handles token exchange itself.

This lives in the [`mcps`](../) monorepo, consolidated from a standalone repo with full commit history preserved (`git log`/`git blame` resolve inside this directory).

## Install as a Claude Code plugin

Two separate commands. The first opens a prompt that expects only the `owner/repo`, so do not paste both lines at once:

```
/plugin marketplace add walkerhughes/mcps
```

```
/plugin install harbor-mcp
```

Requires [`uv`](https://docs.astral.sh/uv/) on your PATH; the plugin builds its own environment from the checked-in `uv.lock` on first launch, which takes a few seconds before the tools appear.

Then run `/harbor-mcp:setup`. It checks your credentials, walks you through login if needed, and summarizes what is currently in your account.

## Credentials

Authenticate once:

```bash
harbor auth login
```

That mints a key scoped to the logged-in user and stores it in `~/.harbor/credentials.json`, which harbor reads on its own. The plugin needs no further configuration, and no key ever goes into a config file or a `.env`.

You do not need a global harbor install: harbor ships inside the plugin's environment, so `uv run --project <plugin-dir> harbor auth login` works too, which is what `/harbor-mcp:setup` falls back to.

`harbor auth status` shows what is stored, but it only reads that local file, so it still reports success for a key that has since been revoked. `whoami` is what confirms the credential is live; it returns the key *id* and source, never the key. Restart the server after changing credentials.

`HARBOR_API_KEY` also works as an override, since harbor itself checks it first. That is for CI and scripting; interactively, prefer `harbor auth login` so the key stays scoped to you.

## Local development

```bash
uv sync
```

The same [`.mcp.json`](.mcp.json) serves both cases: it runs [`scripts/start-server.sh`](scripts/start-server.sh) at `${CLAUDE_PLUGIN_ROOT:-.}`, which resolves to the installed plugin directory when loaded as a plugin and to this directory when Claude Code is started from here.

That wrapper exists for a reason worth knowing: naming `uv` directly as the command assumes it is on whatever PATH the MCP client spawns with, and it often is not. A Homebrew `uv` lives in `/opt/homebrew/bin`, which is missing from the minimal PATH some launch contexts provide, and the server then fails with an opaque JSON-RPC `-32000` and no explanation. The wrapper searches PATH plus the common install locations, resolves the plugin root from its own location, and prints an actionable message to stderr if `uv` genuinely is not installed.

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

Read-only is the default. Every write tool refuses unless `HARBOR_MCP_ENABLE_WRITES=true` in the server environment, so export it in your shell and restart the server. It is a local toggle, not a credential; the plugin passes it through explicitly. `delete_job` additionally requires `confirm=true` per call, which the agent should pass only after you explicitly approve deleting a specific job. This keeps read-only use the safe default.

## Testing

| Tier | Command | Needs | Uses an LLM? |
|------|---------|-------|--------------|
| unit | `make test` | nothing (harbor clients mocked) | no |
| integration | `make test-integration` | `HARBOR_API_KEY` | no (tools driven directly over MCP stdio) |
| e2e | `make test-e2e` | `HARBOR_API_KEY` + `HARBOR_TEST_ENV` | no (oracle agent runs `solve.sh`) |
| evals | `make evals` | `HARBOR_API_KEY` + `ANTHROPIC_API_KEY` + `EVAL_*` | yes (agent rollouts) |

`HARBOR_TEST_ENV` selects where harbor runs the fixture job: `docker` (default) or `modal`. Modal needs its own credentials (`modal token new`) and the `modal` extra (`uv sync --dev --extra modal`), which pulls in harbor's modal support; the base install omits it. The integration and e2e tiers are deterministic (no agent decisions), so they gate PRs without spending on model calls; the `evals/` agent rollouts run separately once tool use is proven at the lower tiers.

The `harbor` dependency is pinned exactly because this server imports Harbor internals, which are not a stable public API. Bump it deliberately.
