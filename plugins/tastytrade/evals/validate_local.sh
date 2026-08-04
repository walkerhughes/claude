#!/usr/bin/env bash
# Validate every task's verifier WITHOUT Harbor and without a model: score the real
# rewardkit checks against synthetic trajectories and assert the reward matrix
# (see validate_in_container.sh for the table). This is the local stand-in for
# `harbor run -a oracle`, and it catches a verifier that accepts a wrong answer
# or, now, one that cannot tell the intended route from a bypass.
#
# Runs in the bench image rather than on the host: rewardkit scores these checks
# and does not build on macOS, where its litellm dependency wants a newer rustc
# than ships there. Using the same image CI uses also means the verifier under
# test is the one that will really grade a gate run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

die() { echo "error: $1" >&2; exit 1; }

docker info > /dev/null 2>&1 \
    || die "docker is not running (the verifiers need rewardkit, which lives in the bench image)"

# Rebuilt every time: the checks under test are generated, so scoring a stale
# image would report on the previous generation of tasks.
echo "==> Building tastytrade-bench"
docker build -q -f "$ROOT/evals/environment/Dockerfile" -t tastytrade-bench "$ROOT" > /dev/null

echo "==> Scoring every verifier: solved / empty / bypassed"
docker run --rm -v "$ROOT:/work:ro" tastytrade-bench bash /work/evals/validate_in_container.sh
