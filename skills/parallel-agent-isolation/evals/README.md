# parallel-agent-isolation evals

Two checks, in cost order.

```bash
make check    # packaging and wiring, no API key, no cost
make evals    # behavioural, needs Claude Code on PATH and credentials
```

## `make check`

`check_wiring.py` reads the skill's frontmatter, its marketplace entry, and the
case set. It exists because every way a skill breaks in packaging is silent: an
unclosed frontmatter fence, a `name` that no longer matches the directory, a
marketplace entry whose `skills` path points somewhere else, a `version` pinned
in the entry so installed copies never refresh. In each case the skill installs
and simply never loads. Stdlib only, so it runs anywhere.

## `make evals`

`run_evals.py` runs each case as headless Claude Code in a throwaway workspace
holding this skill and nothing else, with `--setting-sources project` so a
personal skill on the developer's machine cannot stand in for the one under
test. Every case asserts on skill invocation; the triggering cases additionally
grade the answer against a rubric using a second, tool-less Claude Code call
that returns a structured verdict and never sees the skill.

The triggering cases deliberately sit in different ecosystems and share different
kinds of state, because a skill that recognised only containers and databases
would pass a case set drawn from one stack while being useless on the next one.

| Case | Stack, and what is shared | Skill must | The answer must |
| --- | --- | --- | --- |
| `shared-database-dispatch` | Go, one hosted staging database | load | resolve the shared instance by isolating, serialising, re-verifying serially, or giving the stateful work to one agent, rather than dispatching both agents at the suite concurrently |
| `shared-infra-state` | Terraform, one remote state file and one sandbox account | load | resolve the shared state and account the same way, rather than letting three applies race through the lock |
| `green-report-collision` | iOS, one booted simulator | load | treat a green suite reported alongside "a second simulator would not boot" as invalid, extend the doubt to the other agent's green result, and re-run serially |
| `file-only-parallel` | any, nothing shared | stay out | (not graded) |

`file-only-parallel` is the honesty check, and it earns its place. A description
that fires on every mention of parallel agents would pass the triggering cases
while making the skill noise, so one case dispatches three agents over
documentation edits and requires the skill to stay out of it. The first draft of
the description failed exactly there, and so did a later attempt to shorten the
clause that excludes file-only work.

Whether a description triggers is sampled behaviour, so each case runs three
times and every run must hold. Cost is a dollar or so a full run on `sonnet`,
capped per call by `--max-budget-usd`. `EVAL_RUNS`, `EVAL_MODEL`,
`EVAL_MAX_BUDGET_USD`, and `EVAL_TIMEOUT_SEC` override the defaults. Pass case
names as arguments to run a subset.

## Why not the Harbor harness

The [harbor-hub evals](../../../plugins/harbor-hub/evals/) are Harbor tasks: a
container image, an MCP server declared in `task.toml`, and a verifier that
recomputes ground truth from the hub. That shape fits a capability surface with
a live backend to compare against. This skill has no server, no backend, and
nothing to recompute. What it has is a claim about what a model does at dispatch
time, so the eval runs the model and looks. Wrapping that in Harbor would add an
image build, a Modal or Docker dependency, and a Harbor API key to a check whose
whole content is one prompt and one grading rubric.
