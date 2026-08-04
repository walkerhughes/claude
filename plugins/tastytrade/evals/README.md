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
    tests/test.sh         # verifier, writes a reward to /logs/verifier/reward.txt
    solution/solve.sh     # oracle, writes the known-correct answer
  job.yaml                # runs the agent over every task
  generate_tasks.py       # regenerates the tasks from the fixtures
  validate_local.sh       # checks every verifier without Harbor or Docker
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
uv tool run --from "harbor==0.13.2" harbor run -c job.yaml
uv tool run --from "harbor==0.13.2" harbor view jobs
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

## Check the verifiers without Harbor

`validate_local.sh` runs each task's oracle (`solve.sh`), then its verifier (`test.sh`), and
confirms the verifier awards a reward of 1. It then feeds an empty answer and confirms the
reward is 0. This is the local stand-in for `harbor run -a oracle`:

```bash
bash evals/validate_local.sh
# 13 passed, 0 failed
```

## Safety

The agent never sees real credentials. The image sets `API_BASE_URL` to the local mock and
uses throwaway credentials, and `require-local-api` refuses to start a server unless
`API_BASE_URL` points at localhost. Even the order-placement task only reaches the mock, which
records the order to a file the verifier reads.

The mock runs in the container as a background process that the server wrapper starts on first
use, so the benchmark is not tied to the local Docker provider the way a multi-container setup
would be. `network_mode: public` is set so the agent can reach the Anthropic API; the
Tastytrade calls stay on localhost.
