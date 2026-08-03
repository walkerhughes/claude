I maintain a Go service. Its end-to-end tests run with `go test -tags e2e ./...`
against our shared staging Postgres, a managed instance in our cloud account
that everyone on the team points at. There is no local copy of it. The unit
tests need nothing.

I have two independent pieces of work queued: adding pagination to the orders
endpoint, and fixing a timezone bug in the reporting query. Each one needs the
e2e suite to pass before I will look at it.

I want to hand both to subagents at the same time, each in its own git worktree,
and have them report back. Write me the dispatch plan: how many agents, what
each one does, and what I put in their prompts.

Do not run anything. Just give me the plan.
