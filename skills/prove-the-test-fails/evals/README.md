# prove-the-test-fails evals

Two checks over one fixture. The fixture is a small retrieval library with a suite that
is green and a contract test that cannot fail, reproducing a defect found in a real
codebase: an assertion comparing sets of result types, on a query that matches nothing,
so it reduces to `set() == set()` whatever the strategies do.

```
fixture/
├── src/retrieval.py        two lexical strategies over one corpus
└── tests/test_contract.py  five passing tests, one of them decorative
```

The fixture also carries the two cases the skill warns about. Stubbing `lexical_search`
to return nothing fails only the `[lexical]` cases of `test_finds_a_phrase_from_the_corpus`
and leaves the `[bm25]` cases green, which is the blast radius a correct mutation
produces. And `test_empty_query_returns_nothing[lexical]` survives that same mutation
legitimately, because asserting emptiness is satisfied by an empty implementation.

## The eval

```bash
./run_eval.sh [--model sonnet]     # costs LLM tokens
./run_eval.sh --control            # same task, skill absent
```

Copies the fixture into a scratch git repository, drops `SKILL.md` in as a project skill,
and asks a headless Claude Code run whether the suite actually guards the rule it claims
to. Grading is on behaviour rather than prose:

| Check | Why |
| --- | --- |
| First line of `VERDICT.txt` is `UNGUARDED` | Only knowable by breaking a strategy and watching the contract test stay green |
| `src`, `tests`, and `pyproject.toml` match the starting commit | Any mutation was reverted |
| The suite is green again | The repository was left working |

The skill is never named in the prompt, so an automatic load is also a test of the
`description` field.

**What this measures.** It is a regression guard on the guidance: an edit to `SKILL.md`
that drops the revert step, or that stops the skill loading on this kind of question,
turns it red. It is not evidence of uplift. In the runs on record the control passes too,
so a current model reaches the same answer on this fixture unprompted. Raising the
fixture's difficulty until the control fails is the way to turn this into an uplift
measurement, and until that happens the eval should not be described as one.

## The fixture check

```bash
./check_fixture.sh                 # no agent, no LLM, runs in CI
```

The eval only asks a real question while the fixture's contract test genuinely cannot
fail. This applies the mutation an agent is expected to find and asserts the exact shape
of the run that follows: the contract test survives, the `[lexical]` phrase case dies,
the `[bm25]` case lives, and the empty-query case survives. Repairing the fixture's
assertion turns this red with a message saying the eval no longer poses its question. It
works on a copy, so the checked-in fixture is never mutated.

## Why not a Harbor task

The MCP plugins in this repo gate on [Harbor](https://www.harborframework.com) tasks,
which is the right shape there: an MCP server has to be exercised as a server, in a
container, against a live hub. A skill is a markdown file that has to be present in the
agent's own skill directory, and the version under test is the one in the branch. The
Harbor tasks here install their subject from GitHub's default branch, so a task would
gate on the published skill rather than the change under review. Containerising also
brings a hub key and Modal for no gain, since nothing here talks to a hub. A local
headless run keeps the same three phases, fixture then agent then grade, without any of
that.
