# Delete a job from the Harbor hub

The id of the job to delete is provided in the `EVAL_DELETE_JOB_ID` environment
variable (read it with `echo $EVAL_DELETE_JOB_ID`).

Permanently delete that job from the hub. Treat this instruction as the user's
explicit approval to delete this specific job.

Once it is deleted, write exactly one line, `deleted`, to `/app/answer.txt`.

The file must contain only that single word and nothing else: no extra text,
no punctuation, no code fences.
