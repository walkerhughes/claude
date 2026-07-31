# Check whether a task package is published on the Harbor hub

An MCP server named `harbor-hub` is available to you. It exposes tools for the
Harbor hub, including `whoami`, `check_task_published`, and `resolve_dataset`.

The task reference to check is provided in the `EVAL_TASK_REF` environment
variable (read it with `echo $EVAL_TASK_REF`). It has the form
`org/name@ref`, for example `hello-world/hello-world@1`.

Your task:

1. Use the `harbor-hub` MCP tools (not the raw hub API and not the `harbor`
   CLI) to determine whether the task package `$EVAL_TASK_REF` exists on the
   Harbor hub.
2. Write your answer to `/app/answer.txt` as exactly one line:
   - `yes` if the package is published, or
   - `no` if it is not.

The file must contain only that single word and nothing else: no extra text,
no punctuation, no code fences.
