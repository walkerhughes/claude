# Repo conventions

A Claude Code plugin marketplace. Every plugin ships from `plugins/<name>/` and is
listed in `.claude-plugin/marketplace.json`.

These rules are derived from what the existing plugins already do. When they
disagree, the majority of the three MCP plugins wins, and the divergence is
listed under [Known drift](#known-drift) rather than left implicit.

## Layout

```
.claude-plugin/marketplace.json   every plugin: name, source, description
.github/workflows/<plugin>.yml    one workflow per plugin, plus plugin-version.yml and review.yml
plugins/<plugin>/
  .claude-plugin/plugin.json      the manifest
  README.md
  commands/ skills/               what Claude Code loads
  src/ tests/ evals/              MCP server plugins only
  scripts/start-server.sh         MCP server plugins only
  Makefile pyproject.toml uv.lock MCP server plugins only
```

`persona` is the exception and is allowed to be: it ships skills and one
stdlib-only script, with no server, no dependencies, and no build.

## Plugin manifests

`plugin.json` carries the same eight keys everywhere: `name`, `version`,
`description`, `author`, `license`, `homepage`, `repository`, `keywords`.
`homepage` points at the plugin's directory on GitHub, `repository` at the repo.

**Bump `version` whenever a shipped file changes.** Claude Code caches an
installed plugin under a path keyed by that version, so shipping without a bump
means installed copies never refresh no matter how many times a user reinstalls.
The change is invisible rather than broken, which is the worst way to fail.
`plugin-version.yml` enforces this and excludes `tests/**` and `evals/**`, which
are not copied into the cache.

A new plugin needs an entry in `marketplace.json` too. The version gate
discovers plugins by globbing manifests, so it needs no edit.

## CI

One workflow per plugin, named after it. Every workflow:

- filters `paths` to `plugins/<name>/**` plus its own file, on both
  `pull_request` and `push` to main. A change to one plugin must never run
  another's suite.
- sets `defaults.run.working-directory` to the plugin directory, because Actions
  only reads workflows from the repo root.
- runs a cheap job first (lint, typecheck, unit tests), then gates the expensive
  eval job on it with `needs:`.

Prefer failing in the cheap job. A check that needs no hub, no Docker, and no
model belongs there, where it fails a PR in seconds instead of after the gate has
spent a rate-limit window.

## Evals

Every MCP server plugin is gated at the agent-loop level: Claude Code drives the
tools over a set of tasks through [Harbor](https://github.com/laude-institute/harbor),
and CI fails unless the rewards clear the threshold. This is the only check that
catches a server a real agent cannot actually drive.

### Two rewards, always

`tests/test.sh` is exactly `rewardkit /tests`. Below it, one directory per reward
dimension:

```
tests/outcome/check.py    the answer is right
tests/process/check.py    the answer came through the plugin
```

**`outcome` alone cannot gate an MCP plugin.** Every one of these images has a
back door: a mock API on a local port, fixtures on disk, a CLI on PATH, the real
upstream API over the network. An agent that ignores the MCP entirely can still
produce a perfect answer, and real gate runs in this repo have done exactly that.
`process` is what makes these MCP evals rather than answer matching.

### Writing criteria

rewardkit aggregates **every criterion in a reward directory by weighted mean**,
so each one you register dilutes the others. Two rules follow:

- Register only criteria that carry signal. A `file_exists` next to a check that
  already returns False on a missing file turns the reward into a fraction and
  decides nothing.
- Partial credit must be meaningful. Two criteria are right when they can
  disagree usefully, for example claiming a deletion versus performing it.

A `@criterion` taking nothing but `workspace` self-registers at decoration time,
so never also call it.

### Fail closed

No trajectory means no evidence the intended route was taken, so `process` scores
0. A "did not bypass" check is vacuously true when there are no tool calls at
all, so it must return False on an empty run rather than handing a no-op agent
half the reward.

Criteria return False for a missing, malformed, or wrong-typed answer rather than
raising. An agent that wrote nothing has failed the task, which is a verdict, not
a harness fault. Raise only when the failure is genuinely infrastructure, such as
an unreadable hub, where scoring it as a wrong answer would report an agent
defect that did not happen.

### Read the transcripts, not just the trajectory

Harbor builds `trajectory.json` from the main session only: its session scan
drops any jsonl whose path contains a `subagents/` component, which is exactly
where Claude Code writes a delegate's transcript. A delegated call therefore
leaves an `Agent` entry and no tool.

So `process` criteria read the raw transcripts under `/logs/agent/sessions` as
well, and stop caring who placed the call. Whether the agent called the tool
itself or routed it through a delegate is the harness's decision, not a fact
about the plugin.

**This has to cut both ways.** Crediting a delegated MCP call while missing a
delegated bypass turns "ask a subagent" into an invisible bypass, which is worse
than not looking at all. Assert both directions.

Pass `path` explicitly to any rewardkit built-in trajectory criterion. They
default to `/logs/trajectory.json`, Harbor agents write
`/logs/agent/trajectory.json`, and the wrong path is not an error: the file is
just missing and the criterion silently returns 0.

### Match the bypass check to the actual bypass

Where the back door is an HTTP endpoint, match on the port across all tool
arguments rather than on a hostname list. A mock that binds every interface
answers on `localhost`, `127.0.0.1`, `0.0.0.0`, `[::1]`, and the container's own
name, and naming two of those lets the other three through.

Where the back door is a CLI, match shell calls only. Widening past that buys
nothing and adds false positives. Either way, a bypass that scores as good
behaviour is worse than no check at all.

### Prove the verifiers without a model

Every plugin ships a validator that scores its real criteria against synthetic
runs, with no Harbor, no model, and no API key. `harbor run -a oracle` cannot
answer this question: the oracle takes the intended route by construction, so it
proves a task is solvable and says nothing about whether a bypass would be
caught.

Cover at least: solved, empty, bypassed, a second spelling of the bypass,
delegated, and delegated-bypass. One spelling of a bypass proves only that one
spelling is caught.

rewardkit does not build on macOS (its litellm dependency wants a newer rustc
than ships there). Either run the validator in the bench image, or stub rewardkit
and load the real `check.py` from disk. Never fork the criteria into the test.

### Task prompts

State the rule `process` scores. Every paragraph of it should be there because a
gate run failed without it.

Do not name the tool to call. The point of the plugin is that its tool
descriptions and server instructions do the routing, so naming it tests the
agent's reading comprehension instead. A run that fails for that reason is a bug
upstream in the tool description, and belongs fixed there.

Word the rule so it avoids the host, port, and module name the bypass check
greps for, so an agent echoing its instructions into a shell comment cannot fail
the check by quoting it.

Do not hand-type expected answers where a generator can compute them from the
same fixtures the agent sees.

### Running the gate

- Authenticate with `CLAUDE_CODE_OAUTH_TOKEN` and set `CLAUDE_FORCE_OAUTH=1`, so
  runs bill to a subscription. **Never reintroduce `ANTHROPIC_API_KEY`**: with
  both present the CLI silently prefers the key and the run is on credits again,
  with only a debug log to say so.
- Probe the token before spending a rate-limit window. An expired credential
  otherwise surfaces as "the gate did not clear", which reads as a server
  regression and is not one. Fail rather than skip on a missing secret.
- Serialize with a `concurrency` group named `<plugin>-evals` and
  `cancel-in-progress: false`. Subscription rate limits are per account and
  shared with interactive use.
- Guard the job to same-repo PRs. A fork PR gets no secrets.
- Upload to the hub as **`ci-evals-<plugin>`**, one job per CI run, so every
  plugin's history is searchable together.
- Upload on PR runs too. Restricting uploads to main leaves a PR gate with
  nothing on the hub, so the only record is an artifact that expires in 7 days.
- On failure, print each trial by name with its rewards and the tool calls behind
  it. Dumping raw verifier output gives anonymous pairs of numbers and forces a
  CI artifact download to learn which task broke.

## Known drift

Real today, worth closing. Do not copy these into a new plugin.

| What | fred | tastytrade | harbor-hub |
| --- | --- | --- | --- |
| Uploads on PR runs | yes | yes | **push only** |
| Names failing trials on failure | `explain_trials.py` | `explain_trials.py` | **cats verifier output** |
| Cheap CI job name | `check` | `check` | `lint-unit` |
| Validator scope | outcome + process | outcome + process | **process only** |
| `EVAL_ATTEMPTS` / `EVAL_MIN_MEAN` | set | set | unset |
| Makefile `check` / `typecheck` / `format` / `coverage` | yes | yes | **no** |

The first two are the ones that bite: both are behaviours fred and tastytrade
adopted deliberately after being burned, and harbor-hub still has the version
they moved away from.

Differences that are **not** drift, because harbor-hub grades against a live hub
rather than a mock: no `job.yaml`, no `generate_tasks.py`, no mock scripts, tasks
at `evals/<name>/` rather than `evals/tasks/<name>/`, and `answer.txt` rather
than `answer.json`.

## Style

- No em dashes anywhere, prose or code comments.
- Comments say why, not what. If a line is there because a real run failed
  without it, say which failure.
- Never add an agent name as commit co-author.
- Do not hand-edit `CHANGELOG.md` or any generated file.
