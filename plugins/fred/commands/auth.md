---
description: Save or replace your FRED API key, stored only at ~/.fred-mcp/credentials.json on this computer.
allowed-tools: Bash
---

Run the credential helper:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/save-credentials.sh
```

**Do not ask the user to type or paste their API key into this conversation, and do
not read it from any file.** The script prompts for it through the operating system's
own password dialog. That keeps the key out of the transcript and out of your context,
which is the entire point of running a script instead of just asking. If the script
fails, report what it said and let the user retry it; never offer to collect the key
yourself as a workaround.

Before running it, tell the user in one or two lines what is about to happen:

- A password prompt will open, with the field masked.
- The key is written only to `~/.fred-mcp/credentials.json` on this machine, with
  owner-only permissions. Nothing is uploaded anywhere, and it is not sent to Anthropic
  or stored in the conversation.
- The key is checked against FRED before it is saved, so a mistyped key cannot replace
  a working one.
- Running this again always overwrites, which is how to rotate a key.

Then run it and report the outcome:

- On success, say where it was saved and whether it was verified. Mention that the FRED
  tools pick it up on the next call, with no restart needed.
- On a cancelled or rejected key, say the existing file was left untouched and offer to
  run it again. A free key comes from https://fredaccount.stlouisfed.org/apikeys.

If the user would rather not use a file at all, the alternative is exporting
`FRED_API_KEY` in the environment Claude Code launches with, which takes precedence over
the file. Note that a GUI launch does not inherit a shell profile, so the file is usually
the more reliable of the two.
