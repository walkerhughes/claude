"""`outcome` reward: /app/answer.txt matches the hub's mean reward for the job.

Self-truthing, as before: nothing here is a planted constant. HARBOR_API_KEY
and EVAL_READ_JOB_ID reach the verifier through [verifier.env], so the ground
truth is recomputed live from the hub with the harbor CLI and compared.
"""

import json
import os
import re
import subprocess
from pathlib import Path

from rewardkit import criteria, criterion

# One line, a plain decimal, nothing else -- no units, prose, or code fences.
_DECIMAL = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")


def _answer(workspace: Path) -> str:
    """The trimmed contents of answer.txt, or "" if it isn't there.

    A raising criterion errors the whole trial rather than scoring 0, which
    would turn the nop agent's empty run into a harness error instead of the
    zero the eval-safety check expects.
    """
    try:
        return (workspace / "answer.txt").read_text().replace("\r", "").strip()
    except OSError:
        return ""


def _hub_mean_reward(job_id: str) -> float | None:
    """The job's mean reward per the hub, or None if it can't be read."""
    proc = subprocess.run(
        ["harbor", "hub", "job", "show", job_id, "--json"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    try:
        return float((json.loads(proc.stdout).get("stats") or {})["avg_reward"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


@criterion(description="answer.txt matches the hub's mean reward for the job")
def answer_matches_hub_mean_reward(workspace: Path) -> bool:
    job_id = os.environ.get("EVAL_READ_JOB_ID", "")
    if not os.environ.get("HARBOR_API_KEY") or not job_id:
        return False  # thread both through [verifier.env]

    answer = _answer(workspace)
    if not _DECIMAL.match(answer):
        return False

    truth = _hub_mean_reward(job_id)
    return truth is not None and abs(float(answer) - truth) <= 1e-6


criteria.file_exists("answer.txt")
criteria.answer_matches_hub_mean_reward()
