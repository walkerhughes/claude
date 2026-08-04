# persona

Learns your writing voice from your own Claude Code transcripts and builds a
skill that translates Claude's output into it.

The loop is generator/discriminator. Claude drafts a voice skill from snippets
you label, isolated subagents use that skill to write candidate passages, and
you judge them blind against your own real writing. When Claude fools you three
times, the skill is done.

## Use

Say "learn my voice" (or `/persona`) and Claude drives it. Underneath:

```bash
python3 scripts/persona.py harvest --limit 60   # mine your prose from transcripts
python3 scripts/persona.py serve --mode critique # label what sounds like you
python3 scripts/persona.py serve --mode turing   # blind: you, or a subagent?
python3 scripts/persona.py report                # labels + fool count
```

Output lands in `~/.claude/skills/persona-voice/SKILL.md`. Labels live in
`~/.claude/persona/state.json`.

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
