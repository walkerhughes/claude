"""`outcome` reward: the job is gone from the hub, and the agent said so.

Self-truthing, as before: nothing here is a planted constant. HARBOR_API_KEY
and EVAL_DELETE_JOB_ID reach the verifier through [verifier.env], so the
verifier confirms the deletion against the live hub with the harbor CLI --
claiming success without deleting fails.
"""

import json
import os
import subprocess
from pathlib import Path

from rewardkit import criterion


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


@criterion(description="answer.txt says exactly 'deleted'")
def answer_says_deleted(workspace: Path) -> bool:
    return _answer(workspace) == "deleted"


@criterion(description="the job is really gone from the hub")
def job_gone_from_hub(workspace: Path) -> bool:
    job_id = os.environ.get("EVAL_DELETE_JOB_ID", "")
    if not os.environ.get("HARBOR_API_KEY") or not job_id:
        return False  # thread both through [verifier.env]

    proc = subprocess.run(
        ["harbor", "hub", "job", "show", job_id, "--json"],
        capture_output=True,
        text=True,
    )
    # A missing job is not an error to the CLI: it exits 0 with `{}`. So a
    # nonzero exit, or output that will not parse, is the hub or the network,
    # never a verdict on the job. Returning False there would report "the job
    # is still on the hub" -- the agent failed -- for an infra blip. Raise so
    # the trial errors and names the real cause. Unreachable for an agent that
    # wrote no answer: answer_says_deleted carries that case, and this
    # criterion returns above without a job id.
    if proc.returncode != 0:
        raise RuntimeError(
            f"could not check whether job {job_id!r} is gone: "
            f"`harbor hub job show` exited {proc.returncode}: {proc.stderr.strip()}"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"could not check whether job {job_id!r} is gone: `harbor hub job show` returned unparseable JSON: {exc}"
        ) from exc
    # A deleted (or never-existent) job returns an empty object; a live job
    # carries a "stats" block. Treat empty/absent as gone.
    return not payload or not payload.get("stats")
