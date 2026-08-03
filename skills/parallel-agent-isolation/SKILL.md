---
name: parallel-agent-isolation
description: Decide what stateful resources concurrent agents will share, then isolate, serialise, or re-verify serially before dispatching them. Worktrees isolate files, not services, so parallel agents collide on one database, one simulator, or one state file and both still report green.
when_to_use: Use when two or more agents will run concurrently AND their work touches something stateful outside the filesystem, such as a database, a service stack, an integration or end-to-end suite, a search index, a message broker, a cache, a fixed port, a device or simulator, a shared cloud environment or IaC state file, or a shared account or API key. Also use when judging a finished parallel agent's report, especially one saying it could not get its own instance of such a resource and used the one already running, in any wording, including "port is already allocated", "address already in use", "container name is already in use", or "no free simulator". Do not use when concurrent agents only read and write files, such as editing docs or independent source modules, since worktrees already isolate that.
---

# Parallel agents share more than the filesystem

Ask this before dispatch:

> **What stateful thing outside the filesystem will these agents share?**

A git worktree isolates files. It isolates nothing else. Two agents in separate
worktrees still query the one database, boot the one simulator, and lock the one
remote state file.

## What counts

- Databases and search indexes, and the fixtures that truncate or seed them
- Message brokers and caches, and anything holding state between requests
- Fixed ports, and container or project names derived from a directory name
- Devices, emulators, and simulators, where one is booted at a time
- Shared cloud resources: a bucket, a queue, a staging environment, an IaC state file
- A shared test account, or an API key with per-account state or rate limits

If nothing on that list is in play, the work is file-local. Dispatch in parallel
and stop reading.

## Pick one

| Strategy | Fits when |
| --- | --- |
| **Isolate.** Each agent gets its own instance, on its own ports, schema, namespace, or account. | The resource is cheap to duplicate and the parallel work is long enough to repay the setup. |
| **Serialise the stateful step.** Agents work in parallel; a lock, or the dispatcher, lets one run the suite at a time. | The shared step is short next to the work around it. |
| **Parallel, then re-verify serially.** Let them run, treat every agent's test result as unverified, and re-run the suites yourself one at a time. | The suite is fast and the agents' edits do not conflict. Say up front that their results are advisory. |
| **Split the work.** One agent owns everything that touches the resource; the rest parallelise around it. | Only some of the tasks need the resource at all. |

Re-verify serially when unsure. It is the cheapest of the four to get right, and
the only one that still works when an agent ignores its instructions.

## The collision is silent

Two suites on one database interleave. Fixtures that truncate tables around each
test delete the other run's rows mid-test. Both suites go green. The shape
repeats wherever state is shared: two runs driving one simulator tap each
other's screens, two applies against one state file each plan against a world
the other has already changed.

So an agent that could not get its own instance and used the one already there
has reported a **corrupted run, not a workaround**. The signal is any claim that
the agent reused a resource it could not create, whatever the wording:

- `port is already allocated`, `address already in use`, `container name ... is already in use`
- "no free simulator, so I used the booted one", "the shared staging database was already migrated"
- "the services were already up", "reused the existing stack", "skipped the setup step"

## Make it detectable

Put the reporting requirement in the dispatch prompt, not just the expectation:

> Report how you ran the tests: the exact command, and whether every service,
> device, environment, and account it touched was yours alone. If you could not
> get your own, stop and say so rather than using the one already running.

A green result that does not say how it was produced is unverified.

## Clean up

- Whatever an aborted start leaves half-made: a booted device, a held lock, a
  partly applied stack. Containers are the common case, stranded in `created` or
  `exited`: `docker ps -a`, then remove by project.
- Worktrees: `git worktree list`, then `git worktree remove`.
- Branches a worktree pinned. The branch will not delete while its worktree
  exists, so remove worktrees first and branches second.
