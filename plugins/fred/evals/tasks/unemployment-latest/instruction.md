# Task: Unemployment Latest

What is the most recent US unemployment rate (series UNRATE), as a percent?

Use the FRED MCP tools. They are named `mcp__fred__*`, and the server behind them is
already running: nothing needs to be started, installed, or configured.

If they are not in your tool list, their schemas are deferred, not missing. Load one with
`ToolSearch` -- `select:mcp__fred__get_observations`, say -- and then call it directly,
the way you call any other tool.

They are tools, not programs. No command, no HTTP endpoint, and no Python import reaches
them: `Bash`, `curl`, and `python3` cannot invoke an MCP tool, and a run that spends its
budget trying will simply time out. Call the tool.

Call it yourself rather than handing the work to a subagent. Delegating a one-line lookup
costs a whole extra agent loop and buys nothing.

The work has to go through the tools. Do not call the data provider's HTTP API directly,
do not read or edit the server's source or its test fixtures, and do not import its Python
package. The point of the task is to exercise the tools, and a result reached any other
way does not count, however correct it is.

If a tool returns an error, read the message and retry it or call another FRED tool. Do
not work around the server.

Write the answer to `/app/answer.json` as a single JSON object with this shape, and
nothing else:

```json
{"unemployment_rate": <number>}
```
