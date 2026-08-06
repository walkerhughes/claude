# Evals

The server is evaluated at the agent-loop level, where it actually runs: Claude Code
drives the tools over a set of tasks using the
[Harbor](https://github.com/laude-institute/harbor) framework, and each trial records
reward, tool calls, tokens, and latency.

Every task runs against the mock FRED API in `tests/fixtures/fred_api.py`, so the answers
are fixed and reproducible and no run touches the real API or spends a real key. That is
not only a safety property: FRED publishes new observations every month and revises old
ones, so a gate scored against live data would fail on the day CPI comes out.

The fast deterministic checks for argument correction and error guidance live alongside
the unit tests, in `tests/unit/test_schemas.py` and `tests/unit/test_dates.py`.

## Layout

```
evals/
  environment/
    Dockerfile            # python, uv, the server checkout, rewardkit
    scripts/              # require-local-api, start-mock, mcp-server
  tasks/<name>/
    task.toml             # task config
    instruction.md        # the prompt the agent sees
    tests/test.sh         # verifier: `rewardkit /tests`
    tests/outcome/check.py  # reward 1: the answer is right
    tests/process/check.py  # reward 2: it came through the MCP server
    solution/solve.sh     # oracle, writes the known-correct answer
  job.yaml                # runs the agent over every task
  generate_tasks.py       # regenerates the tasks from the fixtures
  check_reward.py         # gates a harbor result.json on its rewards
  explain_trials.py       # names each trial and dumps the tool calls behind a failure
  validate_local.sh       # scores every verifier without Harbor or a model
  validate_in_container.sh  # the reward matrix it asserts
```

## Tasks (10)

One per meaningful capability, covering all five tools.

| Task | Tool | Asks for |
|---|---|---|
| `unemployment-latest` | `get_observations` | the latest UNRATE value |
| `inflation-yoy` | `get_observations` | CPI year-over-year, which means `units=pc1` |
| `rate-history-max` | `get_observations` | the highest value a long daily series ever reached |
| `gdp-peak-unemployment` | `get_observations` | UNRATE on the date GDPC1 peaked, so two series on one index |
| `initial-print` | `get_revisions` | GDP as first published, before revision |
| `revision-count` | `get_revisions` | how many observations have been revised |
| `next-release` | `get_release_calendar` | the next scheduled Employment Situation date |
| `release-series-count` | `search_series` | how many monthly series a release publishes |
| `series-units` | `get_series` | the units of a series, as text |
| `find-series-id` | `search_series` | the canonical ID for a described series |

**`rate-history-max` is the one that earns its keep.** The daily fixture puts its true
maximum on a single day at an index the downsampler does not sample, so:

```
summary max                     300.0
highest point actually returned 199.96
```

An agent that reads the returned points is wrong by a hundred, and the tolerance is 0.01.
The task is the central claim of `get_observations`, that the summary covers every
observation while the points are only a sample, turned into pass or fail.
`tests/integration/test_observations.py::test_the_extremes_are_not_in_the_returned_points`
fails if a fixture change ever makes the peak reachable from the points again, which is
how an earlier version of the fixture quietly made this task prove nothing.

Nothing in the tasks is hand-typed. `generate_tasks.py` computes every expected answer
from the fixtures by running the same shaping code the server uses, so a task can never
disagree with the data the agent sees. Regenerate after changing a fixture:

```bash
python evals/generate_tasks.py
```

`next-release` is the exception to "fixed answers", and deliberately. The fixture places
release dates relative to the current day, because a calendar whose whole job is "what
came out and what is next" stops straddling today the moment a hard-coded date ages. Its
check and its oracle both compute the expected date at run time, and the check accepts
today's and yesterday's answer, since a trial that starts before midnight is graded after
it.

## Two rewards per task

Every task scores `outcome` and `process`, both computed by
[rewardkit](https://pypi.org/project/harbor-rewardkit/) from the subdirectories of
`tests/`.

`outcome` is the answer. `process` is whether it came through the plugin.

The split is not theoretical. A tastytrade gate run produced a perfect answer without
ever calling a tool: it searched for the MCP tools, never called them, read the mock's
source off disk, and drove the backend with `urllib`. `outcome` alone scored that 1.0.

This plugin has **three** ways round the server rather than tastytrade's two, and
`process` has to see all of them:

| Route | Why it is reachable | How it is caught |
|---|---|---|
| The local mock's port | the server needs a backend | matched on `:8080`, not on a hostname. The mock binds every interface, so it answers on `localhost`, `127.0.0.1`, `0.0.0.0`, `[::1]` and the container's own name; naming two of those lets the other three through |
| The fixtures on disk | they hold every expected answer in plain Python | matched on the module name |
| The real FRED API | `network_mode: public` is required for the agent to reach its own model | matched on the API hostname |

The third is new relative to tastytrade, whose mock-only setup never had to consider it.
It is also why `require-local-api` exists: the server refuses to start unless
`FRED_BASE_URL` points at localhost, so a benchmark run cannot spend a developer's real
key even if one leaked into the environment.

A delegated call counts, and seeing it takes a second source. `trajectory.json` holds the
main session only: harbor's session scan drops any jsonl whose path contains a
`subagents/` component, which is exactly where Claude Code writes a subagent's transcript.
So the checks read the raw session transcripts under `/logs/agent/sessions` as well, and
stop caring who placed the call. Whether the top-level agent called the tool or routed it
through a delegate is the harness's decision, not a fact about this plugin.

That has to cut both ways. Crediting a delegated MCP call while missing a delegated `curl`
would turn "ask a subagent" into an invisible bypass, so the bypass criterion reads the
same union, and the reward matrix asserts both directions.

Both checks fail closed. No trajectory means no evidence the intended route was taken, so
`process` is 0. That is why the oracle scores `outcome=1, process=0`: it is a shell
script, not an agent, and cannot call tools.

Every task prompt states the rule `process` scores, including the paragraph explaining
that an MCP tool with a deferred schema is loaded with `ToolSearch` and then called
directly. That paragraph is inherited from tastytrade, where four gate trials failed the
same way: each opened with `ToolSearch`, loaded a schema, and then never called the tool,
one of them running `Bash: mcp__tastytrade__get_option_chain ...` as a shell command until
it timed out. The confusion was never about which tool or which arguments; it was about
how to invoke an MCP tool at all.

The wording avoids the port, the fixture module name, and the API hostname the bypass
check greps for, so that an agent echoing its instructions into a shell comment cannot
fail the check by quoting it.

## Check the verifiers without Harbor

`validate_local.sh` scores every task's real verifier against seven synthetic
trajectories and asserts the whole reward matrix. No model, no Harbor, no API key:

| case | answer | trajectory | outcome | process |
|---|---|---|---|---|
| solved | oracle | called an MCP tool | 1 | 1 |
| empty | none | none | 0 | 0 |
| bypassed-port | oracle | curled the local mock | 1 | 0 |
| bypassed-fixture | oracle | read the fixtures off disk | 1 | 0 |
| bypassed-real | oracle | curled the real FRED API | 1 | 0 |
| delegated | oracle | subagent called an MCP tool | 1 | 1 |
| delegated-bypass | oracle | subagent curled the local mock | 1 | 0 |

The bypass rows are the point, and they are what `harbor run -a oracle` cannot tell you.
One spelling of a bypass proves only that one spelling is caught, so `bypassed-port`
deliberately uses `0.0.0.0`, the address a hostname list would miss.

```bash
make validate-tasks
# 70 passed, 0 failed
```

It runs in the bench image rather than on the host, because rewardkit scores these checks
and does not build on macOS (its litellm dependency wants a newer rustc than ships there).
Using the same image CI uses also means the verifier under test is the one that will
really grade a gate run, so **this needs Docker**.

## Run it

Harbor must run with `evals/` as the working directory, because it resolves the dataset
path relative to where it is invoked. The `make` targets handle that, so run them from the
plugin root:

```bash
export CLAUDE_CODE_OAUTH_TOKEN=...   # claude setup-token
make benchmark-build    # docker build -f evals/environment/Dockerfile -t fred-bench .
make benchmark          # cd evals && harbor run -c job.yaml
make benchmark-view     # cd evals && harbor view jobs
```

Each task carries a one-line `environment/Dockerfile` (`FROM fred-bench`). Harbor only
discovers a directory as a task if it has an `environment/`, so this is required even
though the task also sets `docker_image`.

The image copies the working tree rather than cloning a ref, so a run measures the code
you have checked out. Rebuild after changing the server.

## The merge gate

`make validate-tasks` and `make evals` answer different questions, and CI runs both.
`validate-tasks` proves each verifier accepts its oracle and rejects every bypass, with no
model involved, which catches a broken verifier. `make evals` drives all 10 tasks with the
real claude-code agent and fails unless every reward is 1.0, which is the only thing that
catches a server an agent cannot actually drive.

The gate authenticates with `CLAUDE_CODE_OAUTH_TOKEN` so runs bill to a Claude
subscription rather than API credits. It deliberately does **not** accept
`ANTHROPIC_API_KEY`: with a key present the CLI prefers it over the token, which either
moves the run onto credits silently or, if the key is empty, 401s every trial before
spending a token.

Every gate run uploads to the Harbor hub as **`ci-evals-fred`**, one job per CI run
holding all 10 tasks as trials, following the repo-wide `ci-evals-<plugin>` convention.

```bash
export CLAUDE_CODE_OAUTH_TOKEN=...   # claude setup-token
make evals                           # add HARBOR_API_KEY and EVALS_UPLOAD=1 to upload
```

### When it fails

The gate prints each trial by name with its rewards, and for any trial that lost
`process`, the tool calls the agent made, MCP ones unmarked and everything else flagged
`!`. That list *is* the `process` score, so it is usually the whole diagnosis:

```
== inflation-yoy: outcome=1.0, process=0.5
   3 tool call(s), 1 through the MCP server:
   ! Bash {"command": "curl -s http://0.0.0.0:8080/fred/series/observations?series_id=CPIAUCSL"}
     mcp__fred__get_series {"series_ids": ["CPIAUCSL"]}
```

## Safety

The agent never sees a real credential. The image sets `FRED_BASE_URL` to the local mock
and a throwaway key, and `require-local-api` refuses to start the server unless
`FRED_BASE_URL` points at localhost. The API is read-only in any case, so there is nothing
a benchmark run could change even if it did reach the real service.

The mock runs in the container as a background process that the server wrapper starts on
first use, so the benchmark is not tied to the local Docker provider the way a
multi-container setup would be. It is a stdlib HTTP server over the same `route()`
function the unit tests drive through an httpx transport, so the benchmark and the test
suite cannot disagree about what FRED returns.
