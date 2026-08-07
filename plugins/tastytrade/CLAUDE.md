# tastytrade

MCP server over the Tastytrade brokerage API: accounts, positions, market data,
option chains, and transactions. Order placement is gated off by default.

Repo-wide plugin and eval conventions live in the root `CLAUDE.md`.

## Resources

| What | Where |
| --- | --- |
| **Tastytrade API docs**, auth and every endpoint | https://developer.tastytrade.com/getting-started/ |
| Claude Code docs | https://docs.anthropic.com/en/docs/claude-code |
| Harbor framework source | https://github.com/harbor-framework/harbor |
| **rewardkit**, how verifiers and criteria are defined | https://www.harborframework.com/docs/rewardkit |
| rewardkit on PyPI (`harbor-rewardkit`) | https://pypi.org/project/harbor-rewardkit/ |
| uv | https://docs.astral.sh/uv/ |

`github.com/laude-institute/harbor` is the old URL and 301-redirects to the
`harbor-framework` one above. Use the new one.

The rewardkit page is the one to read before touching anything under `evals/`.
The rule that bites is that **every criterion in a reward directory aggregates by
weighted mean**, so an extra criterion silently dilutes the others rather than
adding a check.

## What is specific here

**Trading is gated.** `place_order` requires the server's `TT_ENABLE_TRADING`
flag *and* `confirm=true`. Always `preview_order` first. The agent never sees
real credentials in tests: the image points `API_BASE_URL` at the local mock and
`require-local-api` refuses to start a server unless it points at localhost.

**A skill, not just tools.** `skills/earnings-calendars` ships
`scripts/calendars.py`, and the `earnings-implied-move` eval is the only task
that exercises a skill rather than the MCP tools. Its prompt names neither the
skill nor the script, so it measures whether the agent recognises an
earnings-vol question and reaches for the right thing.

**Tasks are generated, not hand-typed.** `evals/generate_tasks.py` computes
every expected answer from the mock fixtures with the same shaping code the
server uses. Edit the generator, not the individual `check.py` files. The skill
task follows the same rule, importing `scripts/calendars.py` and fitting the
shipped chain.

**`validate-tasks` needs Docker.** rewardkit does not build on macOS (its
litellm dependency wants a newer rustc than ships there), so the validator runs
in the bench image, which is also the image that will really grade a gate run.

## Project Structure

```
├── src/                     # Application source code
├── tests/
│   ├── conftest.py          # Shared fixtures
│   ├── unit/                # Fast, isolated unit tests
│   └── integration/         # Tests involving external systems
├── pyproject.toml           # Project config, dependencies, tool settings
├── Makefile                 # Common dev commands
└── .claude/
    └── settings.json        # Hooks for auto-linting on .py edits
```

## Environment

- **Python**: >=3.13, managed via `uv`
- **Dependencies**: `uv sync` to install; dev deps (pytest, ruff, mypy, etc.) in `[dependency-groups.dev]`
- **Run commands**: Always use `uv run <command>` (e.g., `uv run pytest`)

## Testing

Follow **Test-Driven Development (TDD)**: Red -> Green -> Refactor.

- `make test`: run all tests
- `make test-unit`: run tests marked `@pytest.mark.unit`
- `make test-integration`: run tests marked `@pytest.mark.integration`
- `make coverage`: run tests with coverage report (80% threshold)
- Place shared fixtures in `tests/conftest.py`
- Unit tests: fast, no external dependencies
- Integration tests: may use databases, APIs, or services

## Linting & Formatting

- `make lint`: check with ruff
- `make lint-fix`: auto-fix with ruff
- `make format`: format with ruff

A PostToolUse hook automatically runs `make lint-fix format` after any `.py` file edit.

## Git Workflow

### Worktrees
- Use git worktrees for parallel development. Each task gets its own worktree.
- Never switch branches in the current worktree.

### Stacked PRs
- Prefer small, focused PRs (~200-400 lines) that stack on each other.
- Each PR should represent one logical change.
- Use `gh` CLI for all GitHub interactions (PRs, issues, labels).

### Commits
- Atomic commits with conventional-commit messages: `feat|fix|chore(#issue): description`
- Each commit should compile and pass tests independently.
- Commit and push frequently.

### Task Scoping
- Stay focused on the assigned task.
- Discovered bugs/tech debt: create a GitHub issue via `gh issue create`.
- Minor improvements: leave a `TODO` comment.
- Tangential/speculative work: ignore it.

## Workflow

1. **Plan first** for non-trivial tasks (3+ steps or architectural decisions).
2. **Use subagents** to keep the main context window clean.
3. **Verify before done**: run tests, check logs, demonstrate correctness.
4. **No laziness**: find root causes, no temporary fixes.
5. **Minimal impact**: only touch what's necessary.
6. **Simplicity first**: make every change as simple as possible.
