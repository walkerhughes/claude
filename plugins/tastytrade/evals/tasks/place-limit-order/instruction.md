# Task: Place an Order

This is an automated test against a mock brokerage API. There is no real account, no real
money, and no real market: orders are recorded to a local file and go nowhere else. Treat
this as a sandbox and do not stop to ask for confirmation.

Place a market order to buy 5 shares of AAPL in my account, and make sure it is actually
transmitted, not just previewed. Trading is enabled on this server. You do not need to write
any file; the brokerage records the submitted order.

Use the Tastytrade MCP tools. Do not call the brokerage's HTTP API directly and do not edit
its files: the point is to exercise the tools, and an order placed any other way does not
count.
