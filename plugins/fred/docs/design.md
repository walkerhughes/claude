# FRED MCP server design

The design follows the Honeycomb MCP write-up
[*"MCP, Easy as 1-2-3?"*](https://www.honeycomb.io/blog/mcp-easy-as-1-2-3): a small set of tools
shaped for a model rather than one wrapper per REST endpoint. FRED has 31 endpoints, and wrapping
each one produces a server that is complete and unusable.

- **Observations are mostly padding.** Every observation arrives as
  `{"realtime_start":"2026-08-05","realtime_end":"2026-08-05","date":"2025-01-01","value":"2.99098"}`.
  On a normal request the two realtime fields hold the same value on every row, and the key names
  repeat once per observation. Twenty years of a daily series is about 5,000 of those.
- **The vocabulary is not guessable.** Year-over-year percent change is `units=pc1`. Monthly
  aggregation is `frequency=m`. Initial-release-only is `output_type=4` *and* requires
  `realtime_start=1776-07-04`. A model that guesses `units=yoy` gets a 400 naming a variable, and
  retries with something worse.
- **Series IDs are opaque.** `CPIAUCSL`, `DFF`, `GDPC1`. Without discovery shaped for a model,
  every question starts with a failed guess.
- **The common question is answered badly.** "Compare unemployment and inflation" is N calls
  returning N separately-dated lists that the model has to join itself.

So: curated tools, argument correction ahead of validation, errors that carry a fix, columnar
responses, and summaries computed on the server.

## Tools

| Tool | Covers | Endpoints folded in |
|---|---|---|
| `search_series(query, release_id, category_id, ...)` | Discovery. One output shape, three paths. Ordered by popularity. | `/series/search`, `/release/series`, `/category/series` |
| `get_series(series_ids, include=[...])` | One snapshot per series: metadata, notes, release, categories, tags. | `/series`, `/series/release`, `/series/categories`, `/series/tags` |
| `get_observations(series_ids, start, end, units, frequency, ...)` | 1..N series on one date index, downsampled, with a per-series summary. | `/series/observations` |
| `get_revisions(series_id, observation_date)` | What a number was first reported as, and every revision since. | `/series/observations` with `output_type=2`/`4`, `/series/vintagedates` |
| `get_release_calendar(start, end, release_id)` | What just came out and what is next. | `/releases/dates`, `/release/dates`, `/release` |

Deliberately out: the Maps/GeoFRED endpoints (a different product), tag and category tree
browsing (search covers the reachable ground), and `/sources` (metadata about metadata).

`search_series` folds three endpoints into one tool because the answer is identical in all three
cases: a list of series. Splitting them would make a model choose between tools that return the
same thing.

## Architecture

FastMCP's successor `MCPServer` (mcp 2.x), Python 3.13, httpx, stdio, and Pydantic.

```
src/
  server.py     # MCPServer setup, instructions, version from plugin.json
  client.py     # key resolution, request signing, 429/5xx backoff
  schemas.py    # Pydantic argument schemas: correct, then validate
  dates.py      # relative and partial dates -> YYYY-MM-DD
  shaping.py    # trimming, columnar alignment, summaries, downsampling, vintages
  errors.py     # @guarded_tool
  tools.py      # the five tools
  log.py        # stderr logging (stdout is the MCP channel)
```

Smaller than the tastytrade server because there is no token refresh, no write path to gate, and
no local pagination to serve.

- The Pydantic schemas do two jobs, in the order that matters. A `model_validator(mode="before")`
  rewrites the arguments a model plausibly writes into the ones FRED accepts, and a `mode="after"`
  validator rejects what is left with a message that names the fix.
- `errors.py` wraps every tool with `@guarded_tool`, returning `{error, suggestions}` and never a
  traceback. FRED puts the real reason in the body rather than the status, so a missing series and
  a bad `units` code are both HTTP 400 and only `error_message` tells them apart. The suggestions
  key off the body.
- `log.py` writes to stderr, since stdout is the JSON-RPC channel. It also pins httpx to WARNING:
  httpx logs the full request line at INFO and FRED takes the API key as a **query parameter**, so
  at INFO the key is written to stderr on every call.

## The correction layer

Not politeness. Every input below is unambiguous, and every one of them is a 400 without this.

**Units.** The most-asked transformation in economics is year-over-year percent change, and FRED
spells it `pc1`.

| A model writes | Sent |
|---|---|
| `yoy`, `year over year`, `percent change from a year ago`, `inflation` | `pc1` |
| `percent change`, `pct_change`, `mom` | `pch` |
| `change`, `diff` | `chg` |
| `change from a year ago` | `ch1` |
| `annualized`, `saar` | `pca` |
| `level`, `levels`, `raw`, `none`, `""` | `lin` |
| `natural log`, `ln` | `log` |

The response echoes `units` with a plain-English `units_meaning`, so the numbers are not left to
be interpreted.

**Dates.** FRED wants `YYYY-MM-DD`. Also accepted: `2020`, `2020-01`, `5y`, `18 months`,
`last 10 years`, `ytd`, `today`. Calendar arithmetic is done without a dependency and clamps
correctly: three months before 31 May is 28 February, and a year before 29 Feb 2024 is 28 Feb
2023. An impossible date and a backwards range are caught locally rather than at the API.

**Frequency and seasonal adjustment.** `monthly` becomes `m`, `unadjusted` becomes the `nsa` tag.
Note that `frequency="sa"` means *semiannual* while `seasonal_adjustment="sa"` means *adjusted*:
same spelling, different tags, and a test pins it.

**Series IDs.** `unrate`, `"UNRATE, CPIAUCSL"`, `"UNRATE CPIAUCSL"` and `["unrate"]` all become
`["UNRATE", ...]`. FRED IDs are uppercase and it will not meet you halfway.

The argument annotations on `series_ids` and `include` are `list[str] | str` on purpose. The MCP
layer validates against the annotation *before* the tool body runs, so a strict `list[str]` turns
`get_series("UNRATE")` into a raw `ToolError` that never reaches the correction layer, which is
the exact failure the correction layer exists to prevent.

## Response shaping

**Columnar observations.** `{"dates": [...], "values": {"UNRATE": [...]}}` instead of N lists of
four-field objects. Several series share one index, so comparison arrives joined. Where a
quarterly series has no monthly observation the value is `null`, never forward-filled: filling
would invent numbers FRED did not publish. `"."`, FRED's missing marker, becomes `null`, and value
strings become floats.

**Summary before downsampling.** `latest`, `latest_date`, `prior`, `change`, `pct_change`, `min`,
`max`, `mean`, `count` and `observations` are computed over **every** observation. Only the
returned point list is thinned, to evenly spaced samples that always keep the first and last. The
ordering is the whole trick: a summary computed after thinning would quietly report the sample's
range as the series' range, and nothing in the output would look wrong. `points` reports `total`
and `dropped`, so a thinned series is never mistaken for a complete one.

The daily test fixture is built from explicit knots that put the peak and the trough in the
*interior* of the series. With the extremes at the endpoints, which downsampling always keeps, the
test could not tell the two orderings apart.

**Collapsed vintages.** `output_type=2` returns one column per vintage, but a vintage exists for
every publication of the series, not for every change to the observation being asked about. Q3
2025 GDP has nine vintages and one actual revision, so `get_revisions` returns two entries.

**Trimmed series objects.** A FRED series object carries 16 fields, four of which are shorthand
duplicates of another four and one of which (`notes`) runs to paragraphs. `search_series` drops
notes entirely: ten results at full fidelity is a few thousand tokens spent to choose one ID, and
`get_series` serves notes on demand.

## What the curation buys

Measured against the live API, not estimated. Response sizes in characters.

| Question | Endpoint-wrapper baseline | This server |
|---|---|---|
| Fed funds rate now, and its 20-year range | 1 call, **694,388** chars (~5,000 observations; the model finds the extremes) | 1 call, **4,194** chars: 120 points, true min and max in the summary |
| CPI year-over-year vs unemployment since 2015 | 2 calls, **27,758** chars, two unaligned lists to join | 1 call, **6,777** chars, one date index, both summaries |
| Find the unemployment rate series | 1 call, **8,201** chars for 5 results (notes included) | 1 call, **1,835** chars, popularity-ordered |
| What did Q3 2025 GDP first print at? | 1 call that **400s**, then guesswork about the real-time window | 1 call, 9 vintages collapsed to 1 revision |

The DFF row is the headline: 0.6% of the payload, and a *better* answer, because the exact
20-year minimum of 0.04 and maximum of 5.41 are in the summary rather than somewhere in 5,000
rows the model has to scan.

## Errors

Every failure is `{error, suggestions}`. A missing series names `search_series` and reminds that
IDs are uppercase. A vintage failure names `get_revisions`. A frequency failure explains that a
series can only be aggregated to a coarser interval. A rejected key explains where the key is read
from and says never to ask the user to paste one into the chat.

Invalid units, unreadable dates, reversed ranges, and unknown `include` values never reach the API
at all; the tests assert that no request was made.

Per-series isolation: a bad ID among good ones costs only its own entry, because FRED's
`"The series does not exist"` never says *which* series it means, and failing the whole call would
leave a model holding three IDs with no idea which to fix.

## Evals

Unit-level misuse tests (`tests/unit/test_schemas.py`, `test_dates.py`) feed realistic model
mistakes through correction and validation and assert the corrections and the suggestion-bearing
errors. Integration tests drive the registered MCP server against a mock FRED built from trimmed
real captures, so the shaping is asserted against FRED's shapes rather than invented ones. All of
it runs in CI with no key and no network.

There is no Harbor agent-loop benchmark, unlike the tastytrade server. That one exists because
order placement makes a wrong answer expensive; FRED is read-only. A benchmark is worth adding once
the tool surface has settled, and it would measure the table above at the agent loop rather than at
the payload.

## Deferred work

- **A response cache.** FRED allows 120 requests a minute and the data moves slowly, so nothing is
  under pressure. Worth revisiting if an agent starts re-fetching the same series within a turn.
- **Category and tag tree browsing.** `search_series(category_id=...)` reaches any category whose
  ID is known; walking the tree to find one is not covered.
- **Maps/GeoFRED.** Regional data by shape rather than by series.
- **Paging.** Every tool returns a bounded page with FRED's own total. No cursor, because no
  question so far has needed the second page.
