# Task: Net Liq Value

Find my account's current net liquidating value, in dollars.

Use the Tastytrade MCP tools. They are named `mcp__tastytrade__*`, and the server behind
them is already running: nothing needs to be started, installed, or configured.

If they are not in your tool list, their schemas are deferred, not missing. Load one with
`ToolSearch` -- `select:mcp__tastytrade__get_portfolio`, say -- and then call it directly,
the way you call any other tool.

They are tools, not programs. No command, no HTTP endpoint, and no Python import reaches
them: `Bash`, `curl`, and `python3` cannot invoke an MCP tool, and a run that spends its
budget trying will simply time out. Call the tool.

Call it yourself rather than handing the work to a subagent. Delegating a one-line lookup
costs a whole extra agent loop and buys nothing.

The work has to go through the tools. Do not call the brokerage's HTTP API directly, do
not read or edit its source or its fixtures, and do not import the server's Python
package. The point of the task is to exercise the tools, and a result reached any other
way does not count, however correct it is.

If a tool returns an error, read the message and retry it or call another Tastytrade tool.
Do not work around the server.

Write the answer to `/app/answer.json` as a single JSON object with this shape, and
nothing else:

```json
{"net_liquidating_value": <number>}
```
