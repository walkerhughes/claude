# Benchmark agent environment.
#
# One checkout of the server plus the mock Tastytrade API, so Claude Code can be
# benchmarked over the eval tasks. Harbor installs the claude-code agent itself.
#
# This used to build two checkouts and compare a baseline ref against a candidate
# ref. That comparison existed to show the refactored server beat the plain
# endpoint-wrapper baseline. The refactor landed on main, the candidate branch was
# deleted, and the image stopped building. There is no second side left to compare
# against, so the split is gone and the evals are now a regression gate on one
# server rather than a bake-off between two.
#
# Build context is the plugin root, not this directory:
#   make benchmark-build     # docker build -f evals/environment/Dockerfile .
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv for dependency management (matches the project toolchain).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# The server under test is the working tree rather than a cloned ref. A clone only
# ever measured what had already been pushed, which is how the stale-branch breakage
# went unnoticed; copying measures the code actually in front of you.
COPY . /opt/tastytrade
RUN cd /opt/tastytrade && (uv sync --frozen || uv sync)

# Claude Code discovers personal skills here. Installing the skill lets a task
# exercise the real trigger path instead of naming the script in its prompt.
RUN mkdir -p /root/.claude/skills \
    && cp -r /opt/tastytrade/skills/earnings-calendars /root/.claude/skills/earnings-calendars

COPY evals/environment/scripts/ /usr/local/bin/
RUN chmod +x /usr/local/bin/require-local-api /usr/local/bin/start-mock /usr/local/bin/mcp-server

WORKDIR /app
# The server talks to the mock API with throwaway credentials. require-local-api also
# enforces the localhost target at startup, so the benchmark can never reach a real account.
ENV API_BASE_URL=http://localhost:8080 \
    TT_CLIENT_ID=test \
    TT_SECRET=test \
    TT_REFRESH=test \
    TT_ENABLE_TRADING=true \
    MOCK_STATE_FILE=/app/placed_orders.jsonl
