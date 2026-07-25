# mcps

A collection of [Model Context Protocol](https://modelcontextprotocol.io) servers that give agents like [Claude Code](https://docs.anthropic.com/en/docs/claude-code) direct access to external services. Each server lives in its own subdirectory with its own setup, tests, and docs.

| Server | What it connects to | Plugin |
|--------|---------------------|--------|
| [`tastytrade-mcp`](tastytrade-mcp/) | The [TastyTrade Open API](https://developer.tastytrade.com/getting-started/): brokerage account, market data, and order management (12 tools). | not yet |
| [`harbor-mcp`](harbor-mcp/) | The [Harbor](https://www.harborframework.com) hub: evaluation jobs, trials, uploads, and published packages. | yes |

## Install as a Claude Code plugin

This repo is also a plugin marketplace. Run these as two separate commands, not as one paste: the first opens a prompt that expects only the `owner/repo`.

```
/plugin marketplace add walkerhughes/mcps
```

```
/plugin install harbor-mcp
```

Plugins require [`uv`](https://docs.astral.sh/uv/) on your PATH. The first launch builds the server's environment, so give it a moment before the tools appear. See each server's README for credentials.

## Design

These servers follow Honeycomb's [MCP, easy as 1-2-3](https://www.honeycomb.io/blog/mcp-easy-as-1-2-3) guidance: a few curated tools built around real questions rather than raw API endpoints, responses shaped for a model instead of a UI, and typed schemas that steer the model toward valid calls.

## Layout

Each server is self-contained. Its own `README.md` covers how to install and configure it for Claude Code, run its tests, and use its tools.

```
mcps/
├── tastytrade-mcp/
└── harbor-mcp/
```
