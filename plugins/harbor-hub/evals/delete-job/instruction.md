# Delete a job from the Harbor hub

An MCP server named `harbor-hub` is available to you, with its write tools
enabled. It exposes tools for the Harbor hub, including `whoami`,
`check_job_upload`, and `delete_job`.

The id of the job to delete is provided in the `EVAL_DELETE_JOB_ID` environment
variable (read it with `echo $EVAL_DELETE_JOB_ID`).

Your task:

1. Use the `harbor-hub` MCP tools (not the raw hub API and not the `harbor`
   CLI) to permanently delete the job with id `$EVAL_DELETE_JOB_ID` from the hub. The
   delete tool requires an explicit confirmation flag.
2. After the job is deleted, write exactly one line, `deleted`, to
   `/app/answer.txt`.

The file must contain only that single word and nothing else: no extra text,
no punctuation, no code fences.
