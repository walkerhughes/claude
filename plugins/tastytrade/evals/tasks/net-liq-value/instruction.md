# Task: Net Liq Value

Find my account's current net liquidating value, in dollars.

Use the Tastytrade MCP tools. They are already connected and ready: you do not need to
start, install, configure, or inspect anything before calling one.

The work has to go through them. Do not call the brokerage's HTTP API directly, do not
read or edit its source or its fixtures, and do not import the server's Python package.
The point of the task is to exercise the tools, and a result reached any other way does
not count, however correct it is.

If a tool returns an error, read the message and retry it or call another Tastytrade tool.
Do not work around the server.

Write the answer to `/app/answer.json` as a single JSON object with this shape, and
nothing else:

```json
{"net_liquidating_value": <number>}
```
