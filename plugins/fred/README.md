# fred

An MCP server for the [FRED API](https://fred.stlouisfed.org/docs/api/fred/), the Federal Reserve Bank of St. Louis's economic data service: around 800,000 time series covering prices, employment, output, rates, and trade.

Five tools rather than thirty-one endpoint wrappers. See [docs/design.md](docs/design.md) for why, and for what the curation measurably buys.

## Install

```
/plugin marketplace add walkerhughes/claude
```

```
/plugin install fred
```

The non-interactive equivalents, which are also the only way to move an existing install to a new version:

```bash
claude plugin marketplace update walkerhughes && claude plugin update fred@walkerhughes
```

Needs [`uv`](https://docs.astral.sh/uv/) on your PATH. The first launch builds the server's environment, so give it a moment before the tools appear. A plugin update needs a Claude Code restart, not just an `/mcp` reconnect.

## Credentials

A FRED API key is free, takes a minute, and needs no card: <https://fredaccount.stlouisfed.org/apikeys>.

Put it in either place. The environment wins if both are set.

```bash
export FRED_API_KEY="your32characterlowercasealnumkey"
```

```bash
mkdir -p ~/.fred-mcp && printf '{"api_key": "%s"}\n' "$FRED_API_KEY" > ~/.fred-mcp/credentials.json
```

The key's shape is checked before any request, so a key pasted with a stray quote or capital says so instead of coming back as FRED's message about "the value for variable api_key". The key is never written to a log or an error message.

The API is read-only. There is nothing here that can change your data or spend your money.

## Tools

### `search_series(query, release_id, category_id, limit, frequency, seasonal_adjustment, order_by)`

Find series. Start here: FRED names things `CPIAUCSL` and `DFF`, so guessing does not work.

Supply exactly one of `query` (free text), `release_id` (everything in a publication), or `category_id` (everything in a category). All three return the same shape.

Ordered by popularity, so the canonical series comes first. FRED's own default buries `UNRATE` under hundreds of regional variants.

`frequency` takes words or codes (`"monthly"`, `"m"`, `"quarterly"`, `"annual"`). `seasonal_adjustment` takes `"SA"`, `"NSA"`, `"unadjusted"`, or the full phrase.

### `get_series(series_ids, include)`

What a series measures, in what units, at what frequency, seasonally adjusted or not, covering which period, last updated when. The questions that decide whether a number means what you think it does.

`include` selects how much: `metadata` (default), `notes`, `release`, `categories`, `tags`, or `all`. Up to 20 series per call, and a bad ID among good ones fails only its own entry.

### `get_observations(series_ids, start, end, units, frequency, aggregation_method, max_points)`

The numbers. Several series come back on one shared date index, so a comparison is one call:

```json
{"dates": ["2025-01-01", ...],
 "values": {"UNRATE": [4.0, ...], "CPIAUCSL": [2.99, ...]},
 "summary": {"UNRATE": {"latest": 4.3, "min": 3.4, "max": 14.8, ...}}}
```

`units` transforms server-side, so do not do the arithmetic yourself: `"yoy"` for year-over-year percent change, `"percent change"`, `"change"`, `"annualized"`, `"level"`.

`start` and `end` take `YYYY-MM-DD`, a year (`"2020"`), a year-month (`"2020-01"`), a span back from today (`"5y"`, `"18 months"`), `"ytd"`, or `"today"`.

Every series gets a summary computed over **all** its observations; only the point list is thinned to `max_points`. Twenty years of daily fed funds returns 120 points and still reports the true 20-year minimum and maximum.

### `get_revisions(series_id, observation_date, limit)`

What a number was first reported as, and how it has been revised since.

With `observation_date`, the full revision history of that data point, with repeated vintages collapsed so you see the changes rather than one column per publication. Without one, first-printed against current across recent observations.

The real-time window this needs is set for you. Asking FRED for vintages without it fails with a message about no vintage dates existing, which reads like the series has no history.

### `get_release_calendar(start, end, release_id, limit)`

What economic data just came out, and what is scheduled next, split around today. Defaults to the last 7 days and the next 14.

`release_id` narrows to one publication and closes the discovery loop: this tool gives you release 50, and `search_series(release_id=50)` lists every series the Employment Situation publishes.

## Development

```bash
uv sync
make check           # lint, typecheck, unit tests
make test            # everything
make coverage        # with a report, 80% floor
make validate-tasks  # score every eval verifier against its oracle and each bypass (needs Docker)
make evals           # THE MERGE GATE: drive the tasks with a real agent (needs Docker + a token)
```

Integration tests drive the registered MCP server against a mock FRED built from trimmed real captures. No network and no API key, so the whole suite runs anywhere.

The agent-loop benchmark lives in [`evals/`](evals/): 10 tasks over all five tools, each scoring both whether the answer is right and whether it came through the MCP server rather than round it. See [evals/README.md](evals/README.md).

## Not here

- **Maps / GeoFRED.** A different product with a different shape.
- **Tag and category tree browsing.** `search_series` covers the reachable ground; the tree is a UI affordance.
- **Sources.** Metadata about metadata.
- **A response cache.** FRED allows 120 requests a minute and the data moves slowly, so nothing is under pressure. See the design doc's deferred work.
- **Forward date spans.** `"5y"` means five years ago; a forward window needs an absolute end date.
