# Benchmark agent environment.
#
# One checkout of the server plus the mock FRED API, so Claude Code can be
# benchmarked over the eval tasks. Harbor installs the claude-code agent itself.
#
# Build context is the plugin root, not this directory:
#   make benchmark-build     # docker build -f evals/environment/Dockerfile .
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv for dependency management (matches the project toolchain).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# The server under test is the working tree rather than a cloned ref, so a run
# measures the code actually in front of you rather than what has been pushed.
COPY . /opt/fred
RUN cd /opt/fred && (uv sync --frozen || uv sync)

# rewardkit scores the verifiers (each tests/<name>/ becomes a named reward).
# Baked in rather than fetched at verify time so verification needs no network,
# and in its own venv so it cannot disturb the server's resolved dependencies.
RUN python -m venv /opt/rewardkit \
    && /opt/rewardkit/bin/pip install --no-cache-dir "harbor-rewardkit==0.1.*" \
    && ln -s /opt/rewardkit/bin/rewardkit /usr/local/bin/rewardkit

COPY evals/environment/scripts/ /usr/local/bin/
RUN chmod +x /usr/local/bin/require-local-api /usr/local/bin/start-mock /usr/local/bin/mcp-server

WORKDIR /app
# The server talks to the mock with a throwaway key. require-local-api also enforces the
# localhost target at startup, so a benchmark run can never reach the real FRED API or
# spend a real key: the container has no real key to spend and no route it would accept.
ENV FRED_BASE_URL=http://localhost:8080/fred \
    FRED_API_KEY=abcdef0123456789abcdef0123456789 \
    FRED_LOG_LEVEL=INFO
