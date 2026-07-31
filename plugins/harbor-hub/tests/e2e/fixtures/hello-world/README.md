# hello-world (fixture — NOT an eval)

A trivial, deterministic, oracle-solvable task used as a **fixture** by two
consumers:

- `tests/e2e/test_hub_roundtrip.py` — the job it uploads/downloads/deletes
  through the MCP server.
- `evals/_hublib.sh` (`bootstrap_job`) — the eval runners run it with the
  oracle agent (`--upload`) to seed fresh hub jobs for the job-based evals.

It deliberately lives under `tests/e2e/fixtures/`, not `evals/`: the CI gate
runs `harbor run -p evals/`, which discovers every task directory in `evals/`,
and this canary is not an MCP eval.

It mirrors Harbor's maintained `hello-world/hello-world` task but uses a python
base image (see `environment/Dockerfile`) because modal's image builder
requires a `python` executable, which Harbor's ubuntu-based original lacks.
