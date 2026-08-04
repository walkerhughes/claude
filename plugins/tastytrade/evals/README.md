# Evals

The server is evaluated at the agent-loop level: Claude Code drives the tools over a set of
tasks using the [Harbor](https://github.com/laude-institute/harbor) framework, and each trial
records reward, tool calls, tokens, and latency.

This used to run two agents, a baseline ref and a candidate ref, to show the refactored server
beat the plain endpoint-wrapper baseline. That refactor landed on main and the candidate branch
was deleted, which left the image cloning a ref that no longer existed. There is no second side
to compare against now, so the job runs one server and the evals serve as a regression gate.

Every task runs against the mock Tastytrade API in `tests/fixtures/mock_api`, so the answers
are fixed and reproducible and no run touches a real account or live market data. The fast
deterministic checks for argument correction and error guidance live alongside the unit tests,
in `tests/unit/test_misuse_evals.py`.

## Layout

```
evals/
  environment/
    Dockerfile            # python, uv, the server checkout, the skill, the mock API
    scripts/              # require-local-api, start-mock, mcp-server
  tasks/<name>/
    task.toml             # task config
    instruction.md        # the prompt the agent sees
    tests/test.sh         # verifier: `rewardkit /tests`
    tests/outcome/check.py  # reward 1: the answer is right
    tests/process/check.py  # reward 2: it came through the MCP server (or the skill)
    solution/solve.sh     # oracle, writes the known-correct answer
  job.yaml                # runs the agent over every task
  generate_tasks.py       # regenerates the tasks from the fixtures
  check_reward.py         # gates a harbor result.json on its rewards
  explain_trials.py       # names each trial and dumps the tool calls behind a failure
  validate_local.sh       # scores every verifier without Harbor or a model
  validate_in_container.sh  # the reward matrix it asserts
```

## Tasks (13)

Ten tasks ask for a single number (portfolio P/L, largest drawdown, ATM strike, IV rank,
total fees, net cash, latest dividend, net liquidating value, position count, and the fees on
a previewed vertical spread). One asks for the symbols in a watchlist. One asks the agent
to place an order, and its verifier reads the order the mock recorded rather than a file the
agent wrote.

The last, `earnings-implied-move`, is the only one that exercises a skill rather than the MCP
tools. It points the agent at the option chain that `earnings-calendars` ships and asks for the
implied expected earnings move, which is 10.52% for that chain. The prompt names neither the
skill nor the script, so it measures whether the agent recognises an earnings-vol question and
reaches for the right tool. The image installs the skill at `/root/.claude/skills` so the normal
trigger path is live.

Nothing in the tasks is hand-typed. `generate_tasks.py` computes every expected answer from
the mock fixtures by running the same shaping code the server uses, so a task can never
disagree with the data the agent sees. The skill task follows the same rule: its answer comes
from importing `scripts/calendars.py` and fitting the shipped chain. The two anchor values are
a total unrealized P/L of +$700 and an SPY ATM strike of 200. Regenerate after changing a
fixture:

```bash
python evals/generate_tasks.py
```

## Run it

Harbor must run with `evals/` as the working directory, because it resolves the dataset path
relative to where it is invoked. The `make` targets handle that for you, so run them from the
repo root:

```bash
export ANTHROPIC_API_KEY=...
make benchmark-build    # docker build -f evals/environment/Dockerfile -t tastytrade-bench .
make benchmark          # cd evals && harbor run -c job.yaml
make benchmark-view     # cd evals && harbor view jobs
```

Or run Harbor directly, from inside `evals/`. Call it through `uv` and pin the version the
tasks were validated against, so it doesn't depend on what's on your PATH:

```bash
docker build -f evals/environment/Dockerfile -t tastytrade-bench .
cd evals
uv tool run --from "harbor==0.18.0" harbor run -c job.yaml
uv tool run --from "harbor==0.18.0" harbor view jobs
```

Each task carries a one-line `environment/Dockerfile` (`FROM tastytrade-bench`). Harbor only
discovers a directory as a task if it has an `environment/`, so this is required even though
the task also sets `docker_image`. `make benchmark-build` creates the `tastytrade-bench` image
they inherit.

The tasks reference the image by name (`docker_image = "tastytrade-bench"`), so build it
before the first run. Each trial's `result.json` records the reward, the phase timings, and
the token and cost totals, so success rate, tokens, tool calls, and latency come straight out
of the job directory.

The image copies the working tree rather than cloning a ref, so a run measures the code you
have checked out. Rebuild after changing the server or the skill.

## Two rewards per task

Every task scores `outcome` and `process`, both computed by
[rewardkit](https://pypi.org/project/harbor-rewardkit/) from the subdirectories of
`tests/`.

`outcome` is the answer. `process` is whether it came through the plugin.

The split is not theoretical. The mock brokerage listens on `localhost:8080` inside the
container and its source sits in the checkout, so an agent can produce a perfect answer
without ever calling a tool, and a real gate run did exactly that: it searched for the MCP
tools, never called them, read `mock_api/app.py` off disk, and drove the REST API with
`urllib`. `outcome` alone scored that 1.0. `process` is what makes these MCP evals rather
than answer-matching.

For the twelve tool tasks, `process` asks that a `mcp__tastytrade__*` tool was called and
that nothing reached the mock brokerage directly. "Directly" is matched on the mock's port
rather than on a list of hostnames: it binds every interface, so it answers on `localhost`,
`127.0.0.1`, `0.0.0.0`, `[::1]`, and the container's own name, and naming two of those let
the other three through. Nothing else in the image listens on that port.

For `earnings-implied-move` `process` asks that the skill or its script was used, since an
agent that eyeballs the straddle can land close enough to pass `outcome` without loading
the skill, and an early run did.

A delegated call counts, and seeing it takes a second source. `trajectory.json` holds the
main session only: harbor's session scan drops any jsonl whose path contains a `subagents/`
component, which is exactly where Claude Code writes a subagent's transcript. So a call the
agent hands to a delegate leaves an `Agent` entry and no tool, and two trials fetched the
right answer that way. The checks therefore read the raw session transcripts under
`/logs/agent/sessions` as well, and stop caring who placed the call: whether the top-level
agent called the tool or routed it through a delegate is the harness's decision, not a fact
about this plugin, and the gate's question is whether a real agent can drive the server.

That has to cut both ways. Crediting a delegated MCP call while missing a delegated `curl`
would turn "ask a subagent" into an invisible bypass, so the bypass criterion reads the same
union, and `validate_local.sh` asserts both directions.

Every task prompt states the rule `process` scores, and each paragraph of it is there
because a gate run failed without it. The first run under the split scored `outcome` 1.0
on all thirteen tasks and lost `process` on six, with every prompt saying only "use the
Tastytrade MCP tools" and putting nothing out of bounds. Saying it explicitly fixed two of
the six. The remaining four all failed the same way, and it was not the way anyone
expected: each opened with `ToolSearch {"query": "tastytrade"}` and then never called a
tool. One ran `Bash: mcp__tastytrade__get_option_chain --symbol SPY ...` as a shell
command. Two delegated. `preview-vertical-spread` spent 44 calls trying to reach the MCP
over a socket, a subprocess, and an SDK import, having already loaded the schema, and hit
the agent timeout -- which took `outcome` down with it, 1.0 to 0.0.

So the confusion was never about which tool or which arguments. It was about how to invoke
an MCP tool at all when its schema is deferred rather than listed, and the prompt now says:
load it with `ToolSearch`, then call it like any other tool, and no shell command or Python
import can substitute.

The wording avoids the host, port, and module name the bypass check greps for, so that an
agent echoing its instructions into a shell comment cannot fail the check by quoting it.

Both checks fail closed. No trajectory means no evidence the intended route was taken, so
`process` is 0. That is why the oracle scores `outcome=1, process=0`: it is a shell script,
not an agent, and cannot call tools.

## The merge gate

`make validate-tasks` and `make evals` answer different questions, and CI runs both.
`validate-tasks` proves each verifier accepts its oracle and rejects an empty answer, with no
model involved, which catches a broken verifier. `make evals` drives all 13 tasks with the
real claude-code agent and fails unless every reward is 1.0, which is the only thing that
catches a server or skill an agent cannot actually drive.

The gate authenticates with `CLAUDE_CODE_OAUTH_TOKEN` so runs bill to a Claude subscription
rather than API credits. It deliberately does **not** accept `ANTHROPIC_API_KEY`: with a key
present the CLI prefers it over the token, which either moves the run onto credits silently or,
if the key is empty, 401s every trial before spending a token. `job.yaml` used to declare the
key for exactly this reason and no longer does.

Every gate run uploads to the Harbor hub as **`ci-evals-tastytrade`**, one job per CI run
holding all 13 tasks as trials. That follows the repo-wide `ci-evals-<plugin>` convention, so
every plugin's CI history is searchable together instead of hiding behind a generic job name.

PR runs upload too. Restricting uploads to main left a PR gate with nothing on the hub, so the
only record was a CI artifact that expires after 7 days.

```bash
export CLAUDE_CODE_OAUTH_TOKEN=...   # claude setup-token
make evals                           # add HARBOR_API_KEY and EVALS_UPLOAD=1 to upload
```

### When it fails

The gate prints each trial by name with its rewards, and for any trial that lost `process`,
the tool calls the agent made, MCP ones unmarked and everything else flagged `!`. That list
*is* the `process` score, so it is usually the whole diagnosis:

```
== dividend-lookup: outcome=1.0, process=0.5
   3 tool call(s), 1 through the MCP server:
   ! Bash {"command": "curl -s http://0.0.0.0:8080/market-metrics"}
     mcp__tastytrade__get_market_data {"symbols": ["AAPL"], "include": ["dividends"]}
```

It used to `cat` the verifier output instead, which printed thirteen anonymous pairs of
numbers: you could see that six tasks lost `process` and not which six. Recovering that
meant downloading the CI artifact, which expires after seven days.

## Check the verifiers without Harbor

`validate_local.sh` scores every task's real verifier against six synthetic trajectories
and asserts the whole reward matrix. No model, no Harbor, no API key:

| case | answer | trajectory | outcome | process |
|---|---|---|---|---|
| solved | oracle | took the intended route | 1 | 1 |
| empty | none | none | 0 | 0 |
| bypassed | oracle | went round the server | 1 | 0 |
| bypassed-alt | oracle | went round it another way | 1 | 0 |
| delegated | oracle | subagent took the intended route | 1 | 1 |
| delegated-bypass | oracle | subagent went round the server | 1 | 0 |

The bypass rows are the point, and they are what `harbor run -a oracle` cannot tell you.
`bypassed-alt` exists because one spelling of a bypass proves only that one spelling is
caught: it reaches the mock on an address the first check's hostname list did not name, and
for the skill task it does the arithmetic inline, which leaves no distinctive string at all.

The `delegated` pair covers the blind spot behind it, and both halves have to be asserted
together: crediting a delegated MCP call while missing a delegated `curl` would make "ask a
subagent" an invisible bypass, which is worse than not looking at all.

```bash
make validate-tasks
# 78 passed, 0 failed
```

It runs in the bench image rather than on the host, because rewardkit scores these checks
and does not build on macOS (its litellm dependency wants a newer rustc than ships there).
Using the same image CI uses also means the verifier under test is the one that will really
grade a gate run, so **this needs Docker**.

Writing it paid for itself immediately: it caught two bugs in the first draft of the process
checks. An empty run scored 0.5 because "did not bypass the server" is vacuously true when
there are no tool calls at all, and the skill check matched the reference chain's own file
path, which contains the skill's name, so merely reading the input counted as using the
skill.

## Safety

The agent never sees real credentials. The image sets `API_BASE_URL` to the local mock and
uses throwaway credentials, and `require-local-api` refuses to start a server unless
`API_BASE_URL` points at localhost. Even the order-placement task only reaches the mock, which
records the order to a file the verifier reads.

The mock runs in the container as a background process that the server wrapper starts on first
use, so the benchmark is not tied to the local Docker provider the way a multi-container setup
would be. `network_mode: public` is set so the agent can reach the Anthropic API; the
Tastytrade calls stay on localhost.
