#!/usr/bin/env python3
"""Earnings calendar-spread analysis. Standard library only.

Decomposes an option chain's term structure into base vol plus a one-time event
jump, then prices and ranks calendar spreads against that jump.

    calendars.py fit      chain.json     # term structure -> event jump, E|move|
    calendars.py rank     chain.json     # rank candidate calendars, all regimes
    calendars.py scenario chain.json --strikes 140 --front 2026-08-07 \
                                     --back 2026-09-18   # P&L by move
    calendars.py --selftest             # assert the pricer and fit still work

Input JSON (see the skill for how to build it from get_option_chain):

    {"symbol": "PLTR", "spot": 125.64,
     "history": [14.0, 6.85, 7.94, 7.85, 12.2, 24.0, 23.5, 10.1],
     "chains": {"2026-08-07": {"dte": 4,
                               "calls": {"140": [2.34, 2.35]},
                               "puts":  {"115": [2.62, 2.65]}}, ...}}

`history` is absolute post-earnings moves in percent, most recent first. Quotes
are [bid, ask]. Every number this prints comes from those quotes; nothing is
fetched here.

ponytail: no numpy. The move distribution is a weighted grid rather than Monte
Carlo, which is exact, reproducible, and fast enough in pure Python. Swap in a
vectorised pricer only if a chain ever needs more than a few thousand strikes.
"""

import argparse
import json
import math
import sys

# Annualisation, and the carry rate used to build forwards. Override per-chain
# with a top-level "rate" key; the level barely moves a calendar, since both
# legs discount the same way.
YEAR = 365.0
DEFAULT_RATE = 0.04

# Regimes we always score against. The point is that a calendar's edge is a
# claim about which of these is right, so all three get reported side by side.
REGIMES = ("calm", "implied", "history")


# --------------------------------------------------------------------------
# Black-Scholes on forwards, plus a bisection IV solve.
# --------------------------------------------------------------------------


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs(fwd, strike, t, sigma, kind, rate=DEFAULT_RATE):
    """Undiscounted-forward Black-76, discounted back. kind is 'c' or 'p'."""
    if t <= 0:
        intrinsic = max(0.0, fwd - strike) if kind == "c" else max(0.0, strike - fwd)
        return intrinsic
    sigma = max(sigma, 1e-6)
    sq = sigma * math.sqrt(t)
    d1 = (math.log(fwd / strike) + 0.5 * sigma * sigma * t) / sq
    d2 = d1 - sq
    disc = math.exp(-rate * t)
    if kind == "c":
        return disc * (fwd * norm_cdf(d1) - strike * norm_cdf(d2))
    return disc * (strike * norm_cdf(-d2) - fwd * norm_cdf(-d1))


def implied_vol(price, fwd, strike, t, kind, rate=DEFAULT_RATE):
    """Bisection. Returns None when the price is outside the arbitrage bounds."""
    lo, hi = 1e-4, 6.0
    if bs(fwd, strike, t, lo, kind, rate) > price:
        return None
    if bs(fwd, strike, t, hi, kind, rate) < price:
        return None
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if bs(fwd, strike, t, mid, kind, rate) < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def mid(quote):
    return 0.5 * (quote[0] + quote[1])


def half_spread(quote):
    return 0.5 * (quote[1] - quote[0])


# --------------------------------------------------------------------------
# Chain plumbing.
# --------------------------------------------------------------------------


class Chain:
    """One parsed input file: quotes, forwards, ATM vols, smile shape."""

    def __init__(self, blob):
        self.symbol = blob.get("symbol", "?")
        self.spot = float(blob["spot"])
        self.history = [abs(float(h)) / 100.0 for h in blob.get("history", [])]
        self.rate = float(blob.get("rate", DEFAULT_RATE))
        self.exps = {}
        for exp, body in blob["chains"].items():
            calls = {float(k): tuple(v) for k, v in body.get("calls", {}).items()}
            puts = {float(k): tuple(v) for k, v in body.get("puts", {}).items()}
            self.exps[exp] = {"dte": int(body["dte"]), "c": calls, "p": puts}
        if not self.exps:
            raise SystemExit("no expirations in input")
        self.order = sorted(self.exps, key=lambda e: self.exps[e]["dte"])
        self.fwd = {e: self._forward(e) for e in self.order}
        self.atm = {e: self._atm_vol(e) for e in self.order}
        self.smile = self._smile()

    def t(self, exp, elapsed=0.0):
        return max((self.exps[exp]["dte"] - elapsed) / YEAR, 0.0)

    def quote(self, exp, strike, kind=None):
        """OTM side by default: puts below spot, calls above."""
        if kind is None:
            kind = "p" if strike < self.spot else "c"
        return self.exps[exp][kind].get(strike)

    def _forward(self, exp):
        """Put-call parity across near-ATM strikes, else spot carried forward."""
        e = self.exps[exp]
        t = self.t(exp)
        both = sorted(set(e["c"]) & set(e["p"]))
        near = [k for k in both if abs(k - self.spot) <= 0.06 * self.spot]
        if not near:
            return self.spot * math.exp(self.rate * t)
        fs = [k + math.exp(self.rate * t) * (mid(e["c"][k]) - mid(e["p"][k])) for k in near]
        return sum(fs) / len(fs)

    def _vol_points(self, exp):
        """(log-moneyness / sqrt(t), iv) for every OTM strike we can solve."""
        e, t, f = self.exps[exp], self.t(exp), self.fwd[exp]
        if t <= 0:
            return []
        pts = []
        for kind in ("c", "p"):
            for k, q in e[kind].items():
                if (kind == "c" and k < f) or (kind == "p" and k > f):
                    continue  # ITM: wide and uninformative
                v = implied_vol(mid(q), f, k, t, kind, self.rate)
                if v is not None:
                    pts.append((math.log(k / f) / math.sqrt(t), v))
        return sorted(pts)

    def _atm_vol(self, exp):
        pts = self._vol_points(exp)
        if not pts:
            return None
        return interp(0.0, [p[0] for p in pts], [p[1] for p in pts])

    def _smile(self):
        """Normalised skew from the expiry with the widest strike coverage.

        Picked by coverage, not by tenor: the shape only needs to be
        representative, and the event distorts level far more than shape.
        """
        pts = []
        for exp in self.order:
            p = self._vol_points(exp)
            if len(p) > len(pts):
                pts = p
        if len(pts) < 3:
            return ([0.0], [1.0])
        zs = [p[0] for p in pts]
        atm = interp(0.0, zs, [p[1] for p in pts]) or pts[0][1]
        return (zs, [p[1] / atm for p in pts])

    def skew(self, z):
        return interp(z, self.smile[0], self.smile[1])


def interp(x, xs, ys):
    """Linear interp, flat outside the knots."""
    if not xs:
        return None
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            span = xs[i] - xs[i - 1]
            if span <= 0:
                return ys[i]
            w = (x - xs[i - 1]) / span
            return ys[i - 1] * (1 - w) + ys[i] * w
    return ys[-1]


# --------------------------------------------------------------------------
# Term structure: total_var(T) = base_var(T)*T + J^2
# --------------------------------------------------------------------------


def fit_term_structure(chain):
    """Solve for base vol a + b*ln(T) and a one-time event jump J.

    Two free shape params and a jump, fit to the ATM total-variance curve.
    Coarse grid then two refinements: the surface is smooth and tiny, so this
    beats hand-rolling an optimiser.
    """
    pts = [(chain.t(e), chain.atm[e]) for e in chain.order if chain.atm[e] and chain.t(e) > 0]
    if len(pts) < 2:
        raise SystemExit("need >= 2 expirations with solvable ATM vols to fit")
    tv = [(t, v * v * t) for t, v in pts]

    def sse(a, b):
        js = []
        for t, total in tv:
            base = a + b * math.log(t)
            js.append(total - base * base * t)
        j2 = max(0.0, sum(js) / len(js))
        err = 0.0
        for (t, total), _ in zip(tv, js):
            base = a + b * math.log(t)
            err += (base * base * t + j2 - total) ** 2
        return err, j2

    lo_a, hi_a, lo_b, hi_b = 0.05, 2.0, -0.35, 0.35
    best = None
    for _ in range(3):
        step_a = (hi_a - lo_a) / 40.0
        step_b = (hi_b - lo_b) / 40.0
        for i in range(41):
            a = lo_a + i * step_a
            for j in range(41):
                b = lo_b + j * step_b
                err, j2 = sse(a, b)
                if best is None or err < best[0]:
                    best = (err, a, b, math.sqrt(j2))
        _, a, b, _ = best
        lo_a, hi_a = a - step_a, a + step_a
        lo_b, hi_b = b - step_b, b + step_b
    _, a, b, jump = best
    return a, b, jump


def base_vol(a, b, t):
    return max(0.05, a + b * math.log(max(t, 1e-6)))


def expected_abs_move(jump):
    """E|X| for X ~ N(0, jump). The number every band gets compared to."""
    return jump * math.sqrt(2.0 / math.pi)


# --------------------------------------------------------------------------
# Move distribution: a weighted grid, not a simulation.
# --------------------------------------------------------------------------


def move_grid(history, rms, lo=-0.60, hi=0.60, n=481, bw=0.18):
    """Sign-symmetrised, kernel-smoothed historical moves rescaled to `rms`.

    Earnings moves are bimodal: the stock rarely sits still. A normal centred on
    zero understates the gap-away cases that decide a calendar, so the empirical
    shape is kept and only its scale is set.
    """
    if not history:
        history = [rms]
    # Smoothing widens each atom, so shrink the centres by the same factor to
    # land on the requested rms rather than above it.
    hist_rms = math.sqrt(sum(h * h for h in history) / len(history))
    scale = rms / (hist_rms * math.sqrt(1.0 + bw * bw))
    centres = [s * h * scale for h in history for s in (-1.0, 1.0)]
    step = (hi - lo) / (n - 1)
    grid = [lo + i * step for i in range(n)]
    w = [0.0] * n
    for c in centres:
        sd = max(bw * abs(c), 0.004)
        # Normalise each kernel to unit mass. Without this a wide kernel spans
        # more grid points and silently outweighs a narrow one, which tilts the
        # whole distribution toward the largest historical moves.
        k = [0.0] * n
        for i, g in enumerate(grid):
            z = (g - c) / sd
            if abs(z) < 6.0:
                k[i] = math.exp(-0.5 * z * z)
        mass = sum(k)
        if mass <= 0:
            continue
        for i, v in enumerate(k):
            w[i] += v / mass
    total = sum(w)
    if total <= 0:
        raise SystemExit("degenerate move distribution")
    return grid, [x / total for x in w]


def regime_rms(chain, jump):
    """calm = recent quarters, implied = the chain's own jump, history = all of it."""
    h = chain.history
    out = {"implied": jump}
    if h:
        recent = h[: min(4, len(h))]
        out["calm"] = math.sqrt(sum(x * x for x in recent) / len(recent))
        out["history"] = math.sqrt(sum(x * x for x in h) / len(h))
    else:
        out["calm"] = jump * 0.75
        out["history"] = jump * 1.15
    return out


# --------------------------------------------------------------------------
# Pricing a calendar after the event.
# --------------------------------------------------------------------------


def leg_value(chain, a, b, strike, exp, spot1, vol_adj, elapsed, kind):
    t = chain.t(exp, elapsed)
    if t <= 0:
        return max(0.0, spot1 - strike) if kind == "c" else max(0.0, strike - spot1)
    z = math.log(strike / spot1) / math.sqrt(t)
    vol = max(0.05, (base_vol(a, b, t) + vol_adj) * chain.skew(z))
    return bs(spot1 * math.exp(chain.rate * t), strike, t, vol, kind, chain.rate)


def calendar_cost(chain, strikes, front, back):
    """Entry debit at mid plus a quarter-spread per leg. None if unquotable."""
    debit = slip = 0.0
    for k in strikes:
        kind = "p" if k < chain.spot else "c"
        qf, qb = chain.quote(front, k, kind), chain.quote(back, k, kind)
        if qf is None or qb is None:
            return None
        debit += mid(qb) - mid(qf)
        slip += 0.5 * (half_spread(qf) + half_spread(qb))
    if debit + slip <= 0.05:
        return None
    return debit + slip, slip


def calendar_pnl(
    chain, a, b, strikes, front, back, moves, cost, front_adj=0.0, back_adj=0.0, skew_beta=0.0, elapsed=1.0
):
    """P&L per move. skew_beta lifts settled vol on selloffs (spot-vol corr)."""
    entry, slip = cost
    out = []
    for m in moves:
        spot1 = chain.spot * math.exp(m)
        bump = skew_beta * max(0.0, -m)
        val = 0.0
        for k in strikes:
            kind = "p" if k < chain.spot else "c"
            val += leg_value(chain, a, b, k, back, spot1, back_adj + bump, elapsed, kind)
            val -= leg_value(chain, a, b, k, front, spot1, front_adj + bump, elapsed, kind)
        out.append(val - slip - entry)
    return out


def summarise(pnl, weights, entry):
    ev = sum(p * w for p, w in zip(pnl, weights))
    var = sum((p - ev) ** 2 * w for p, w in zip(pnl, weights))
    sd = math.sqrt(max(var, 1e-12))
    pwin = sum(w for p, w in zip(pnl, weights) if p > 0)
    wins = [(p, w) for p, w in zip(pnl, weights) if p > 0]
    losses = [(p, w) for p, w in zip(pnl, weights) if p <= 0]
    aw = sum(p * w for p, w in wins) / sum(w for _, w in wins) if wins else 0.0
    al = sum(p * w for p, w in losses) / sum(w for _, w in losses) if losses else 0.0
    # 5% left tail, walking the grid in P&L order.
    order = sorted(zip(pnl, weights))
    acc, tail = 0.0, []
    for p, w in order:
        if acc >= 0.05:
            break
        take = min(w, 0.05 - acc)
        tail.append((p, take))
        acc += take
    cvar = sum(p * w for p, w in tail) / acc if acc > 0 else 0.0
    return {
        "ev": ev,
        "sd": sd,
        "pwin": pwin,
        "roc": ev / entry,
        "sharpe": ev / sd,
        "avg_win": aw,
        "avg_loss": al,
        "wl": (aw / abs(al)) if al < 0 else float("inf"),
        "cvar5": cvar,
    }


def profit_band(chain, a, b, strikes, front, back, cost, skew_beta=0.0):
    """Contiguous move range where the trade makes money. The screening gate."""
    grid = [-0.50 + i * 0.0025 for i in range(401)]
    pnl = calendar_pnl(chain, a, b, strikes, front, back, grid, cost, skew_beta=skew_beta)
    pos = [g for g, p in zip(grid, pnl) if p > 0]
    if not pos:
        return None, max(pnl)
    return (min(pos), max(pos)), max(pnl)


# --------------------------------------------------------------------------
# Candidate generation.
# --------------------------------------------------------------------------


def candidates(chain, front, back, max_moneyness=0.14, doubles=True):
    """Singles near the money, plus doubles that straddle spot."""
    ks = sorted(
        k
        for k in set(list(chain.exps[front]["c"]) + list(chain.exps[front]["p"]))
        if chain.quote(front, k) and chain.quote(back, k)
    )
    out = [[k] for k in ks if abs(k - chain.spot) <= max_moneyness * chain.spot]
    if doubles:
        for i, k1 in enumerate(ks):
            for k2 in ks[i + 1 :]:
                if k1 < chain.spot < k2 and 0.04 * chain.spot <= k2 - k1 <= 0.25 * chain.spot:
                    out.append([k1, k2])
    return out


def pairs(chain, max_front_dte=10):
    """(front, back): front is the first expiry after the event, backs follow."""
    fronts = [e for e in chain.order if chain.exps[e]["dte"] <= max_front_dte]
    if not fronts:
        fronts = chain.order[:1]
    front = fronts[0]
    return [(front, b) for b in chain.order if chain.exps[b]["dte"] > chain.exps[front]["dte"]]


# --------------------------------------------------------------------------
# Commands.
# --------------------------------------------------------------------------


def load(path):
    with open(path) as fh:
        return Chain(json.load(fh))


def cmd_fit(args):
    chain = load(args.chain)
    a, b, jump = fit_term_structure(chain)
    eam = expected_abs_move(jump)
    print(f"{chain.symbol}  spot {chain.spot:.2f}")
    print(f"\n{'expiry':12}{'dte':>5}{'fwd':>9}{'ATM IV':>9}{'base(de-earnings)':>20}")
    for e in chain.order:
        v = chain.atm[e]
        bv = base_vol(a, b, chain.t(e))
        shown = f"{v * 100:8.1f}%" if v else "       na"
        print(f"{e:12}{chain.exps[e]['dte']:>5}{chain.fwd[e]:>9.2f}{shown}{bv * 100:>19.1f}%")
    print(f"\nbase vol(T) = {a:.4f} {b:+.4f}*ln(T)")
    print(f"implied event jump   sigma = {jump * 100:.2f}%")
    print(f"implied E|move|            = {eam * 100:.2f}%   <-- compare every profit band to this")
    if chain.history:
        h = chain.history
        rec = h[: min(4, len(h))]
        s = sorted(h)
        med = s[len(s) // 2] if len(s) % 2 else 0.5 * (s[len(s) // 2 - 1] + s[len(s) // 2])
        print(
            f"\nhistorical |move|  n={len(h)}  median {med * 100:.1f}%  "
            f"mean {sum(h) / len(h) * 100:.1f}%  "
            f"rms {math.sqrt(sum(x * x for x in h) / len(h)) * 100:.1f}%"
        )
        print(f"  most recent {len(rec)}: rms {math.sqrt(sum(x * x for x in rec) / len(rec)) * 100:.1f}%")
        rms_all = math.sqrt(sum(x * x for x in h) / len(h))
        verdict = (
            "event vol looks RICH vs history"
            if jump > rms_all * 1.15
            else "event vol looks CHEAP vs history"
            if jump < rms_all * 0.85
            else "event vol is FAIRLY PRICED vs history (no vol edge to harvest)"
        )
        print(f"  verdict: {verdict}")


def cmd_rank(args):
    chain = load(args.chain)
    a, b, jump = fit_term_structure(chain)
    eam = expected_abs_move(jump)
    rms = regime_rms(chain, jump)
    grids = {r: move_grid(chain.history, rms[r]) for r in REGIMES}

    rows = []
    for front, back in pairs(chain):
        for ks in candidates(chain, front, back, doubles=not args.no_doubles):
            cost = calendar_cost(chain, ks, front, back)
            if cost is None:
                continue
            band, peak = profit_band(chain, a, b, ks, front, back, cost, args.skew_beta)
            stats = {}
            for r in REGIMES:
                g, w = grids[r]
                pnl = calendar_pnl(chain, a, b, ks, front, back, g, cost, skew_beta=args.skew_beta)
                stats[r] = summarise(pnl, w, cost[0])
            rows.append(
                {
                    "ks": ks,
                    "front": front,
                    "back": back,
                    "entry": cost[0],
                    "slip": 2 * cost[1],
                    "band": band,
                    "peak": peak,
                    "stats": stats,
                    "mean_sharpe": sum(stats[r]["sharpe"] for r in REGIMES) / len(REGIMES),
                }
            )
    if not rows:
        raise SystemExit("no quotable calendars; check that strikes overlap between expiries")
    rows.sort(key=lambda r: -r["mean_sharpe"])

    print(f"{chain.symbol}  spot {chain.spot:.2f}   event jump {jump * 100:.1f}%   implied E|move| {eam * 100:.1f}%")
    print("regime rms: " + "  ".join(f"{r}={rms[r] * 100:.1f}%" for r in REGIMES))
    print(
        f"\n{'strikes':14}{'cycle':22}{'entry':>7}{'slip':>6}{'band':>17}{'wide?':>7}"
        + "".join(f"{'ROC ' + r[:4]:>10}" for r in REGIMES)
        + f"{'meanSh':>8}{'W/L':>6}"
    )
    for r in rows[: args.top]:
        lbl = "/".join(f"{k:g}" for k in r["ks"])
        cyc = f"{r['front'][5:]}-{r['back'][5:]}"
        if r["band"]:
            band = f"[{r['band'][0] * 100:+.0f}%,{r['band'][1] * 100:+.0f}%]"
            wide = "yes" if min(abs(r["band"][0]), abs(r["band"][1])) >= eam else "NO"
        else:
            band, wide = "none", "NO"
        print(
            f"{lbl:14}{cyc:22}{r['entry']:>7.2f}{r['slip']:>6.2f}{band:>17}{wide:>7}"
            + "".join(f"{r['stats'][x]['roc'] * 100:>9.1f}%" for x in REGIMES)
            + f"{r['mean_sharpe']:>8.3f}{r['stats']['implied']['wl']:>6.2f}"
        )
    print("\n'wide?' = does the profit band cover the implied E|move| on both sides.")
    print("A NO means the trade needs a below-consensus move to pay. Check W/L too:")
    print("a high win rate with W/L well under 1 is the classic double-calendar trap.")
    pos = [r for r in rows if r["stats"]["implied"]["roc"] > 0]
    print(f"\n{len(pos)} of {len(rows)} structures are positive-EV under the implied distribution.")


def cmd_scenario(args):
    chain = load(args.chain)
    a, b, jump = fit_term_structure(chain)
    ks = [float(x) for x in args.strikes.split(",")]
    cost = calendar_cost(chain, ks, args.front, args.back)
    if cost is None:
        raise SystemExit("that structure is not quotable in the input")
    entry, slip = cost
    lbl = "/".join(f"{k:g}" for k in ks)
    print(f"{chain.symbol} {lbl} calendar   short {args.front}  long {args.back}")
    print(f"entry {entry:.2f} (incl {slip:.2f} slip)   spot {chain.spot:.2f}\n")

    betas = [0.0, args.skew_beta] if args.skew_beta else [0.0]
    moves = [x / 100.0 for x in (0, -2, -5, -7, -10, -12, -15, -20, -25, 2, 5, 7, 10, 12, 15, 20, 25)]
    moves = sorted(set(moves))
    print("P&L by realised move (next-day exit), by spot-vol beta k:")
    print(f"{'move':>7}{'spot':>9}" + "".join(f"{'k=' + str(k):>10}" for k in betas) + f"{'  %debit':>10}")
    for m in moves:
        row = [calendar_pnl(chain, a, b, ks, args.front, args.back, [m], cost, skew_beta=k)[0] for k in betas]
        print(
            f"{m * 100:>6.0f}%{chain.spot * math.exp(m):>9.2f}"
            + "".join(f"{v:>10.2f}" for v in row)
            + f"{row[-1] / entry * 100:>9.0f}%"
        )

    for k in betas:
        band, peak = profit_band(chain, a, b, ks, args.front, args.back, cost, k)
        if band:
            print(
                f"\nk={k}: profit band [{band[0] * 100:+.1f}%, {band[1] * 100:+.1f}%]  "
                f"(spot {chain.spot * math.exp(band[0]):.2f} to "
                f"{chain.spot * math.exp(band[1]):.2f})   peak +{peak:.2f}"
            )
        else:
            print(f"\nk={k}: no profitable move. peak {peak:+.2f}")

    # Directional fragility: an asymmetric band is a direction bet in disguise.
    rms = regime_rms(chain, jump)
    g, w = move_grid(chain.history, rms["implied"])
    for k in betas:
        pnl = calendar_pnl(chain, a, b, ks, args.front, args.back, g, cost, skew_beta=k)
        dn = [(p, wt) for p, wt, m in zip(pnl, w, g) if m < 0]
        up = [(p, wt) for p, wt, m in zip(pnl, w, g) if m >= 0]
        wd, wu = sum(x[1] for x in dn), sum(x[1] for x in up)
        ed = sum(p * x for p, x in dn) / wd if wd else 0.0
        eu = sum(p * x for p, x in up) / wu if wu else 0.0
        ev = sum(p * x for p, x in zip(pnl, w))
        thresh = eu / (eu - ed) if eu > 0 > ed else None
        line = f"\nk={k}: E[P&L|down] {ed:+.2f}   E[P&L|up] {eu:+.2f}   EV {ev:+.2f} ({ev / entry * 100:+.1f}%)"
        if thresh is not None:
            line += f"\n      flips negative-EV once P(down) exceeds {thresh * 100:.0f}%"
        print(line)


# --------------------------------------------------------------------------
# Self-test.
# --------------------------------------------------------------------------


def selftest():
    # Pricer round-trips through the IV solver.
    f, k, t, v = 100.0, 100.0, 0.25, 0.40
    px = bs(f, k, t, v, "c")
    got = implied_vol(px, f, k, t, "c")
    assert abs(got - v) < 1e-4, got

    # Put-call parity holds on the pricer.
    c = bs(105.0, 100.0, 0.5, 0.3, "c")
    p = bs(105.0, 100.0, 0.5, 0.3, "p")
    assert abs((c - p) - math.exp(-DEFAULT_RATE * 0.5) * 5.0) < 1e-8, (c, p)

    # A synthetic chain built from a known (flat base vol, jump) is recovered.
    spot, a0, j0 = 100.0, 0.50, 0.12
    chains = {}
    for name, dte in (("2026-01-05", 4), ("2026-01-12", 11), ("2026-01-30", 29), ("2026-02-20", 50)):
        t = dte / YEAR
        tot = a0 * a0 * t + j0 * j0
        sig = math.sqrt(tot / t)
        fwd = spot * math.exp(DEFAULT_RATE * t)
        calls, puts = {}, {}
        for strike in range(80, 126, 5):
            calls[str(strike)] = _tight(bs(fwd, strike, t, sig, "c"))
            puts[str(strike)] = _tight(bs(fwd, strike, t, sig, "p"))
        chains[name] = {"dte": dte, "calls": calls, "puts": puts}
    chain = Chain({"symbol": "TEST", "spot": spot, "history": [10, 12, 8, 14], "chains": chains})
    a, b, jump = fit_term_structure(chain)
    assert abs(jump - j0) < 0.01, f"jump {jump} != {j0}"
    assert abs(base_vol(a, b, 20 / YEAR) - a0) < 0.03, base_vol(a, b, 20 / YEAR)

    # Flat smile in, flat skew out.
    assert abs(chain.skew(0.0) - 1.0) < 0.02, chain.skew(0.0)

    # Move grid: weights normalise and rms is hit.
    g, w = move_grid([10, 12, 8, 14], 0.13)
    assert abs(sum(w) - 1.0) < 1e-9
    rms = math.sqrt(sum(x * x * wt for x, wt in zip(g, w)))
    assert abs(rms - 0.13) < 0.003, rms

    # A calendar is worth more at its strike than far away from it.
    cost = calendar_cost(chain, [100.0], "2026-01-05", "2026-01-30")
    assert cost is not None
    at, away = calendar_pnl(chain, a, b, [100.0], "2026-01-05", "2026-01-30", [0.0, 0.35], cost)
    assert at > away, (at, away)

    # Band is finite and brackets zero for an ATM calendar.
    band, peak = profit_band(chain, a, b, [100.0], "2026-01-05", "2026-01-30", cost)
    assert band and band[0] < 0 < band[1], band
    assert peak > 0

    # Summary stats: EV of a constant payoff is that constant.
    s = summarise([2.0, 2.0], [0.5, 0.5], 1.0)
    assert abs(s["ev"] - 2.0) < 1e-9 and abs(s["pwin"] - 1.0) < 1e-9

    print("selftest ok")


def _tight(px):
    """A synthetic 2c-wide quote around a theoretical price."""
    return [round(max(px - 0.01, 0.01), 4), round(max(px + 0.01, 0.02), 4)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    f = sub.add_parser("fit", help="term structure -> base vol + event jump")
    f.add_argument("chain")
    f.set_defaults(fn=cmd_fit)

    r = sub.add_parser("rank", help="rank calendars across move regimes")
    r.add_argument("chain")
    r.add_argument("--top", type=int, default=12)
    r.add_argument("--no-doubles", action="store_true")
    r.add_argument("--skew-beta", type=float, default=0.0, help="lift settled vol by beta*|move| on selloffs (try 0.6)")
    r.set_defaults(fn=cmd_rank)

    s = sub.add_parser("scenario", help="P&L by move for one structure")
    s.add_argument("chain")
    s.add_argument("--strikes", required=True, help="e.g. 140 or 115,140")
    s.add_argument("--front", required=True)
    s.add_argument("--back", required=True)
    s.add_argument("--skew-beta", type=float, default=0.6)
    s.set_defaults(fn=cmd_scenario)

    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    if not getattr(args, "fn", None):
        ap.print_help()
        sys.exit(1)
    args.fn(args)


if __name__ == "__main__":
    main()
