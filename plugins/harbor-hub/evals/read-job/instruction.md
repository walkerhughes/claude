# Report a job's mean reward from the Harbor hub

An MCP server named `harbor-hub` is available to you. It exposes tools for the
Harbor hub, including `whoami`, `get_job_overview`, `get_job_trials`, and
`get_trial_detail`.

The job id to inspect is provided in the `EVAL_READ_JOB_ID` environment variable
(read it with `echo $EVAL_READ_JOB_ID`).

Your task:

1. Use the `harbor-hub` MCP tools (not the raw hub API and not the `harbor`
   CLI) to look up the job with id `$EVAL_READ_JOB_ID` on the Harbor hub.
2. Determine the job's mean reward across its trials. Prefer the aggregate mean
   reward reported by the job overview; only compute it yourself from per-trial
   rewards if no aggregate is reported.
3. Write the mean reward to `/app/answer.txt` as exactly one line containing a
   plain decimal number, for example `0.75` or `1.0` or `0`.

The file must contain only that single number and nothing else: no extra text,
no units, no code fences.
