# tastytrade

An MCP server that connects [Claude Code](https://docs.anthropic.com/en/docs/claude-code) to the [TastyTrade Open API](https://developer.tastytrade.com/getting-started/), giving Claude direct access to your brokerage account, market data, and order management.

This lives in the [`claude`](../../) monorepo, consolidated from a standalone repo with full commit history preserved (`git log`/`git blame` resolve inside this directory).

## Features

12 tools, each built around a question a trader actually asks rather than a single REST
endpoint. Responses are trimmed and carry a computed summary, malformed arguments are
corrected where it's safe to, and errors come back with a suggestion instead of a stack
trace.

| Area | Tools |
|---|---|
| Accounts & portfolio | `list_accounts`, `get_portfolio`, `get_portfolio_history` |
| Market data | `search_symbols`, `get_market_data`, `get_option_chain` |
| Activity | `query_transactions`, `list_orders` |
| Trading | `preview_order`, `place_order`, `cancel_order` |
| Watchlists | `get_watchlists` |

- **`get_portfolio`** returns balances, positions, and a P/L rollup in one call.
- **`get_market_data`** is one snapshot covering quote, IV metrics, dividends, earnings, and instrument detail.
- **`get_option_chain`** lists expirations, then returns quote-enriched strikes plus a summary
  (ATM strike, IV range, busiest strikes by volume and open interest).
- **`query_transactions`** fetches once and then pages, searches, and sorts locally, with a cash and fee summary.

Authentication uses the OAuth2 refresh-token flow with automatic token refresh.

### Order safety

`place_order` executes live trades and is gated twice: the server must be started with
`TT_ENABLE_TRADING=true`, **and** each call must pass `confirm=true`. Otherwise the order is not
sent and the previewed effect is returned. Always call `preview_order` first.

## Architecture

The design follows the Honeycomb MCP: a few curated tools, responses shaped for a model rather
than a UI, and schemas that steer the model toward valid calls. See [`docs/design.md`](docs/design.md)
for the full reasoning.

- **Curated tools**, one module per group: [`src/tools/`](src/tools)
- **Response shaping and summaries**, trimmed payloads with computed rollups: [`src/shaping/`](src/shaping)
- **Typed argument schemas** that validate and [auto-correct](src/infra/correction.py) common mistakes: [`src/schemas/`](src/schemas)
- **Guided errors** that return a suggestion instead of a stack trace: [`src/infra/errors.py`](src/infra/errors.py)
- **Caching** with a per-resource TTL that also serves paging, search, and sort in memory: [`src/infra/cache.py`](src/infra/cache.py)
- **Shared pagination** across the list tools: [`src/infra/pagination.py`](src/infra/pagination.py)
- **Structured logging** to stderr, safe for a stdio server: [`src/infra/logging.py`](src/infra/logging.py)
- **Trading safety gate**, an env flag plus a per-call confirm: [`src/config.py`](src/config.py)
- **Deterministic mock API** for tests and evals: [`tests/fixtures/mock_api/`](tests/fixtures/mock_api)
- **Agent-loop evals** through Harbor: [`evals/`](evals)

## Install as a Claude Code plugin

Two separate commands. The first opens a prompt that expects only the `owner/repo`, so do not paste both lines at once:

```
/plugin marketplace add walkerhughes/claude
```

```
/plugin install tastytrade
```

Requires [`uv`](https://docs.astral.sh/uv/) on your PATH. The first launch builds the server's environment, which takes a few seconds before the tools appear.

## Credentials

Unlike Harbor, TastyTrade has no `auth login` command, so this file is created by hand once. Getting the values is the involved part:

1. Register an OAuth application in the TastyTrade developer portal. That yields a **client id** and a **client secret**.
2. Complete the authorization flow for your account to obtain a **refresh token**. This server uses the refresh-token grant, so the refresh token is the long-lived credential; there is no username or password anywhere.

Then write them to `~/.tastytrade-mcp/credentials.json`:

```bash
mkdir -p ~/.tastytrade-mcp && chmod 700 ~/.tastytrade-mcp
touch ~/.tastytrade-mcp/credentials.json && chmod 600 ~/.tastytrade-mcp/credentials.json
```

```json
{
  "client_id": "...",
  "client_secret": "...",
  "refresh_token": "...",
  "base_url": "api.tastyworks.com"
}
```

The environment-variable spellings work too, so a file written from your `.env` needs no renaming:

| Canonical | Also accepted |
|-----------|---------------|
| `client_id` | `TT_CLIENT_ID` |
| `client_secret` | `TT_SECRET` |
| `refresh_token` | `TT_REFRESH` |
| `base_url` | `API_BASE_URL` |

`base_url` is optional and defaults to `api.tastyworks.com`.

There is no username or password: this server authenticates with the OAuth refresh-token grant only. `TT_USERNAME` and `TT_PASSWORD` keys are ignored, so delete them rather than leaving secrets at rest for nothing to read.

**The server refuses to load this file if it is readable by group or others**, and tells you to `chmod 600`. Together the secret and refresh token grant full account access, including order placement when trading is enabled.

### Precedence

| | Source |
|---|--------|
| 1 | `TT_CLIENT_ID`, `TT_SECRET`, `TT_REFRESH` in the environment, when **all three** are set |
| 2 | `~/.tastytrade-mcp/credentials.json` |

Whole-source, not per-field: a file `client_id` paired with an environment `refresh_token` would fail authentication in a way that looks like a revoked token rather than a misconfiguration. A *partially* set environment is a hard error rather than a silent fallthrough to the file, for the same reason.

The environment path exists for CI and scripting. Interactively, use the file.

## Trading gate

Read tools work with any valid credentials. `place_order` refuses unless `TT_ENABLE_TRADING=true` is set in the server environment, and then still requires `confirm=true` on each call. Preview-only is the default; leave it that way unless you intend to place live orders.

## Local development

```bash
uv sync
```

## Example

Once running, you can ask Claude things like:

> "What are my current positions and P&L?"

Claude calls `list_accounts` to find your account number, then `get_portfolio` to fetch balances, positions, and P/L in a single call:

```
User: What are my current positions?

Claude: [calls list_accounts]  returns account XXXXXXXX
        [calls get_portfolio]  returns balances, positions, and a P/L summary

You have 3 open positions:
  AAPL  100 shares   +$320.50 (+2.1%)
  SPY   2 puts       -$45.00  (-8.3%)
  TSLA  5 calls      +$180.00 (+12.5%)

Net liquidating value: $12,345.67
```

You can also ask Claude to analyze option chains, check IV rank across symbols, preview trades before placing them, and manage live orders.

## Development

```bash
make check             # lint + typecheck + unit tests
make test-unit         # unit tests only
make coverage          # tests with coverage report
```

## Project Structure

```
├── src/
│   ├── client.py      # Tastytrade API client (OAuth2 auth, retry, logging)
│   ├── server.py      # FastMCP server: registers the tools
│   ├── config.py      # Env-driven settings (trading gate, cache TTLs)
│   ├── infra/         # errors, cache, correction, pagination, logging
│   ├── schemas/       # Pydantic argument schemas (validation + auto-correction)
│   ├── shaping/       # Response shaping + summary builders
│   └── tools/         # One module per tool group
├── tests/             # Unit and integration tests, plus the mock API fixtures
├── evals/             # Agent-loop eval tasks and the Harbor benchmark
├── docs/design.md     # Technical design doc
├── .mcp.json          # MCP server config for Claude Code
├── .env.example       # Credential template
└── pyproject.toml     # Dependencies and tool config
```
