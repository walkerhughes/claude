# Task: Place an Order

This is an automated test against a mock brokerage API. There is no real account, no real
money, and no real market: orders are recorded to a local file and go nowhere else. Treat
this as a sandbox and do not stop to ask for confirmation.

Place a market order to buy 5 shares of AAPL in my account, and make sure it is actually
transmitted, not just previewed. Trading is enabled on this server. You do not need to write
any file; the brokerage records the submitted order.

Use the Tastytrade MCP tools. They are already connected and ready: you do not need to
start, install, configure, or inspect anything before calling one.

The work has to go through them. Do not call the brokerage's HTTP API directly, do not
read or edit its source or its fixtures, and do not import the server's Python package.
The point of the task is to exercise the tools, and a result reached any other way does
not count, however correct it is.

If a tool returns an error, read the message and retry it or call another Tastytrade tool.
Do not work around the server.
