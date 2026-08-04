# Task: Position Count

Find how many open positions I currently hold.

Use the Tastytrade MCP tools. They are named `mcp__tastytrade__*`, and the server behind
them is already running: nothing needs to be started, installed, or configured.

If they are not in your tool list, their schemas are deferred, not missing. Load one with
`ToolSearch` -- `select:mcp__tastytrade__get_portfolio`, say -- and then call it directly,
the way you call any other tool.

They are tools, not programs. No command, no HTTP endpoint, and no Python import reaches
them: `Bash`, `curl`, and `python3` cannot invoke an MCP tool, and a run that spends its
budget trying will simply time out. Call the tool.

Call it yourself rather than handing the work to a subagent. A subagent's tool calls are
not part of this run's record, so an answer fetched that way cannot be told apart from a
guess.

The work has to go through the tools. Do not call the brokerage's HTTP API directly, do
not read or edit its source or its fixtures, and do not import the server's Python
package. The point of the task is to exercise the tools, and a result reached any other
way does not count, however correct it is.

If a tool returns an error, read the message and retry it or call another Tastytrade tool.
Do not work around the server.

Write the answer to `/app/answer.json` as a single JSON object with this shape, and
nothing else:

```json
{"position_count": <number>}
```
