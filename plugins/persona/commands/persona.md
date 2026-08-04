---
description: Learn my writing voice through a labeling loop, and build a skill that translates Claude's output into it.
---

Run the persona loop using the `persona` skill.

Start by reporting where things stand, so a returning user resumes instead of
starting over:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/persona.py status
```

Then do whatever `status` says is next. If the corpus is empty this is a first
run: explain the loop in two sentences before harvesting, so the user knows they
are about to spend ten minutes labeling and why it pays off.

$ARGUMENTS may name extra prose to mine (a notes directory, a drafts folder).
Pass each as `--from PATH` on the harvest. If the user gave nothing, mention
that `--from` exists after harvesting: transcripts alone are one register, and a
skill built only on them guesses everywhere else.
