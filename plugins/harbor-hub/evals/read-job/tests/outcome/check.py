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


def _hub_mean_reward(job_id: str) -> float:
    """The job's mean reward per the hub.

    Raises rather than returning a sentinel when the hub cannot be read. The
    seeded job exists by construction, so a failure here is the hub or the
    network -- scoring it as a mismatch would mark a correct answer wrong and
    read as an agent or MCP defect. An errored trial names the real cause.
    """
    proc = subprocess.run(
        ["harbor", "hub", "job", "show", job_id, "--json"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"could not read job {job_id!r} from the hub: "
            f"`harbor hub job show` exited {proc.returncode}: {proc.stderr.strip()}"
        )
    try:
        return float((json.loads(proc.stdout).get("stats") or {})["avg_reward"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"could not read a mean reward for job {job_id!r} from the hub: {exc}"
        ) from exc


@criterion(description="answer.txt matches the hub's mean reward for the job")
def answer_matches_hub_mean_reward(workspace: Path) -> bool:
    job_id = os.environ.get("EVAL_READ_JOB_ID", "")
    if not os.environ.get("HARBOR_API_KEY") or not job_id:
        return False  # thread both through [verifier.env]

    answer = _answer(workspace)
    if not _DECIMAL.match(answer):
        return False

    # Raises on an unreadable hub; unreachable for an agent that wrote no
    # well-formed answer, which returns above.
    truth = _hub_mean_reward(job_id)
    return abs(float(answer) - truth) <= 1e-6


# Only file_exists is registered here -- a zero-arg @criterion self-registers
# at decoration time, so calling it again would score it twice.
criteria.file_exists("answer.txt")
