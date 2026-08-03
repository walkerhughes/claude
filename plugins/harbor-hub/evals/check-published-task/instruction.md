# Check whether a task package is published on the Harbor hub

The task reference to check is provided in the `EVAL_TASK_REF` environment
variable (read it with `echo $EVAL_TASK_REF`). It has the form `org/name@ref`,
for example `hello-world/hello-world@1`.

Determine whether that task package is published on the Harbor hub. Write your
answer to `/app/answer.txt` as exactly one line:

- `yes` if the package is published, or
- `no` if it is not.

The file must contain only that single word and nothing else: no extra text,
no punctuation, no code fences.
