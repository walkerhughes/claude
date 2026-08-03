# Delete a job from the Harbor hub

An MCP server named `harbor-hub` is available to you, with its write tools
enabled. It exposes tools for the Harbor hub, including `whoami`,
`check_job_upload`, and `delete_job`.

The id of the job to delete is provided in the `EVAL_DELETE_JOB_ID` environment
variable (read it with `echo $EVAL_DELETE_JOB_ID`).

Your task:

1. Call the `harbor-hub` MCP tool `delete_job` to permanently delete the job
   with id `$EVAL_DELETE_JOB_ID` from the hub; it requires an explicit
   confirmation flag. This is required: you are graded on having called it,
   and shelling out to the `harbor` CLI scores zero even if the job ends up
   deleted. Do not use the raw hub API either.
2. After the job is deleted, write exactly one line, `deleted`, to
   `/app/answer.txt`.

The file must contain only that single word and nothing else: no extra text,
no punctuation, no code fences.
