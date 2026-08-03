I maintain a Python service. Its integration suite talks to Postgres on port
5433 and OpenSearch on port 9200, both brought up by `docker compose up -d` from
the repo root. The unit suite needs neither.

I have two independent pieces of work queued: adding a new retrieval strategy,
and fixing a migration ordering bug. Each one needs `make test-integration` to
pass before I will look at it.

I want to hand both to subagents at the same time, each in its own git worktree,
and have them report back. Write me the dispatch plan: how many agents, what
each one does, and what I put in their prompts.

Do not run anything. Just give me the plan.
