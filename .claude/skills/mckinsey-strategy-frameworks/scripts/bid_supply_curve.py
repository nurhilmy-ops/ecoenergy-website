#!/usr/bin/env python3
"""Industry cost curve / bid supply curve for quota auctions (LSS-style) and
merit-order markets (SMP-style).

Two pricing rules:
  --pricing pay-as-bid  (default) Each winner is paid its own bid; capacity is
        awarded cheapest-first until the quota is full. This is how Malaysia's
        LSS rounds work -- the cost curve predicts the CUT-OFF tariff, not a
        single market price. Projects are lumpy: a bid that does not fit inside
        the remaining quota is either the end of the award (--lumpy stop) or
        passed over for a smaller cheaper one (--lumpy skip).
  --pricing marginal    Uniform clearing price set by the last unit needed to
        meet demand (the McKinsey commodity cost curve; also how a merit-order
        System Marginal Price behaves). Margin = price - own cost.

Input CSV columns (header required):
  name, capacity_mw, cost            required. cost = the tariff the bidder needs
                                     (sen/kWh) at its hurdle IRR -- for us, the
                                     floor from the financial model.
  low, high                          optional range for a competitor's cost
                                     (triangular low/cost/high in Monte Carlo)
  p_compliant                        optional probability the bid passes the
                                     technical/financial evaluation (default 1)
  adj                                optional evaluation adjustment used only for
                                     RANKING (e.g. a preference margin), same unit
  us                                 optional: 1/y marks our own bid (max one row)

Usage:
  python bid_supply_curve.py bids.csv --quota 2200 [--quota 1650 ...] --out outdir
         [--pricing pay-as-bid|marginal] [--lumpy stop|skip] [--sims 3000]
         [--bid-grid LOW HIGH STEP] [--unit "sen/kWh"] [--title "..."]

Outputs: <out>/curve_summary.md, <out>/cost_curve.png, and (pay-as-bid with an
'us' row) <out>/win_probability.png.
"""
import argparse
import csv
import os
import random


def load(path):
    rows = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            g = lambda k, d=None: (r.get(k) or "").strip() or d
            cost = float(g("cost"))
            rows.append(dict(
                name=g("name"), mw=float(g("capacity_mw")), cost=cost,
                low=float(g("low", cost)), high=float(g("high", cost)),
                p=float(g("p_compliant", 1.0)), adj=float(g("adj", 0.0)),
                us=str(g("us", "")).lower() in ("1", "y", "yes", "true"),
            ))
    if sum(r["us"] for r in rows) > 1:
        raise SystemExit("Only one row may be marked us=1")
    for r in rows:
        if not r["low"] <= r["cost"] <= r["high"]:
            raise SystemExit(f"{r['name']}: need low <= cost <= high")
    return rows


def award(stack, quota, lumpy):
    """stack: list of (eval_bid, mw, key) sorted ascending. Returns set of keys awarded."""
    won, used = set(), 0.0
    for bid, mw, key in stack:
        if used + mw <= quota + 1e-9:
            won.add(key)
            used += mw
        elif lumpy == "stop":
            break
    return won


def pay_as_bid_det(rows, quota, lumpy):
    stack = sorted(((r["cost"] + r["adj"], r["mw"], i) for i, r in enumerate(rows)),
                   key=lambda t: (t[0], rows[t[2]]["us"]))  # ties: we rank after rivals
    won = award(stack, quota, lumpy)
    cutoff = max((rows[i]["cost"] + rows[i]["adj"] for i in won), default=None)
    first_out = next((rows[k]["cost"] + rows[k]["adj"] for _, _, k in stack if k not in won), None)
    mw = sum(rows[i]["mw"] for i in won)
    return won, cutoff, first_out, mw


def marginal_det(rows, demand):
    order = sorted(range(len(rows)), key=lambda i: rows[i]["cost"])
    used, price, dispatched = 0.0, None, {}
    for i in order:
        if used >= demand - 1e-9:
            break
        take = min(rows[i]["mw"], demand - used)
        dispatched[i] = take
        used += take
        price = rows[i]["cost"]
    return dispatched, price, used


def tri(lo, mode, hi):
    return lo if hi - lo < 1e-12 else random.triangular(lo, hi, mode)


def win_prob(rows, quota, lumpy, sims, grid, seed=7):
    random.seed(seed)
    us_i = next(i for i, r in enumerate(rows) if r["us"])
    us = rows[us_i]
    wins = [0] * len(grid)
    cutoffs = []
    for _ in range(sims):
        comp = []
        for i, r in enumerate(rows):
            if i == us_i or random.random() > r["p"]:
                continue
            comp.append((tri(r["low"], r["cost"], r["high"]) + r["adj"], r["mw"], i))
        comp.sort()
        won = award(comp, quota, lumpy)
        cutoffs.append(max((b for b, _, k in comp if k in won), default=float("nan")))
        for g, bid in enumerate(grid):
            ev = bid + us["adj"]
            stack = sorted(comp + [(ev, us["mw"], us_i)], key=lambda t: (t[0], t[2] == us_i))
            if us_i in award(stack, quota, lumpy):
                wins[g] += 1
    return [w / sims for w in wins], sorted(c for c in cutoffs if c == c)


def pct(sorted_vals, q):
    if not sorted_vals:
        return float("nan")
    k = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--quota", type=float, action="append", required=True,
                    help="quota (pay-as-bid) or demand (marginal) in MW; repeat for scenarios")
    ap.add_argument("--pricing", choices=["pay-as-bid", "marginal"], default="pay-as-bid")
    ap.add_argument("--lumpy", choices=["stop", "skip"], default="stop")
    ap.add_argument("--sims", type=int, default=3000)
    ap.add_argument("--bid-grid", type=float, nargs=3, metavar=("LOW", "HIGH", "STEP"))
    ap.add_argument("--unit", default="sen/kWh")
    ap.add_argument("--title", default="Bid supply curve")
    ap.add_argument("--out", default="curve_out")
    a = ap.parse_args()

    rows = load(a.csv)
    os.makedirs(a.out, exist_ok=True)
    total = sum(r["mw"] for r in rows)
    U = a.unit
    md = [f"# {a.title}", "",
          f"Pricing rule: **{a.pricing}** · bids: {len(rows)} · capacity offered {total:,.0f} MW",
          ""]
    if a.pricing == "pay-as-bid":
        md.append(f"Lumpy-award rule: **{a.lumpy}** (assumption — confirm against the RFP's award clause).")
    md += ["", "## Stack (cheapest first, central estimates)", "",
           f"| # | Bidder | MW | Cum. MW | Cost ({U}) | Range | P(compliant) | Rank adj. |",
           "|---|---|---|---|---|---|---|---|"]
    cum = 0.0
    for k, r in enumerate(sorted(rows, key=lambda r: r["cost"] + r["adj"]), 1):
        cum += r["mw"]
        nm = f"**{r['name']} (us)**" if r["us"] else r["name"]
        md.append(f"| {k} | {nm} | {r['mw']:,.0f} | {cum:,.0f} | {r['cost']:.2f} | "
                  f"{r['low']:.2f}–{r['high']:.2f} | {r['p']:.2f} | {r['adj']:+.2f} |")

    scen = []
    md += ["", "## Scenarios", ""]
    for q in a.quota:
        if a.pricing == "pay-as-bid":
            won, cutoff, first_out, mw = pay_as_bid_det(rows, q, a.lumpy)
            scen.append((q, won, cutoff))
            ratio = total / q if q else float("nan")
            md.append(f"- **Quota {q:,.0f} MW** (oversubscription {ratio:.1f}×): awarded {mw:,.0f} MW to "
                      f"{len(won)} bids; cut-off {cutoff:.2f} {U}"
                      + (f"; first bid out at {first_out:.2f} {U}" if first_out is not None else "")
                      if cutoff is not None else f"- **Quota {q:,.0f} MW**: nothing awarded")
            us = [i for i, r in enumerate(rows) if r["us"]]
            if us and cutoff is not None:
                r = rows[us[0]]
                gap = cutoff - (r["cost"] + r["adj"])
                if us[0] in won:
                    md.append(f"  - Our bid at floor {r['cost']:.2f} {U}: **IN**; headroom to cut-off "
                              f"{gap:+.2f} {U}")
                else:
                    md.append(f"  - Our bid at floor {r['cost']:.2f} {U}: **OUT** — "
                              + (f"the cut-off sits {-gap:.2f} {U} below our floor"
                                 if gap < 0 else "priced inside the cut-off but the lot does not fit the "
                                 "remaining quota (lumpy award) — test a smaller lot")
                              + ". Levers: lower the floor (capex, yield, financing), resize the lot, or no-bid.")
        else:
            disp, price, used = marginal_det(rows, q)
            scen.append((q, set(disp), price))
            md.append(f"- **Demand {q:,.0f} MW**: clearing price {price:.2f} {U} (marginal unit sets it); "
                      f"dispatched {used:,.0f} MW")
            for i, r in enumerate(rows):
                if r["us"]:
                    m = price - r["cost"]
                    md.append(f"  - Our unit margin {m:+.2f} {U}" + ("" if i in disp else " (not dispatched)"))

    probs, grid = None, None
    us_rows = [r for r in rows if r["us"]]
    if a.pricing == "pay-as-bid" and us_rows:
        floor = us_rows[0]["cost"]
        if a.bid_grid:
            lo, hi, st = a.bid_grid
        else:
            lo = min(r["low"] for r in rows) * 0.95
            hi = max(r["high"] for r in rows) * 1.02
            st = (hi - lo) / 40
        grid = []
        x = lo
        while x <= hi + 1e-9:
            grid.append(round(x, 4))
            x += st
        q0 = a.quota[0]
        probs, cut = win_prob(rows, q0, a.lumpy, a.sims, grid)
        md += ["", f"## Win probability vs our bid (quota {q0:,.0f} MW, {a.sims:,} simulations)", "",
               f"Competitor cut-off without us: P10 {pct(cut, .1):.2f} · P50 {pct(cut, .5):.2f} · "
               f"P90 {pct(cut, .9):.2f} {U}", "",
               f"| Our bid ({U}) | P(win) | Margin over floor | P(win) × margin |", "|---|---|---|---|"]
        best, zeros = None, 0
        for b, p in zip(grid, probs):
            ev = p * (b - floor)
            if b >= floor and (best is None or ev > best[2]):
                best = (b, p, ev)
            if b >= floor - 1e-9 and zeros < 1:
                md.append(f"| {b:.2f} | {p:.0%} | {b - floor:+.2f} | {ev:.3f} |")
                zeros += p < 0.005
        md += ["", "The simulation can disagree with the central-case scenarios above: competitor ranges are "
               "usually skewed (cost overruns are likelier than savings) and some bids fail evaluation "
               "(p_compliant), both of which move the cut-off. Quote the simulation, not the central case, "
               "when advising a bid price."]
        if best:
            md += ["", f"Expected-margin-maximising bid ≈ **{best[0]:.2f} {U}** (P(win) {best[1]:.0%}). "
                   "This is the Friedman (1956) expected-value rule; it ignores the strategic value of "
                   "winning, bid cost and the winner's curse, so treat it as one input, not the answer. "
                   "Never bid below the floor: a tariff that wins but fails the lender's downside case is "
                   "not a win."]
    md += ["", "_Illustrative model. Competitor costs are estimates; since LSS5 the Energy Commission has "
           "not disclosed winning tariffs, so calibrate ranges to bottom-up LCOE builds, not to "
           "old clearing prices. Never obtain or exchange bid prices with competitors — bid rigging is "
           "prohibited under the Competition Act 2010._", ""]
    with open(os.path.join(a.out, "curve_summary.md"), "w") as fh:
        fh.write("\n".join(md))
    print("\n".join(md))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed -- markdown only")
        return

    fig, ax = plt.subplots(figsize=(11, 6.5))
    srt = sorted(range(len(rows)), key=lambda i: rows[i]["cost"] + (rows[i]["adj"] if a.pricing == "pay-as-bid" else 0))
    smallest = min(scen, key=lambda t: t[0])[1]
    largest = max(scen, key=lambda t: t[0])[1]
    lo_all = min(r["low"] for r in rows)
    hi_all = max(r["high"] for r in rows)
    span = hi_all - lo_all or 1.0
    y0 = lo_all - 0.35 * span
    x = 0.0
    for i in srt:
        r = rows[i]
        if i in smallest:
            col = "#2e7d32"
        elif i in largest:
            col = "#c99a06"
        else:
            col = "#c62828"
        ax.bar(x, r["cost"] - y0, bottom=y0, width=r["mw"], align="edge",
               color="#1f4e9c" if r["us"] else col, edgecolor="white", lw=1.2,
               hatch="//" if r["us"] else None)
        if r["high"] > r["low"]:
            ax.plot([x + r["mw"] / 2] * 2, [r["low"], r["high"]], color="#333", lw=1, alpha=0.6)
        ax.text(x + r["mw"] / 2, max(r["high"], r["cost"]) + 0.03 * span, r["name"], ha="center",
                va="bottom", fontsize=7, rotation=90, weight="bold" if r["us"] else None)
        x += r["mw"]
    for k, (q, won, level) in enumerate(sorted(scen, key=lambda t: t[0])):
        ax.axvline(q, color="black", lw=1.4)
        ax.text(q, y0 + 0.04 * span, f" {'quota' if a.pricing == 'pay-as-bid' else 'demand'} {q:,.0f} MW ",
                fontsize=8, rotation=90, va="bottom", ha="right", color="white", weight="bold")
        if level is not None:
            ax.axhline(level, color="#c62828", ls="--", lw=1)
            ax.annotate(f"{'cut-off' if a.pricing == 'pay-as-bid' else 'price'} @ {q:,.0f} MW: {level:.2f} {U}",
                        xy=(x, level), xytext=(x * 1.01, level + (k - (len(scen) - 1) / 2) * 0.09 * span),
                        fontsize=8, color="#c62828", va="center", annotation_clip=False)
    ax.set_xlim(0, x)
    ax.set_ylim(y0, hi_all + 0.75 * span)
    ax.set_xlabel("Cumulative capacity offered (MW)")
    ax.set_ylabel(f"Tariff needed at hurdle IRR ({U}) — axis does not start at zero")
    ax.set_title(a.title, weight="bold")
    fig.text(0.5, 0.01, "Green: in at every quota · Amber: in only at the larger quota · Red: out · "
             "Blue hatched: us · whiskers: estimate range · central estimates shown", ha="center",
             fontsize=8, color="#555")
    fig.tight_layout(rect=(0, 0.03, 0.84, 1))
    fig.savefig(os.path.join(a.out, "cost_curve.png"), dpi=150)

    if probs:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.plot(grid, [p * 100 for p in probs], color="#1f4e9c", lw=2)
        ax.axvline(us_rows[0]["cost"], color="#c62828", ls="--", lw=1)
        ax.text(us_rows[0]["cost"], 3, " our floor", color="#c62828", fontsize=8)
        ax.set_xlabel(f"Our bid ({U})")
        ax.set_ylabel("P(win) %")
        ax.set_ylim(0, 102)
        ax.set_title(f"Win probability at quota {a.quota[0]:,.0f} MW", weight="bold")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(a.out, "win_probability.png"), dpi=150)
    print(f"\nWrote outputs to {a.out}/")


if __name__ == "__main__":
    main()
