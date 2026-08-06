# claude

My [Claude Code](https://docs.anthropic.com/en/docs/claude-code) setup: the tooling I build for it, and the configuration I carry between machines. This repo doubles as a [plugin marketplace](https://code.claude.com/docs/en/plugin-marketplaces), so anything here that ships as a plugin can be installed directly.

Formerly `walkerhughes/mcps`, back when it only held MCP servers.

## MCP servers

[Model Context Protocol](https://modelcontextprotocol.io) servers that give agents direct access to external services. Each lives in its own subdirectory with its own setup, tests, and docs.

| Server | What it connects to | Plugin |
|--------|---------------------|--------|
| [`fred`](plugins/fred/) | The [FRED API](https://fred.stlouisfed.org/docs/api/fred/): the St. Louis Fed's economic time series, plus revision history and the release calendar (5 tools, and `/fred:auth` to store your key). | yes |
| [`harbor-hub`](plugins/harbor-hub/) | The [Harbor](https://www.harborframework.com) hub: evaluation jobs, trials, uploads, and published packages. | yes |
| [`tastytrade`](plugins/tastytrade/) | The [TastyTrade Open API](https://developer.tastytrade.com/getting-started/): brokerage account, market data, and order management (12 tools). | not yet |

They follow Honeycomb's [MCP, easy as 1-2-3](https://www.honeycomb.io/blog/mcp-easy-as-1-2-3) guidance: a few curated tools built around real questions rather than raw API endpoints, responses shaped for a model instead of a UI, and typed schemas that steer the model toward valid calls.

## Skills

Plugins that ship [skills](https://code.claude.com/docs/en/skills) instead of a server. Nothing to connect and no credentials to hold.

| Plugin | Skills | What it does |
|--------|--------|--------------|
| [`persona`](plugins/persona/) | `humanoid`, `learn` | Write in your own voice. `humanoid` is plain-language guidance that applies the moment it is installed. `learn` runs a local labeling loop over your own writing and generates a third skill, `me`, which is the one that translates into your voice. |

`me` is generated rather than shipped, because it can only be written from your writing. The loop behind `learn` is generator/discriminator: Claude drafts `me` from writing you label, isolated subagents use only that skill to produce candidate passages, and you judge them blind against your real writing. It stops once Claude passes as you three times. Everything runs on `127.0.0.1` against files already on disk, so no writing is uploaded and the subagents never see the corpus.

## Install a plugin

Run these as two separate commands, not as one paste: the first opens a prompt that expects only the `owner/repo`.

```
/plugin marketplace add walkerhughes/claude
```

```
/plugin install harbor-hub
```

The non-interactive equivalents below are more reliable, and are the only way to move an existing install to a new version.

MCP server plugins require [`uv`](https://docs.astral.sh/uv/) on your PATH. The first launch builds the server's environment, so give it a moment before the tools appear. See each server's README for credentials. Skill-only plugins have no such setup: `persona` needs nothing beyond the `python3` already on your system.

### Updating

Merging to `main` publishes: the marketplace *is* this repo. What each machine then needs is a refresh of its cached copy, which is one command:

```bash
claude plugin marketplace update walkerhughes
```

Until that runs, a newly added plugin is invisible locally, however many times you try to install it. After it, the two cases differ:

```bash
claude plugin install fred@walkerhughes
```

```bash
claude plugin update tastytrade@walkerhughes
```

Use `install` for a plugin you do not have yet, `update` for one you already have. `install` no-ops on an existing plugin rather than upgrading it, which reads as "nothing happened" rather than as an error.

Then **restart Claude Code**. A plugin change needs a full restart, not just an `/mcp` reconnect.

### Shipping a plugin change

**Bump `version` in the plugin's `.claude-plugin/plugin.json` in the same PR.** Claude Code extracts an installed plugin to a cache path keyed by that version, so if it does not change, the cache is never refreshed and users keep running the old code however many times they update or reinstall. The change is invisible rather than broken. The `plugin version` workflow enforces this.

## Layout

```
claude/
├── .claude-plugin/          # marketplace manifest
└── plugins/
    ├── fred/
    ├── harbor-hub/
    ├── persona/
    └── tastytrade/
```

Plugins live under `plugins/`, one directory each, named for the platform they talk to or the thing they do rather than for being an MCP server. A plugin is the unit Claude Code installs, so skills ship inside one too rather than as a loose directory.

Each plugin directory is self-contained: its own `README.md` covers install, credentials, tests, and tools. CI runs per subdirectory via `paths` filters, so a change to one never runs another's suite.
