# Agent container for a harbor-hub eval.
#
# python:3.12-slim satisfies harbor-mcp's Python >= 3.12 requirement. curl and
# ca-certificates are needed by harbor's agent installers (e.g. the claude-code
# setup script); git is needed for the pip git+https install.
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install harbor-mcp into a DEDICATED VENV, not system site-packages, and put
# its entrypoints (harbor-mcp for the stdio MCP server declared in task.toml,
# harbor for the oracle/verifier CLI calls) on PATH via symlinks.
#
# The venv is load-bearing for modal: modal's image builder appends its own
# pinned client-dependency install into the system interpreter of every image
# AFTER these layers (e.g. builder/2024.10.txt pins typing_extensions==4.12.2,
# while pydantic_core needs the 4.13+ Sentinel), which silently breaks any
# system-python install of harbor. The venv is untouched by that injection, so
# the same image works on docker and modal.
#
# Secrets are NOT baked into this image: HARBOR_API_KEY and
# HARBOR_MCP_ENABLE_WRITES arrive at runtime via `harbor run --ae`.
#
# Local-development alternative (build against your working copy instead of
# the GitHub default branch):
#   COPY . /opt/harbor-mcp-src
#   RUN /opt/harbor-mcp/bin/pip install --no-cache-dir /opt/harbor-mcp-src
RUN python -m venv /opt/harbor-mcp \
    && /opt/harbor-mcp/bin/pip install --no-cache-dir \
        "harbor-mcp @ git+https://github.com/walkerhughes/claude.git#subdirectory=plugins/harbor-hub" \
    && ln -s /opt/harbor-mcp/bin/harbor-mcp /usr/local/bin/harbor-mcp \
    && ln -s /opt/harbor-mcp/bin/harbor /usr/local/bin/harbor

WORKDIR /app
