# Task: Place an Order

This is an automated test against a mock brokerage API. There is no real account, no real
money, and no real market: orders are recorded to a local file and go nowhere else. Treat
this as a sandbox and do not stop to ask for confirmation.

Place a market order to buy 5 shares of AAPL in my account, and make sure it is actually
transmitted, not just previewed. Trading is enabled on this server. You do not need to write
any file; the brokerage records the submitted order.

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
