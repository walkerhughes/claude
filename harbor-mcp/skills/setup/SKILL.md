---
name: setup
description: Diagnose and fix Harbor hub credentials for the harbor-mcp server. Use when the user runs /harbor-mcp:setup, when they ask how to authenticate or connect harbor-mcp, when they want to enable Harbor write tools, or when a harbor-hub tool has just failed with an authentication or "not authenticated" error.
---

# Harbor hub setup

Verify the user's Harbor credentials, and if they are missing, guide them to
whichever of the two credential paths suits them. Never write, echo, or read
back the value of an API key.

## Step 1: check whether credentials already resolve

Call the harbor-hub server's `whoami` tool.

On success it returns `user_id`, `key_source` (`env` or `file`), and `key_id`.
Report the identity and which source was used, then go to Step 3. Nothing else
is needed.

If the tool errors with an authentication failure, or the harbor-hub server is
not connected at all, continue to Step 2.

## Step 2: pick a credential path

Credential precedence, highest first:

1. `HARBOR_API_KEY` already in the environment
2. `KEY=value` in the nearest `.env` (the server searches the working directory
   and up to three parents)
3. `~/.harbor/credentials.json`, written by `harbor auth login`

Work out which paths are already partly set up before recommending one:

```bash
command -v harbor >/dev/null && echo "harbor CLI: present" || echo "harbor CLI: absent"
test -f ~/.harbor/credentials.json && echo "credentials.json: present" || echo "credentials.json: absent"
test -f .env && echo ".env: present" || echo ".env: absent"
```

Then recommend:

- **`harbor CLI: present`**: recommend the CLI path. Tell the user to run
  `harbor auth login` themselves in their terminal. It is interactive and it
  writes the key to `~/.harbor/credentials.json`, which harbor-mcp picks up with
  no further configuration. Do not run it on their behalf.
- **`harbor CLI: absent`**: recommend the `.env` path. Tell the user to create
  a `.env` in their project root containing `HARBOR_API_KEY=sk-harbor-...`, and
  to get that key from `harbor auth login` on a machine that has the CLI, or
  from the Harbor hub web UI. Ask *them* to paste it into the file; never write
  a key value into any file yourself, and never ask them to paste it into chat.
- **`credentials.json: present` but `whoami` still failed**: the stored key is
  likely revoked or expired. Tell them to re-run `harbor auth login`.

If a `.env` already exists, you may check *whether* it contains a
`HARBOR_API_KEY` line without printing the value:

```bash
grep -q '^[[:space:]]*\(export[[:space:]]\+\)\?HARBOR_API_KEY=' .env && echo "HARBOR_API_KEY: set" || echo "HARBOR_API_KEY: missing"
```

After the user completes either path, tell them the harbor-hub server must be
restarted to pick up new credentials, then call `whoami` again to confirm.

## Step 3: report write-tool status

Read tools work with any valid key. The seven write tools (`upload_job`,
`publish_task`, `publish_dataset`, `download_job`, `set_job_visibility`,
`share_job`, `delete_job`) refuse unless `HARBOR_MCP_ENABLE_WRITES=true` is set
in the server's environment. Read-only is the intended default.

State the current status plainly. Only if the user asks to enable writes,
explain that they add `HARBOR_MCP_ENABLE_WRITES=true` to the same `.env` (or
export it in their shell) and restart the server. Note that `delete_job` is
permanent and additionally requires `confirm=true` per call, which you will pass
only after they explicitly approve deleting a specific job.

Do not enable writes proactively, and do not suggest it when the user only asked
to get connected.

## Step 4: suggest a first call

Close by suggesting `list_jobs` to confirm the connection returns real data.
