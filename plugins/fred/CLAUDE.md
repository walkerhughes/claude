# fred

MCP server over the St. Louis Fed's FRED API: search series, pull several onto
one date index with server-side transformations, read revision history, and
check the release calendar.

Repo-wide plugin and eval conventions live in the root `CLAUDE.md`. This file is
the plugin-specific part.

## Resources

| What | Where |
| --- | --- |
| **FRED API reference**, every endpoint and parameter | https://fred.stlouisfed.org/docs/api/fred/ |
| Mint an API key | https://fredaccount.stlouisfed.org/apikeys |
| Harbor framework source | https://github.com/harbor-framework/harbor |
| **rewardkit**, how verifiers and criteria are defined | https://www.harborframework.com/docs/rewardkit |
| rewardkit on PyPI (`harbor-rewardkit`) | https://pypi.org/project/harbor-rewardkit/ |
| uv | https://docs.astral.sh/uv/ |

`github.com/laude-institute/harbor` is the old URL and 301-redirects to the
`harbor-framework` one above. Use the new one.

Series documentation on FRED links out to the source agency, which is where the
real definitions live: [CPI](https://www.bls.gov/cpi/) and
[CES](https://www.bls.gov/ces/) for the BLS series this plugin is most often
pointed at. Units and seasonal adjustment come from the agency, not from FRED,
and `get_series` surfacing them is the point. Note that bls.gov returns 403 to
automated fetches, so a dead-link check will flag it and be wrong.

The rewardkit page is the one to read before touching anything under `evals/`.
The rule that bites is that **every criterion in a reward directory aggregates by
weighted mean**, so an extra criterion silently dilutes the others rather than
adding a check.

## Commands

```
make check           lint + typecheck + selftest + unit tests
make lint            ruff check + ruff format --check
make format          apply formatting
make coverage        unit + integration with the coverage threshold
make validate-tasks  score every verifier against its oracle and the bypasses
make mock-api        run the mock FRED API locally
make evals           the merge gate: a real agent over all 10 tasks
```

`validate-tasks` runs in the bench image rather than on the host, because
rewardkit does not build on macOS (its litellm dependency wants a newer rustc
than ships there). **It needs Docker.**

## What is specific here

**Credentials.** A FRED API key, stored only at
`~/.fred-mcp/credentials.json` on the user's machine. `/fred:auth` writes it.
Never read it into a prompt or a log.

**Tasks are generated, not hand-typed.** `evals/generate_tasks.py` computes
every expected answer from the mock fixtures by running the same shaping code
the server uses, so a task can never disagree with the data the agent sees.
Change a fixture, then regenerate:

```bash
python evals/generate_tasks.py
```

Edit the generator, not the individual `check.py` files. They say so at the top.

**Three bypass routes, not one.** Unlike tastytrade's mock-only setup, these
evals run with the network up, because the agent needs it to reach its own
model. So `outcome` can be satisfied by the mock API on its local port, by the
fixtures on disk, *or* by the real FRED API. The `process` check's bypass regex
covers all three, and matches on the port rather than a hostname list: the mock
binds every interface, so naming two spellings lets the rest through.
