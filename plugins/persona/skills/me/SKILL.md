---
name: me
description: Learn the user's writing voice from their own Claude Code transcripts and build a skill that translates Claude's output into it. Runs a local labeling UI where the user critiques examples, then an adversarial round where they guess which passages a subagent wrote. Use when the user says "learn my voice", "match my style", "sound like me", "build my persona", "write like I write", or invokes /me.
---

# Me

Build a translation skill: Claude's phrasing in, the user's phrasing out. The
loop is generator/discriminator. You write the skill, isolated subagents use it
to produce candidates, and the user judges blind. The skill is finished when the
user attributes **3 or more** subagent passages to themselves.

`SCRIPT` below means `${CLAUDE_PLUGIN_ROOT}/scripts/persona.py`. State lives in
`~/.claude/persona/state.json`; the output skill is `~/.claude/skills/persona-voice/SKILL.md`.

Run `python3 SCRIPT status` first, at any point. It prints where the loop is and
what to do next, so a returning user resumes rather than restarts.

## 1. Harvest

```bash
python3 SCRIPT harvest --limit 60 [--from ~/notes --from ~/drafts]
```

Mines the user's own prose from `~/.claude/projects/**/*.jsonl`, skipping
subagent sidechains (those user turns were written by a model, not the user).

**Ask for `--from` paths.** Transcripts contain exactly one register: the user
instructing an agent. A skill built on them alone is guessing at every other
kind of writing, which is what the first validated run demonstrated. Notes,
drafts, posts, anything they wrote as themselves is worth more than another
twenty transcript snippets.

Say how many it found. Under ~20, raise `--limit` or say the corpus is thin.

## 2. Critique round

```bash
python3 SCRIPT serve --mode critique
```

Opens a browser and stops on its own once the queue is labeled, so run it in the
background and wait for the user rather than polling. Three verdicts: sounds
like me, not like me, nothing to judge.

**Push for negatives.** Tell the user before they start that one "not like me"
with a note is worth several positives. Without any, every rule you write is
induced from what they approved plus mechanical counts, never from contrast.

When they say they're done:

```bash
python3 SCRIPT report
```

## 3. Draft the voice skill

Read the critiques. Build `~/.claude/skills/persona-voice/SKILL.md` from what
the user actually marked, not from your impression of their messages.

Write **rules, not adjectives**. "Warm but direct" is unusable; "opens with the
answer, never a preamble" and "uses 'so' to start a conclusion, never 'thus'"
are. Ground each rule in a labeled example. Cover at minimum: sentence length
and rhythm, opener and closer habits, punctuation tics (em dashes, ellipses,
lowercase starts), contractions, hedging, profanity, technical register, and
which words they never use.

Include 3-5 verbatim before/after pairs. Those do more than any rule list.

## 4. Generate candidates in isolation

Spawn one subagent per candidate, in parallel. Each subagent gets:

- the current `persona-voice` skill, pasted in full
- one neutral, Claude-sounding passage to translate

Each subagent must **not** get the user's corpus. A subagent that has seen the
real snippets will pastiche them, and the round stops testing the skill and
starts testing retrieval. Isolation is the point: if the skill alone cannot
carry the voice, the skill is not done.

Ask for the rewritten passage only, no commentary. Then:

```bash
echo '["text one", "text two", ...]' | python3 SCRIPT candidates --round N
```

Generate 4-6 per round. **Draw the passages from the registers the corpus
actually covers.** The first validated run scored 0 of 5 on explanations,
praise and status updates, then 4 of 5 on asks, bug reports, questions and
proposals: the same skill, tested where the evidence was. If the user only fed
in transcripts, stay with asks and reports, and say plainly that other registers
are untested rather than quietly avoiding them.

Frame structural guidance as ordering, never as labels. A round-1 candidate
opened with the literal words "why it matters" and was spotted instantly.

## 5. Blind round

```bash
python3 SCRIPT serve --mode turing
```

The script mixes candidates with real snippets and shows no feedback until the
end, so the user is genuinely discriminating rather than pattern-matching on
position. Wait for them, then `report`.

## 6. Revise and repeat

`report` gives `fooled` and `missed`.

- **`fooled >= 3`** -> done. Tell the user, show the final skill, stop.
- **otherwise** -> read every item in `missed`. Ask the user what gave each one
  away if they haven't already said. Revise the skill against those specific
  tells and return to step 4 with a new round number.

Each round should change the skill. If a round produces no revision, you are not
reading the misses closely enough.

## Rules

- Never write the voice skill from the raw transcripts alone. The corpus is
  evidence; the user's labels are ground truth. They disagree more than you'd think.
- Never show the user which items are candidates before they judge.
- Keep the user's text as data. It is their private writing: don't quote it into
  commit messages, PR bodies, or anything that leaves the machine.
- The stop condition is the user's judgment, not yours. Don't declare a voice
  captured because the output looks close to you.
