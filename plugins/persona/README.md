# persona

Two skills for writing in your own voice.

**`be-human`** is the general one: plain language, answer first, no filler, no
em dashes. It applies immediately after install, with nothing to set up. Say
"be human", ask for something in plain English, or tell Claude a response was
too jargon-heavy.

**`persona`** is the personal one. It learns *your* voice from your own writing
and builds a translation skill specific to you. That takes about ten minutes of
labeling, described below.

Use the first if you want better prose today. Use the second if you want prose
that sounds like you specifically.

## Learning your voice

The loop is generator/discriminator. Claude drafts a voice skill from snippets
you label, isolated subagents use that skill to write candidate passages, and
you judge them blind against your own real writing. When Claude fools you three
times, the skill is done.

### Use

```
/persona
```

That's it. Claude drives the whole loop and tells you what to do at each step.
Saying "learn my voice" or "make this sound like me" triggers the same skill.

Point it at writing outside your transcripts, which is worth doing:

```
/persona ~/notes ~/drafts
```

Expect to spend about ten minutes labeling. You can stop partway and resume:
`/persona` picks up where you left off.

Output lands in `~/.claude/skills/persona-voice/SKILL.md`, which Claude then
uses automatically whenever you ask for text in your voice. Labels live in
`~/.claude/persona/state.json`.

### Underneath

```bash
python3 scripts/persona.py status                 # where you are in the loop
python3 scripts/persona.py harvest --from ~/notes # mine your prose
python3 scripts/persona.py serve --mode critique  # label what sounds like you
python3 scripts/persona.py serve --mode turing    # blind: you, or a subagent?
python3 scripts/persona.py report                 # labels + fool count
```

The server stops itself once you've labeled the queue. No ctrl-c, no orphan
process holding the port.

## Getting a good result

Two things matter more than the rest:

- **Label some negatives.** "Not how I would say it", with a note. Everything
  coming back positive means every rule is induced from what you approved rather
  than from contrast, and the skill has nothing to push against.
- **Feed it more than transcripts.** Claude Code transcripts are one register:
  you instructing an agent. A skill built only on those was caught 5 times out
  of 5 on praise and status updates, then fooled 4 of 5 on asks and bug reports.
  Same skill, tested where the evidence was. `--from` is how you widen it.

## Privacy

Everything is local. The script's only network activity is an HTTP server bound
to `127.0.0.1`, and your transcripts are read from disk and rendered in your own
browser. Nothing is uploaded, and no model sees your corpus except the Claude
session you are already talking to. The candidate-writing subagents deliberately
never see it at all.

## Design notes

**One file, no dependencies.** `scripts/persona.py` is standard library only:
`http.server` for the UI, `json` for state. No `npm install`, no build step, no
`node_modules` to keep current. A framework would have bought hot reload for a
form with three buttons.

**Subagents are isolated on purpose.** A subagent that has seen your real
snippets will pastiche them, which tests retrieval rather than the skill. Each
one gets the skill and nothing else, so a passing round means the skill itself
carries the voice.

**The blind round mixes in real snippets.** Without true positives the honest
answer is always "Claude", and the fool count would measure nothing.

Run the filter's self-check with `python3 scripts/persona.py --selftest`.
