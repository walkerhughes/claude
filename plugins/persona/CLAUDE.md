# persona

Skills for writing in the user's own voice: a plain-language style skill
(`humanoid`), plus a local labeling loop (`learn`) that harvests the user's own
writing from their transcripts and builds a translation skill from it.

Repo-wide plugin conventions live in the root `CLAUDE.md`. This file is the
plugin-specific part.

## Resources

| What | Where |
| --- | --- |
| Claude Code plugin manifest reference | https://code.claude.com/docs/en/plugins-reference |
| Claude Code docs | https://docs.anthropic.com/en/docs/claude-code |
| This plugin on GitHub | https://github.com/walkerhughes/claude/tree/main/plugins/persona |

Deliberately short. This plugin integrates with nothing external, which is the
feature: no API, no account, no network call except the loopback HTTP server.

## The shape of this plugin

The odd one out, and allowed to be. **No server, no dependencies, no build, no
tests directory.** One stdlib-only script and three markdown documents. Do not
add a framework, a package, or a `pyproject.toml` to it without a concrete
reason: `scripts/persona.py` says so at the top and it is the right call for a
form with three buttons.

```
scripts/persona.py    the whole implementation, stdlib only
commands/learn.md     the /learn slash command
skills/learn/         runs the labeling loop
skills/humanoid/      the plain-language style skill
```

## Commands

There is no Makefile. The checks are:

```bash
python3 scripts/persona.py --selftest   # asserts the harvest filters still work
uvx ruff check . && uvx ruff format --check .
```

Both run in CI. ruff finds the repo-root `ruff.toml` by walking up, since this
plugin has no config of its own.

## What is specific here

**Privacy is the product.** Everything stays on the machine. The only network
call in `persona.py` is the loopback server that renders the labeling UI. Keep
it that way: a telemetry call or a remote model call here would break the one
promise the README makes.

**Never harvest subagent transcripts.** `is_user_prose` drops any event with
`isSidechain`, and `harvest` skips whole files with a `subagents/` path
component. Those user turns were written by the parent model, not the user, so
harvesting them would teach the skill to imitate Claude, which is the exact
opposite of the goal.

**State is overridable, and that matters.** `PERSONA_STATE` and
`PERSONA_PROJECTS` exist so a test run cannot clobber real labels. The default
was wiped once by a `rm -rf` in a smoke test, taking 44 critiques with it. Set
`PERSONA_STATE` before running anything that writes.

**The humanoid skill is hand-written.** The user rewrote it manually so the
instructions read the way they ask Claude to write. Treat wording changes there
as theirs to make.

**Skill frontmatter is load-bearing.** A malformed block does not raise: the
skill silently never loads and never triggers. CI validates it, since that
failure is invisible rather than loud. Skills need `name` and `description`;
commands need only `description`, taking their name from the filename.
