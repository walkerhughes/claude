---
name: earnings-calendars
description: Analyse an option chain for calendar-spread opportunities around an earnings event, and rank the candidates by risk-adjusted return. Decomposes the vol term structure into base vol plus an event jump, which also yields the expected move the market is pricing for the event alone rather than for the front expiry's total vol. Prices every calendar against three move regimes with real bid/ask, and screens on whether the profit band covers the implied move. Use when the user asks about calendar or double-calendar spreads into earnings, whether an earnings vol crush is worth selling, how big a move the options are implying for an upcoming report, how a name's implied move compares to its history, or wants an earnings options chain analysed or ranked.
---

# Earnings calendars

A calendar into earnings is one bet: **that the stock moves less than the options
say it will.** The IV crush is real and usually large, but it is only edge if the
profit band is wider than the implied move. Most of the time it isn't, and the
job here is to find that out before recommending anything.

`SCRIPT` below means `${CLAUDE_PLUGIN_ROOT}/scripts/calendars.py`. It is stdlib
only, so `python3 SCRIPT` works with no install. Run `python3 SCRIPT --selftest`
if anything looks wrong.

## 1. Confirm the event

Get the date **and** whether it is before or after the close. Do not trust
`get_market_data`'s `next_earnings` field: it has returned dates a year stale.
Verify with a web search for the company's own earnings announcement.

The front expiry must be the first one that expires *after* the report. If the
report is Monday after the close, the Friday weekly is the front.

## 2. Pull the chain

```
get_option_chain(symbol)                                  # expirations first
get_option_chain(symbol, expiration=..., strikes_near=25) # then each cycle
```

Pull the front plus **three or four** back cycles. You need the far ones even if
you would never trade them: the term-structure fit needs the long end to separate
base vol from the event jump.

Two things to expect:

- **`iv` comes back null.** Fine. The script solves IVs itself from mids, with
  the forward backed out of put-call parity. Never report an IV you didn't solve.
- **Default strike windows are too narrow.** Ask for `strikes_near=25` or more.
  You need strikes out to roughly ±1.5x the implied move to test double
  calendars and to fit the smile.

Pull calls and puts. The script uses the OTM side of each strike automatically.

## 3. Build the input file

One JSON file, written to the scratchpad:

```json
{"symbol": "PLTR", "spot": 125.64,
 "history": [14.0, 6.85, 7.94, 7.85, 12.2, 24.0, 23.5, 10.1],
 "chains": {"2026-08-07": {"dte": 4,
                           "calls": {"140": [2.34, 2.35]},
                           "puts":  {"115": [2.62, 2.65]}}}}
```

Quotes are `[bid, ask]`, never mids. Spreads decide this analysis: deep-ITM
strikes look cheapest at mid and are often quoted 50c wide.

`history` is absolute post-earnings moves in percent, most recent first, ideally
8 quarters. Search for them. If you genuinely cannot find them, say so in the
writeup, because the "calm" and "history" regimes become guesses without it.

`reference/pltr-2026-08-03.json` is a complete worked example.

If you were handed a chain file that is already in this shape, steps 1 and 2 are done:
go straight to the fit. `history` is the only field worth adding, and only if you can
find the numbers.

## 4. Fit, and apply the gate

```bash
python3 SCRIPT fit chain.json
```

Gives the term structure, the fitted event jump, and **implied E|move|**, which
is the number everything else is compared to. It also prints whether the event
looks rich, cheap, or fairly priced against the name's own history.

**The gate: if no structure's profit band covers the implied E|move| on both
sides, there is no vol edge and you should say so plainly.** A steeply inverted
term structure and a 90th-percentile IV rank are not edge. They are the market
correctly pricing a large event. This is the single most common way to talk
yourself into a bad calendar.

Note the fit's limit: `b` (base-vol slope) and the jump `J` trade off against
each other, so the split is weakly identified. E|move| is robust to about 0.3pp;
don't quote the jump to more precision than that.

## 5. Rank

```bash
python3 SCRIPT rank chain.json --skew-beta 0.6
```

Every candidate is scored against three move regimes: `calm` (the last four
quarters), `implied` (the chain's own jump), and `history` (all quarters given).
A structure that only works under `calm` is a bet that the name's moves have
permanently compressed. That may be true, but it is a view, not an edge, and it
belongs in the writeup as one.

Reading the output:

- **`wide?`** is the gate from step 4, per structure.
- **`W/L`** is average win over average loss. Read it before win rate. A 66% win
  rate with W/L 0.46 loses money, and that combination is the standard double
  calendar.
- **`ROC impl`** is the honest number. `ROC calm` is the optimistic case.
- The footer counts how many structures are positive-EV under the implied
  distribution. When that is zero, lead with it.

`--skew-beta` lifts settled vol on selloffs, which is real for high-beta names
and cushions the downside. 0.6 is a reasonable default, 0 is the conservative
case. Report which you used.

## 6. Stress the finalist, especially against it

```bash
python3 SCRIPT scenario chain.json --strikes 140 \
    --front 2026-08-07 --back 2026-09-18
```

P&L across the move range, the profit band, and the directional-fragility check.

**Always run the adverse direction.** A calendar whose band is asymmetric (say
-1% to +24%) is a direction bet wearing a vol-trade costume. The command prints
the P(down) at which it flips negative-EV. If that threshold is near 50%, the
structure has no cushion, and if the name has a recent directional pattern in its
earnings reactions, say so and name the threshold.

Also check `--strikes` for the exit assumption. Next-day exit beats holding to
front expiry in essentially every down scenario, so recommend exiting the morning
after unless something says otherwise.

## What the numbers have taught

Carry these into the writeup rather than rediscovering them:

- **Band versus E|move| first.** Everything else is secondary.
- **Doubles are usually the wrong shape.** A double is roughly twice the short
  gamma of a single for similar capital. In the tails both wings lose: the stock
  blows through one strike and runs away from the other. On PLTR, 0 of 38 double
  configs were positive-EV. Prefer a single unless the implied move is small
  relative to the strike spacing.
- **Extending the back leg barely widens the band** (~0.2 to 0.7pp going from 25
  to 46 DTE). The band is set by the extrinsic *ratio* between the legs, not
  absolute time. What the further month buys is flatter regime sensitivity and
  better fills. Prefer a standard monthly over a nearby weekly for the long leg.
- **Price with real spreads.** Quarter-spread per leg per side. This flips
  rankings and kills ITM strikes that look cheap at mid.
- **Anchor post-crush IV to settled IV**, not to a generous haircut off the
  pre-event level.

## Reporting

Lead with the verdict, then the evidence. Give the ranking the user asked for
even when the whole set is unattractive, and say plainly that it is. State which
`--skew-beta` and which regime each number came from. Quote the profit band and
E|move| together so the comparison is visible.

Close with the standing caveats: this is chain analysis rather than investment
advice, you are not a licensed advisor, and you have not placed or previewed any
orders. **Never place an order from this skill.** Order placement is a separate,
explicitly gated action, and analysis is never authorisation for it.
