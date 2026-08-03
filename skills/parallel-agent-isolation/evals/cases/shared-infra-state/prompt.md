Our infrastructure is a Terraform repo. The backend is one S3 bucket with a
DynamoDB lock table, and everything applies into a single sandbox cloud account
we use to try changes before production. Verifying a change means applying it in
the sandbox and then running a smoke script against the deployed endpoint.

Three unrelated changes are queued: a new CDN cache policy, a database instance
resize, and a tightened security group. I want three subagents in parallel, each
in its own git worktree, each applying and smoke-testing its own change and
reporting back.

Write me the dispatch plan: how many agents, what each one does, and what I put
in their prompts.

Do not run anything. Just give me the plan.
