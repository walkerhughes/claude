# Report a job's mean reward from the Harbor hub

The job id to inspect is provided in the `EVAL_READ_JOB_ID` environment variable
(read it with `echo $EVAL_READ_JOB_ID`).

Report that job's mean reward across its trials. Write it to `/app/answer.txt`
as exactly one line containing a plain decimal number, for example `0.75` or
`1.0` or `0`.

The file must contain only that single number and nothing else: no extra text,
no units, no code fences.
