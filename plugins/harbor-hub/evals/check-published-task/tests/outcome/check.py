"""`outcome` reward: /app/answer.txt matches whether the ref is published.

Self-truthing, as before: nothing here is a planted constant. HARBOR_API_KEY
and EVAL_TASK_REF reach the verifier through [verifier.env], so the verifier
probes the hub itself with the harbor CLI -- a download of the ref succeeds iff
it is published -- and requires the answer to match.
"""

import os
import subprocess
import tempfile
from pathlib import Path

from rewardkit import criteria, criterion


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


@criterion(description="answer.txt matches whether the task ref is published")
def answer_matches_published_truth(workspace: Path) -> bool:
    task_ref = os.environ.get("EVAL_TASK_REF", "")
    if not os.environ.get("HARBOR_API_KEY") or not task_ref:
        return False  # thread both through [verifier.env]

    answer = _answer(workspace)
    if answer not in ("yes", "no"):
        return False

    with tempfile.TemporaryDirectory() as out:
        proc = subprocess.run(
            ["harbor", "download", task_ref, "-o", out],
            capture_output=True,
            text=True,
        )
    return answer == ("yes" if proc.returncode == 0 else "no")


criteria.file_exists("answer.txt")
criteria.answer_matches_published_truth()
