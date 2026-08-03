---
name: parallel-agent-isolation
description: Decide what stateful resources concurrent agents will share, then isolate, serialise, or re-verify serially before dispatching them. Worktrees isolate files, not services, so parallel agents collide on one database, one simulator, or one state file and both still report green.
when_to_use: Use when two or more agents will run concurrently AND their work touches something stateful outside the filesystem, such as a database, a service stack, an integration or end-to-end suite, a search index, a message broker, a cache, a fixed port, a device or simulator, a shared cloud environment or IaC state file, or a shared account or API key. Also use when judging a finished parallel agent's report, especially one saying it could not get its own instance of such a resource and used the one already running, in any wording, including "port is already allocated", "address already in use", "container name is already in use", or "no free simulator". Do not use when concurrent agents only read and write files, such as editing docs or independent source modules, since worktrees already isolate that.
---

# Parallel agents share more than the filesystem

Decide what concurrently running agents will contend for before dispatching
them, and treat any result produced under contention as unverified.

A git worktree isolates files and nothing else. Agents in separate worktrees
still query the one database, boot the one device, hold the one lock, and spend
the one account's quota. Shared state is whatever exists as a single instance
and carries changes between calls, so what one agent does lands where another
will read it.

## The failure is silent

Contention does not raise an error. Two suites against one database interleave,
and a fixture truncating tables between tests deletes the other run's rows
mid-test, so both go green. Two runs driving one device tap each other's
screens. Two applies against one state file each plan against a world the other
has already changed. All of them report success, indistinguishably from an
honest run.

So this is decided before dispatch, not diagnosed after. Afterwards there is
nothing to find, only the question of whether the result was produced under
contention, and a result produced under contention is unverified whatever it
says.

## The pre-dispatch workflow

**1. Name what will be contended for.** Ask what stateful things outside the
filesystem these agents will share, and name each one separately. The obvious
resource usually hides a second, and resolving one leaves the other shared. If
the honest answer is nothing, the work is file-local: dispatch in parallel and
stop here.

**2. Choose how the contention resolves.** Any of the four chosen deliberately
beats meeting the collision later.

- **Isolate.** Each agent gets its own instance, ports, schema, or account. Fits
  when duplicating the resource is cheap next to the work it unblocks.
- **Serialise the stateful step.** Agents run in parallel, and the dispatcher
  lets one at a time through the step that touches the resource. Fits when that
  step is short next to the work around it. A built-in lock is not this: it
  covers only the thing it guards, leaving whatever that thing mutates still
  shared, so the serialised region has to span the change and the verification
  that depends on it.
- **Parallel, then verify serially.** Take every agent's result as advisory and
  re-run the verification yourself, one at a time. Fits when verification is
  cheap, and it is the only option that still holds when an agent ignores its
  instructions, so prefer it when unsure.
- **Split the work.** One agent owns everything touching the resource; the rest
  parallelise around it. Fits when only some tasks need the resource at all.

**3. Dispatch with the reporting requirement.** Require each agent to report how
it verified its work, not just the outcome: the command it ran, and whether
every service, device, environment, and account that command touched was its
alone. Say up front that a result which cannot answer that is advisory. A green
result that does not say how it was produced is unverified.

## The anti-pattern

An agent reports that it could not obtain its own instance of a shared resource,
used the one already running, and finished green. That is a corrupted run
presented as a workaround. It invalidates its own result rather than excusing
it, and casts the same doubt over every other agent that was using the resource
at the time.
