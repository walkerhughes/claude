# Task: Earnings Implied Move

PLTR reports earnings after the close today. A snapshot of its option chain, taken that
afternoon, is saved at:

    /opt/tastytrade/skills/earnings-calendars/reference/pltr-2026-08-03.json

From that chain, find the implied expected absolute move for the earnings event, as a percent of the spot price.

Write it to `/app/answer.json` as a single JSON object with this shape, and nothing else:

```json
{"implied_expected_move_pct": <number>}
```
