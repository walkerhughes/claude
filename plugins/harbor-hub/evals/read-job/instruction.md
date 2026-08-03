# Report a job's mean reward from the Harbor hub

An MCP server named `harbor-hub` is available to you. It exposes tools for the
Harbor hub, including `whoami`, `get_job_overview`, `get_job_trials`, and
`get_trial_detail`.

The job id to inspect is provided in the `EVAL_READ_JOB_ID` environment variable
(read it with `echo $EVAL_READ_JOB_ID`).

Your task:

1. Call the `harbor-hub` MCP tool `get_job_overview` on the job with id
   `$EVAL_READ_JOB_ID`. This is required: you are graded on having called it,
   and shelling out to the `harbor` CLI scores zero even if your answer is
   right. Do not use the raw hub API either.
2. Read the job's mean reward across its trials from that overview's aggregate.
   Other `harbor-hub` tools (`whoami`, `get_job_trials`, `get_trial_detail`)
   are available if you need them.
3. Write the mean reward to `/app/answer.txt` as exactly one line containing a
   plain decimal number, for example `0.75` or `1.0` or `0`.

The file must contain only that single number and nothing else: no extra text,
no units, no code fences.
