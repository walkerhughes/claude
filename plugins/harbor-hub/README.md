# harbor-hub

An [MCP](https://modelcontextprotocol.io) server for the [Harbor](https://www.harborframework.com) hub. It exposes your evaluation jobs, trials, uploads, and published packages as tools an agent (Claude Code, etc.) can call directly, so you can ask "did my upload work?" or "what was the mean reward on job X?" without leaving the chat.

It wraps Harbor's own async client classes (`HubClient`, `UploadDB`, `RegistryDB`, `Uploader`, `Downloader`, `Publisher`), so there is no separate API layer to maintain. Harbor reads `HARBOR_API_KEY` and handles token exchange itself.

This lives in the [`claude`](../../) monorepo, consolidated from a standalone repo with full commit history preserved (`git log`/`git blame` resolve inside this directory).

## Install as a Claude Code plugin

Two separate commands. The first opens a prompt that expects only the `owner/repo`, so do not paste both lines at once:

```
/plugin marketplace add walkerhughes/claude
```

```
/plugin install harbor-hub
```

Requires [`uv`](https://docs.astral.sh/uv/) on your PATH; the plugin builds its own environment from the checked-in `uv.lock` on first launch, which takes a few seconds before the tools appear.

If you have already run `harbor auth login`, that is the whole setup: the server reads `~/.harbor/credentials.json` on its own. Ask the agent to call `whoami` to confirm.

## Credentials

Authenticate once:

```bash
harbor auth login
```

That mints a key scoped to the logged-in user and stores it in `~/.harbor/credentials.json`, which harbor reads on its own. The plugin needs no further configuration, and no key ever goes into a config file or a `.env`.

You do not need a global harbor install: harbor ships inside the plugin's environment, so `uv run --project <plugin-dir> harbor auth login` works too.

There is no setup skill. If a tool hits an authentication error, it returns the recovery steps (`harbor auth status`, then `login` or `logout`) in its `suggestions`, so the agent gets them exactly when they are needed and they cost nothing otherwise. The plugin's standing guidance lives in the MCP server's `instructions`, which Claude Code loads into every session. A `CLAUDE.md` at the plugin root would *not* work: the [plugins reference](https://code.claude.com/docs/en/plugins-reference) states it is not loaded as project context.

`harbor auth status` shows what is stored, but it only reads that local file, so it still reports success for a key that has since been revoked. `whoami` is what confirms the credential is live; it returns the key *id* and source, never the key. Restart the server after changing credentials.

`HARBOR_API_KEY` also works as an override, since harbor itself checks it first. That is for CI and scripting; interactively, prefer `harbor auth login` so the key stays scoped to you.

## Local development

```bash
uv sync
```

Run the server directly:

```bash
./scripts/start-server.sh
```

[`.mcp.json`](.mcp.json) is the **plugin** config and only works when loaded as a plugin, because `${CLAUDE_PLUGIN_ROOT}` is substituted by the plugin loader. Do not add a `:-default` to it to make local discovery work, which is what broke it for three releases: the `:-default` form is handled by environment-variable expansion, which does not know `CLAUDE_PLUGIN_ROOT`, so the default silently won and the server was launched against whatever project the user happened to be in. It failed as an opaque JSON-RPC `-32000`, visible only in `~/Library/Caches/claude-cli-nodejs/<project>/mcp-logs-plugin-harbor-mcp-harbor-hub/`. Two tests in [tests/unit/test_plugin_config.py](tests/unit/test_plugin_config.py) now guard this.

[`scripts/start-server.sh`](scripts/start-server.sh) resolves the plugin root from its own location, finds `uv` on PATH or in the common install directories, drops an inherited `VIRTUAL_ENV`, and writes diagnostics to stderr so stdout stays a clean JSON-RPC channel.

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
