# claude

My [Claude Code](https://docs.anthropic.com/en/docs/claude-code) setup: the tooling I build for it, and the configuration I carry between machines. This repo doubles as a [plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces), so anything here that ships as a plugin can be installed directly.

Formerly `walkerhughes/mcps`, back when it only held MCP servers.

## MCP servers

[Model Context Protocol](https://modelcontextprotocol.io) servers that give agents direct access to external services. Each lives in its own subdirectory with its own setup, tests, and docs.

| Server | What it connects to | Plugin |
|--------|---------------------|--------|
| [`harbor-hub`](plugins/harbor-hub/) | The [Harbor](https://www.harborframework.com) hub: evaluation jobs, trials, uploads, and published packages. | yes |
| [`tastytrade`](plugins/tastytrade/) | The [TastyTrade Open API](https://developer.tastytrade.com/getting-started/): brokerage account, market data, and order management (12 tools). | not yet |

They follow Honeycomb's [MCP, easy as 1-2-3](https://www.honeycomb.io/blog/mcp-easy-as-1-2-3) guidance: a few curated tools built around real questions rather than raw API endpoints, responses shaped for a model instead of a UI, and typed schemas that steer the model toward valid calls.

## Skills

Skills live in top-level `skills/`, one directory each, and ship through the marketplace as their own installable entries.

| Skill | What it decides |
|-------|-----------------|
| [`parallel-agent-isolation`](skills/parallel-agent-isolation/) | What stateful resources concurrent agents will share, and whether to isolate, serialise, or re-verify serially, before dispatching them. |

A skill's marketplace entry sets `source: "./"` with a `skills` path pointing at its own directory, so several skills can share the one top-level folder without loading each other, and `strict: false` because the repository root has no `plugin.json` to be the authority. Entries deliberately carry no `version`: Claude Code then resolves the version from the commit SHA, so every change reaches installed copies without a manual bump, and the stale-cache trap described below does not apply.

Each skill directory carries its own checks, run from that directory: `make check` for packaging and wiring, which needs no credentials, and `make evals` for behaviour, which costs tokens. CI runs both per skill through `paths` filters, as it does for the servers.

## Install a plugin

Run these as two separate commands, not as one paste: the first opens a prompt that expects only the `owner/repo`.

```
/plugin marketplace add walkerhughes/claude
```

```
/plugin install harbor-hub
```

The non-interactive equivalents are more reliable, and are the only way to move an existing install to a new version, since `claude plugin install` no-ops when the plugin is already present:

```bash
claude plugin marketplace update walkerhughes && claude plugin update harbor-hub@walkerhughes
```

Plugins require [`uv`](https://docs.astral.sh/uv/) on your PATH. The first launch builds the server's environment, so give it a moment before the tools appear. A plugin update needs a Claude Code restart, not just an `/mcp` reconnect. See each server's README for credentials.

### Shipping a plugin change

**Bump `version` in the plugin's `.claude-plugin/plugin.json` in the same PR.** Claude Code extracts an installed plugin to a cache path keyed by that version, so if it does not change, the cache is never refreshed and users keep running the old code however many times they update or reinstall. The change is invisible rather than broken. The `plugin version` workflow enforces this.

## Layout

```
claude/
├── .claude-plugin/          # marketplace manifest
├── plugins/
│   ├── harbor-hub/
│   └── tastytrade/
└── skills/
    └── parallel-agent-isolation/
```

Plugins live under `plugins/`, one directory each, named for the platform they talk to rather than for being an MCP server. Skills and other components get their own top-level directories as they arrive.

Each plugin directory is self-contained: its own `README.md` covers install, credentials, tests, and tools. CI runs per subdirectory via `paths` filters, so a change to one never runs another's suite.
