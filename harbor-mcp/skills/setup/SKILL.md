---
name: setup
description: Check Harbor hub authentication for the harbor-mcp server and summarize the account's current state. Use when the user runs /harbor-mcp:setup, when they ask how to authenticate or connect harbor-mcp, when they want to enable Harbor write tools, or when a harbor-hub tool has just failed with an authentication error.
---

# Harbor hub setup

`harbor auth login` is the only supported way to authenticate: it mints a key
scoped to the logged-in user and stores it in `~/.harbor/credentials.json`, which
harbor reads on its own. Never write, echo, or read back a key value, and never
run `harbor auth login` on the user's behalf; it is an interactive OAuth flow
they must complete themselves.

## Step 1: check stored credentials

```bash
command -v harbor >/dev/null && harbor auth status || uv run --project "${CLAUDE_PLUGIN_ROOT}" harbor auth status
```

The fallback matters: harbor ships inside this plugin's own environment, so the
user does not need a global harbor install. Whichever path runs, use that same
form for any `harbor` command you tell the user to run, so it matches their setup.

**This command exits 0 whether or not the user is authenticated**, so branch on
its output, not its exit code:

- Contains `Not authenticated` → go to Step 2.
- Reports `Logged in as <user> (API key sk-harbor-...)` → go to Step 3. The
  printed key is already truncated to a public prefix, so it is safe to repeat.

## Step 2: not authenticated

Tell the user to run this themselves and say when it is done:

```bash
harbor auth login
```

If `harbor` was not on their PATH in Step 1, give them the plugin form instead:

```bash
uv run --project "${CLAUDE_PLUGIN_ROOT}" harbor auth login
```

Once they confirm, note that the harbor-hub server must be restarted to pick up
new credentials, then return to Step 1.

## Step 3: confirm the key actually works

Call the harbor-hub `whoami` tool.

Step 1 only reads a local file, so it reports success for a key that has since
been revoked or expired. `whoami` is what proves the credential is live. It
returns `user_id`, `key_source`, and `key_id`, never the key.

If `whoami` fails while Step 1 said the user is logged in, the stored key is
revoked or expired. Tell them to run `harbor auth logout` and then
`harbor auth login` again.

## Step 4: summarize the account

Call `list_jobs` once with default arguments, then report a brief snapshot so the
rest of the session has context:

- How many jobs exist in total
- The two or three most recent, with name and status
- Anything still running, or finished with errors

Keep it to a few lines. Do not page through the whole account, and do not write
this to a file: it goes stale as jobs run, and re-calling `list_jobs` costs the
same as reading a cache. Call it again whenever fresh data matters.

`check_task_published` and `resolve_dataset` both require an explicit org and
name, so there is nothing to enumerate for the registry. Skip them here.

## Step 5: report write-tool status

Read tools work with any valid key. The seven write tools (`upload_job`,
`publish_task`, `publish_dataset`, `download_job`, `set_job_visibility`,
`share_job`, `delete_job`) refuse unless `HARBOR_MCP_ENABLE_WRITES=true` is set
in the server's environment. Read-only is the intended default.

State the current status in one line. Only if the user asks to enable writes,
tell them to export `HARBOR_MCP_ENABLE_WRITES=true` and restart the server. Note
that `delete_job` is permanent and additionally requires `confirm=true` per call,
which you will pass only after they explicitly approve deleting a specific job.

Do not enable writes proactively, and do not raise it when the user only asked to
get connected.
