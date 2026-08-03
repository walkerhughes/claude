---
name: parallel-agent-isolation
description: Decide what stateful resources concurrent agents will share, then isolate, serialise, or re-verify serially before dispatching them. Worktrees isolate files, not services, so parallel agents collide on one database or port and both still report green.
when_to_use: Use when two or more agents will run concurrently AND their work touches something stateful outside the filesystem, such as a database, a docker compose stack, an integration or end-to-end suite, a search index, a message broker, a cache, a fixed port, a shared cloud resource or IaC state file, or a shared test account. Also use when judging a finished parallel agent's report, especially one containing "port is already allocated", "address already in use", "container name is already in use", or any statement that the agent reused services it could not start itself. Do not use when concurrent agents only read and write files, such as editing docs or independent source modules, since worktrees already isolate that.
---

# Parallel agents share more than the filesystem

Ask this before dispatch:

> **What stateful thing outside the filesystem will these agents share?**

A git worktree isolates files. It isolates nothing else. Two agents in separate
worktrees still run their suites against the one Postgres listening on 5433.

## What counts

- Databases, and the fixtures that truncate or seed them
- Search indexes, message brokers, caches
- Fixed ports, and docker compose project names derived from a directory name
- Shared cloud resources: a bucket, a queue, a deployed stack, one IaC state file
- A shared test account, or an API key with per-account state or rate limits

If nothing on that list is in play, the work is file-local. Dispatch in parallel
and stop reading.

## Pick one

| Strategy | Fits when |
| --- | --- |
| **Isolate.** Each agent gets its own instance on its own ports and its own compose project name. | The stack is cheap to duplicate and the parallel work is long enough to repay the setup. |
| **Serialise the stateful step.** Agents work in parallel; a lock, or the dispatcher, lets one run the suite at a time. | The shared step is short next to the work around it. |
| **Parallel, then re-verify serially.** Let them run, treat every agent's test result as unverified, and re-run the suites yourself one at a time. | The suite is fast and the agents' edits do not conflict. Say up front that their results are advisory. |
| **Split the work.** One agent owns everything that touches the resource; the rest parallelise around it. | Only some of the tasks need the service at all. |

Re-verify serially when unsure. It is the cheapest of the four to get right, and
the only one that still works when an agent ignores its instructions.

## The collision is silent

Two suites on one database interleave. Fixtures that truncate tables around each
test delete the other run's rows mid-test. Both suites go green. Both reports
read exactly like reports from runs that proved something.

So an agent that could not start its own services and used the ones already
running has reported a **corrupted test run, not a workaround**. Any of these in
an agent's report invalidates that agent's verification:

- `port is already allocated`, `address already in use`
- `container name ... is already in use`
- "the services were already up", "reused the existing stack", "skipped `docker compose up`"

## Make it detectable

Put the reporting requirement in the dispatch prompt, not just the expectation:

> Report how you ran the tests: the exact command, whether you started your own
> services, and the ports and compose project you used. If you could not start
> your own services, stop and say so rather than using the ones already running.

A green result that does not say how it was produced is unverified.

## Clean up

- Containers stranded in `created` or `exited` by a failed start: `docker ps -a`,
  then remove by compose project.
- Worktrees: `git worktree list`, then `git worktree remove`.
- Branches a worktree pinned. The branch will not delete while its worktree
  exists, so remove worktrees first and branches second.
