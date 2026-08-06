#!/usr/bin/env python3
"""Generate the Harbor benchmark tasks.

Every expected answer is computed here from the mock fixtures by running the same
shaping code the server uses. Nothing is typed in by hand, so a task answer can never
drift away from the data the agent actually sees. Change a fixture in
`tests/fixtures/fred_api.py` and rerun this script to refresh the tasks.

Run: python evals/generate_tasks.py
"""

import json
import os
import stat
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.shaping import align, parse_value, revision_rows, summarize  # noqa: E402
from tests.fixtures import fred_api as fx  # noqa: E402

TASKS_DIR = os.path.join(os.path.dirname(__file__), "tasks")


# --- ground truth, computed from the fixtures ----------------------------------------


def _pairs(rows):
    return [(stamp, parse_value(value)) for stamp, value in rows]


def _latest_unrate():
    return summarize(_pairs(fx.UNRATE_OBS))["latest"]


def _cpi_yoy():
    return summarize(_pairs(fx.transform(fx.CPI_OBS, "pc1")))["latest"]


def _daily_max():
    return summarize(_pairs(fx.DAILY_OBS))["max"]


def _unemployment_at_gdp_peak():
    """Needs both series on one date index, which is what the tool does for you."""
    dates, columns = align({"UNRATE": _pairs(fx.UNRATE_OBS), "GDPC1": _pairs(fx.GDPC1_OBS)})
    gdp = columns["GDPC1"]
    peak = max(range(len(dates)), key=lambda i: (gdp[i] is not None, gdp[i]))
    return columns["UNRATE"][peak]


def _initial_print():
    return dict(_pairs(fx.INITIAL_OBS["GDPC1"]))["2025-01-01"]


def _revised_count():
    rows = revision_rows(_pairs(fx.INITIAL_OBS["GDPC1"]), _pairs(fx.GDPC1_OBS))
    return float(sum(1 for row in rows if row.get("revision")))


def _monthly_series_in_release_50():
    monthly = [s for s in fx.RELEASE_50_SERIES if s["frequency"].lower() == "monthly"]
    return float(len(monthly))


def _gdp_units():
    return fx.GDPC1["units"]


# --- task definitions ----------------------------------------------------------------

# (name, prompt, answer key, value, tolerance)
NUMERIC_TASKS = [
    (
        "unemployment-latest",
        "What is the most recent US unemployment rate (series UNRATE), as a percent?",
        "unemployment_rate",
        _latest_unrate(),
        0.01,
    ),
    (
        "inflation-yoy",
        "For the CPI series CPIAUCSL, find the most recent year-over-year change, as a percent. "
        "The server can compute that transformation for you; do not do the arithmetic by hand.",
        "cpi_yoy_pct",
        _cpi_yoy(),
        0.01,
    ),
    (
        "rate-history-max",
        "For the 10-year Treasury series DGS10, find the highest value it has ever reached over "
        "its entire history in this dataset. Be careful: a long daily series is returned as a "
        "sample of its points, and the highest point is not necessarily among the ones you get "
        "back. The tool reports the true figure alongside the points.",
        "max_yield",
        _daily_max(),
        0.01,
    ),
    (
        "gdp-peak-unemployment",
        "Across the observations available for real GDP (GDPC1), find the date on which it was "
        "highest, then report the US unemployment rate (UNRATE) for that same date, as a percent.",
        "unemployment_rate",
        _unemployment_at_gdp_peak(),
        0.01,
    ),
    (
        "initial-print",
        "Real GDP (GDPC1) for the observation dated 2025-01-01 has since been revised. Find the "
        "value as it was FIRST published, not the value it holds today.",
        "initial_value",
        _initial_print(),
        0.5,
    ),
    (
        "revision-count",
        "Across the observations available for real GDP (GDPC1), count how many have been revised "
        "since they were first published, that is, how many now hold a different value than the "
        "one first reported.",
        "revised_count",
        _revised_count(),
        0.01,
    ),
    (
        "release-series-count",
        "The Employment Situation release has FRED release id 50. Count how many of the series it "
        "publishes are monthly.",
        "series_count",
        _monthly_series_in_release_50(),
        0.01,
    ),
]

# (name, prompt, answer key, expected string)
STRING_TASKS = [
    (
        "series-units",
        "What are the units of the real GDP series GDPC1? Report the full units description "
        "exactly as FRED gives it.",
        "units",
        _gdp_units(),
    ),
    (
        "find-series-id",
        "Find the FRED series ID for the headline US unemployment rate: the monthly, seasonally "
        "adjusted one that is the most widely used series of its kind.",
        "series_id",
        "UNRATE",
    ),
]


# --- prompt boilerplate --------------------------------------------------------------
#
# Deliberately worded without the port, the fixture module name, or the API hostname that
# the bypass check greps for. An agent that echoes its instructions into a shell comment
# or a todo entry would otherwise fail the very check the paragraph exists to pass.
MCP_ROUTE = """\
Use the FRED MCP tools. They are named `mcp__fred__*`, and the server behind them is
already running: nothing needs to be started, installed, or configured.

If they are not in your tool list, their schemas are deferred, not missing. Load one with
`ToolSearch` -- `select:mcp__fred__get_observations`, say -- and then call it directly,
the way you call any other tool.

They are tools, not programs. No command, no HTTP endpoint, and no Python import reaches
them: `Bash`, `curl`, and `python3` cannot invoke an MCP tool, and a run that spends its
budget trying will simply time out. Call the tool.

Call it yourself rather than handing the work to a subagent. Delegating a one-line lookup
costs a whole extra agent loop and buys nothing.

The work has to go through the tools. Do not call the data provider's HTTP API directly,
do not read or edit the server's source or its test fixtures, and do not import its Python
package. The point of the task is to exercise the tools, and a result reached any other
way does not count, however correct it is.

If a tool returns an error, read the message and retry it or call another FRED tool. Do
not work around the server."""

TASK_TOML = """\
[task]
name = "fred-mcp/{name}"
description = "{desc}"

[metadata]
suite = "fred-mcp"

[environment]
docker_image = "fred-bench"
network_mode = "public"

[agent]
timeout_sec = 300

[verifier]
timeout_sec = 60
"""

NUMERIC_INSTRUCTION = """\
# Task: {title}

{instruction}

{route}

Write the answer to `/app/answer.json` as a single JSON object with this shape, and
nothing else:

```json
{{"{key}": <number>}}
```
"""

STRING_INSTRUCTION = """\
# Task: {title}

{instruction}

{route}

Write the answer to `/app/answer.json` as a single JSON object with this shape, and
nothing else:

```json
{{"{key}": "<text>"}}
```
"""

# Every task's verifier is the same line: rewardkit scores each subdirectory of tests/
# as its own named reward. The image installs it (evals/environment/Dockerfile).
TEST_SH = """\
#!/usr/bin/env bash
# Verifier. Two rewards, both computed by rewardkit:
#
#   outcome  the answer is right
#   process  the answer came through the MCP server
#
# `outcome` alone cannot gate this plugin. The mock FRED API is reachable over
# plain HTTP from inside the container, its fixtures sit on disk in plain Python,
# and the real FRED API is reachable over the network. An agent that ignores the
# MCP entirely can still produce the right answer. `process` is what makes these
# MCP evals rather than answer-matching.
rewardkit /tests
"""

OUTCOME_NUMERIC = '''\
"""`outcome` reward: the number in answer.json matches the fixtures.

Generated by evals/generate_tasks.py. The expected value is computed from the mock
fixtures by the same shaping code the server uses, so it cannot drift from what the
agent sees. Edit the generator, not this file.
"""

import json
from pathlib import Path

from rewardkit import criterion

KEY = "{key}"
EXPECTED = {expected!r}
TOLERANCE = {tol!r}


@criterion(description="answer.json[{key}] is within {tol} of {expected}")
def answer_matches(workspace: Path) -> bool:
    try:
        data = json.loads((workspace / "answer.json").read_text())
        return abs(float(data[KEY]) - EXPECTED) <= TOLERANCE
    except Exception:
        # Missing, malformed, or wrong-typed answers score 0 rather than erroring the
        # trial: an agent that writes nothing has failed the task, which is a verdict,
        # not a harness fault.
        return False
'''

OUTCOME_STRING = '''\
"""`outcome` reward: the text in answer.json matches the fixtures.

Generated by evals/generate_tasks.py. Compared case-insensitively with whitespace
collapsed, since "Billions of Chained 2017 Dollars" and "billions of chained 2017
dollars" are the same answer and neither is more correct.
"""

import json
from pathlib import Path

from rewardkit import criterion

KEY = "{key}"
EXPECTED = {expected!r}


def _normal(value: object) -> str:
    return " ".join(str(value).split()).strip().lower()


@criterion(description="answer.json[{key}] equals {expected}")
def answer_matches(workspace: Path) -> bool:
    try:
        data = json.loads((workspace / "answer.json").read_text())
        return _normal(data[KEY]) == _normal(EXPECTED)
    except Exception:
        return False
'''

# The calendar answer is a date relative to the day the trial runs, because the fixture
# generates release dates from a clock rather than writing them down. A fixed date would
# be right for exactly one day.
OUTCOME_NEXT_RELEASE = '''\
"""`outcome` reward: the next release date for release 50.

Generated by evals/generate_tasks.py. The fixture places release dates relative to the
current day, so the expected answer is computed here rather than baked in: a literal
date would stop being the right answer tomorrow.
"""

import json
from datetime import date, timedelta
from pathlib import Path

from rewardkit import criterion

KEY = "{key}"
OFFSET_DAYS = {offset}


def _accepted() -> set:
    """The expected date, plus the one for yesterday.

    The agent and the verifier are two processes, and a trial that starts just before
    midnight is graded on the next day against a fixture that has moved with it.
    Accepting both is a tolerance on the clock, the same as the numeric tasks carry a
    tolerance on the value.
    """
    today = date.today()
    return {{(day + timedelta(days=OFFSET_DAYS)).isoformat() for day in (today, today - timedelta(days=1))}}


@criterion(description="answer.json[{key}] is the next scheduled release date")
def answer_matches(workspace: Path) -> bool:
    try:
        data = json.loads((workspace / "answer.json").read_text())
        return str(data[KEY]).strip() in _accepted()
    except Exception:
        return False
'''

PROCESS_MCP = '''\
"""`process` reward: the answer came through the fred MCP server.

There are three ways round this server, and `outcome` cannot see any of them:

  1. the mock FRED API, reachable over plain HTTP inside the container
  2. the fixtures on disk, which hold every expected answer in plain Python
  3. the real FRED API, reachable because the agent needs the network for its own model

A tastytrade gate run took route 1 and scored a clean 1.0 on outcome alone. This reward
is what catches all three.

Generated by evals/generate_tasks.py.
"""

import json
import re
from pathlib import Path

from rewardkit import criterion

TRAJECTORY = "/logs/agent/trajectory.json"
SESSIONS = Path("/logs/agent/sessions")


def _trajectory_calls() -> list:
    """Tool calls harbor recorded, as steps[].tool_calls[].

    `path` matters: rewardkit's own trajectory helpers default to /logs/trajectory.json
    while Harbor agents write /logs/agent/trajectory.json, and a missing file scores 0
    silently rather than erroring.
    """
    try:
        data = json.loads(Path(TRAJECTORY).read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return [call for step in data.get("steps") or [] for call in step.get("tool_calls") or []]


def _session_calls() -> list:
    """Tool calls from Claude Code's own transcripts, subagents included.

    harbor builds trajectory.json from the main session only: its session-dir scan drops
    any jsonl whose path contains a `subagents/` component, and modern Claude Code writes
    each subagent's transcript there. A call the agent delegated therefore leaves an
    `Agent` entry in the trajectory and no tool.

    Reading the raw transcripts makes the check stop caring who placed the call. That
    cuts both ways on purpose: crediting a delegated MCP call without also seeing a
    delegated `curl` would turn "ask a subagent" into an invisible bypass, which is the
    hole this reward exists to close.
    """
    calls = []
    for path in sorted(SESSIONS.rglob("*.jsonl")):
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = (event.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    calls.append({"function_name": block.get("name"), "arguments": block.get("input")})
    return calls


def _calls() -> list:
    """Every tool call this trial can be shown to have made, or [].

    A list rather than a generator so every criterion can fail closed on an empty
    trajectory. A "did not bypass" check is vacuously true when there are no calls at
    all, which would hand a no-op run half of `process`; no record means no evidence the
    intended route was taken, so it has to score 0.
    """
    return _trajectory_calls() + _session_calls()


def _name(call) -> str:
    return str(call.get("function_name") or "")


def _args(call) -> str:
    return json.dumps(call.get("arguments") or {})


MCP_PREFIX = "mcp__fred__"
# The three ways round the server. Matched against tool arguments, so it catches Bash,
# Read, and Edit alike without enumerating tool names.
#
# The port alone, not host:port. The mock binds every interface, so it answers on
# localhost, 127.0.0.1, 0.0.0.0, [::1], and the container's own hostname; enumerating two
# spellings lets the other three through, and a bypass that scores as good behaviour is
# worse than no check. Nothing else in the image listens on that port.
#
# The hostname of the real API is here because this benchmark runs with the network up
# (the agent needs it to reach its own model), which tastytrade's mock-only setup did not
# have to consider.
BYPASS = re.compile(r":8080\\b|\\bfred_api\\b|stlouisfed", re.IGNORECASE)


@criterion(description="Agent called a fred MCP tool")
def used_mcp_server(workspace: Path) -> bool:
    """Anywhere in the run, subagents included -- see `_session_calls`.

    Whether the top-level agent placed the call or handed it to a delegate is the
    harness's routing decision, not a fact about this plugin. The question the gate asks
    is whether a real agent can drive the server to the answer, and a delegated call is
    that.
    """
    return any(_name(call).startswith(MCP_PREFIX) for call in _calls())


@criterion(description="Agent did not reach the data directly")
def no_direct_data_access(workspace: Path) -> bool:
    calls = _calls()
    if not calls:
        return False  # no trajectory is not evidence of good behaviour
    for call in calls:
        if _name(call).startswith(MCP_PREFIX):
            continue  # the MCP server talking to its own backend is the point
        if BYPASS.search(_args(call)):
            return False
    return True
'''

NUMERIC_SOLVE = """\
#!/usr/bin/env bash
# Oracle: write the answer the fixtures imply, so the verifier itself can be checked.
set -euo pipefail
APP_DIR="${{APP_DIR:-/app}}"
mkdir -p "$APP_DIR"
echo '{{"{key}": {expected}}}' > "$APP_DIR/answer.json"
"""

STRING_SOLVE = """\
#!/usr/bin/env bash
# Oracle: write the answer the fixtures imply, so the verifier itself can be checked.
set -euo pipefail
APP_DIR="${{APP_DIR:-/app}}"
mkdir -p "$APP_DIR"
cat > "$APP_DIR/answer.json" <<'JSON'
{json_line}
JSON
"""

NEXT_RELEASE_SOLVE = """\
#!/usr/bin/env bash
# Oracle for the calendar task. The expected date moves with the clock, so the oracle
# computes it the same way the verifier does rather than echoing a literal.
set -euo pipefail
APP_DIR="${{APP_DIR:-/app}}"
mkdir -p "$APP_DIR"
python3 - "$APP_DIR/answer.json" <<'PY'
import json, sys
from datetime import date, timedelta
answer = (date.today() + timedelta(days={offset})).isoformat()
with open(sys.argv[1], "w") as fh:
    json.dump({{"{key}": answer}}, fh)
PY
"""

ENVIRONMENT_DOCKERFILE = "FROM fred-bench\n"


def _write(path: str, content: str, executable: bool = False) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)
    if executable:
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _title(name: str) -> str:
    return name.replace("-", " ").title()


def _common(base: str, name: str, desc: str, instruction: str, template: str, key: str) -> None:
    _write(os.path.join(base, "task.toml"), TASK_TOML.format(name=name, desc=desc.replace('"', "'")))
    _write(
        os.path.join(base, "instruction.md"),
        template.format(title=_title(name), instruction=instruction, key=key, route=MCP_ROUTE),
    )
    _write(os.path.join(base, "tests", "test.sh"), TEST_SH, executable=True)
    _write(os.path.join(base, "tests", "process", "check.py"), PROCESS_MCP)


def generate() -> list[str]:
    names: list[str] = []

    for name, instruction, key, expected, tol in NUMERIC_TASKS:
        base = os.path.join(TASKS_DIR, name)
        _common(base, name, instruction, instruction, NUMERIC_INSTRUCTION, key)
        _write(
            os.path.join(base, "tests", "outcome", "check.py"),
            OUTCOME_NUMERIC.format(key=key, expected=expected, tol=tol),
        )
        _write(
            os.path.join(base, "solution", "solve.sh"),
            NUMERIC_SOLVE.format(key=key, expected=expected),
            executable=True,
        )
        names.append(name)

    for name, instruction, key, expected in STRING_TASKS:
        base = os.path.join(TASKS_DIR, name)
        _common(base, name, instruction, instruction, STRING_INSTRUCTION, key)
        _write(os.path.join(base, "tests", "outcome", "check.py"), OUTCOME_STRING.format(key=key, expected=expected))
        _write(
            os.path.join(base, "solution", "solve.sh"),
            STRING_SOLVE.format(json_line=json.dumps({key: expected})),
            executable=True,
        )
        names.append(name)

    # The calendar task: a clock-relative answer, so both the check and the oracle
    # compute it rather than carrying a literal.
    name, key, offset = "next-release", "next_release_date", fx.NEXT_RELEASE_50_OFFSET
    base = os.path.join(TASKS_DIR, name)
    instruction = (
        "The Employment Situation release has FRED release id 50. Find the date of its NEXT "
        "scheduled release, that is, the first one still in the future. Report it as YYYY-MM-DD."
    )
    _common(base, name, instruction, instruction, STRING_INSTRUCTION, key)
    _write(
        os.path.join(base, "tests", "outcome", "check.py"),
        OUTCOME_NEXT_RELEASE.format(key=key, offset=offset),
    )
    _write(
        os.path.join(base, "solution", "solve.sh"),
        NEXT_RELEASE_SOLVE.format(key=key, offset=offset),
        executable=True,
    )
    names.append(name)

    # Every task needs an environment/ directory or Harbor will not discover it.
    for task in names:
        _write(os.path.join(TASKS_DIR, task, "environment", "Dockerfile"), ENVIRONMENT_DOCKERFILE)

    return names


if __name__ == "__main__":
    created = generate()
    print(f"Generated {len(created)} tasks:")
    for task in created:
        print(" -", task)
