#!/usr/bin/env python3
"""Weighted nine-box scorer: GE-McKinsey portfolio matrix and bid/no-bid matrix.

One engine, two modes:
  --mode ge   Industry attractiveness x business-unit strength (portfolio call:
              invest / selectivity / harvest-divest) for service lines, sectors,
              technologies or client segments.
  --mode bid  Opportunity attractiveness x ability to win (tender call: bid /
              bid-with-conditions / no-bid), with pass/fail gates that override
              the score (registration, eligibility, conflict of interest).

Input is a JSON file (see assets/ge_matrix_template.json and
assets/bid_no_bid_template.json). The script:
  1. validates weights (each axis sums to 1.00) and scores (1-5),
  2. computes weighted totals, bands (Low < 2.33 <= Medium <= 3.67 < High) and cell,
  3. lists every score that has no evidence string (scores must be backed by data),
  4. stress-tests the classification: shifts each factor weight +/-5 percentage
     points (renormalising the rest) and reports units whose cell flips -- the
     known weakness of weighted portfolio grids (Wind, Mahajan & Swire 1983),
  5. writes <out>/matrix_summary.md and, if matplotlib is present, <out>/matrix.png.

Usage:
  python weighted_matrix.py input.json --out outdir [--mode ge|bid]
"""
import argparse
import json
import os
import sys

LOW_HI = 1 + 4 / 3      # 2.333...
MED_HI = 1 + 8 / 3      # 3.666...
BANDS = ["Low", "Medium", "High"]

# (attractiveness band, strength band) -> (label, posture, colour)
GE_CELLS = {
    ("High", "Low"): ("Build selectively", "Invest only in segments where you can win", "amber"),
    ("High", "Medium"): ("Invest to build", "Challenge for leadership; fund capability gaps", "green"),
    ("High", "High"): ("Grow & protect", "Invest at full speed; defend position", "green"),
    ("Medium", "Low"): ("Limited expansion", "Low-risk moves only, or harvest", "red"),
    ("Medium", "Medium"): ("Selectivity", "Manage for earnings; fix the weakest strength factor first", "amber"),
    ("Medium", "High"): ("Build selectively", "Grow the profitable segments", "green"),
    ("Low", "Low"): ("Divest", "Exit, or stop offering, at best value", "red"),
    ("Low", "Medium"): ("Harvest", "Cut investment, maximise cash", "red"),
    ("Low", "High"): ("Protect & refocus", "Defend, milk for cash, refocus", "amber"),
}

BID_CELLS = {
    ("High", "Low"): ("Bid only if a gap can be closed", "Partner/teaming or a named fix before the bid decision gate", "amber"),
    ("High", "Medium"): ("Bid", "Pursue; resource the capture plan to lift ability to win", "green"),
    ("High", "High"): ("Must-win bid", "Commit the A-team and full proposal budget", "green"),
    ("Medium", "Low"): ("No-bid", "Decline politely; keep the relationship", "red"),
    ("Medium", "Medium"): ("Bid with conditions", "Bid only if named conditions are met by the decision gate", "amber"),
    ("Medium", "High"): ("Bid", "Efficient bid; reuse proven content", "green"),
    ("Low", "Low"): ("No-bid", "Decline", "red"),
    ("Low", "Medium"): ("No-bid", "Decline unless strategic (state why in writing)", "red"),
    ("Low", "High"): ("Bid only if strategic", "Cheap win possible but low value; check opportunity cost", "amber"),
}

COLOURS = {"green": "#2e7d32", "amber": "#c99a06", "red": "#c62828"}


def band(x):
    if x < LOW_HI - 1e-9:
        return "Low"
    if x > MED_HI + 1e-9:
        return "High"
    return "Medium"


def weighted(factors, scores):
    return sum(f["weight"] * float(scores[f["name"]]) for f in factors)


def validate(data, errors, warnings):
    axes = data.get("axes", {})
    for ax in ("attractiveness", "strength"):
        if ax not in axes:
            errors.append(f"axes.{ax} missing")
            continue
        fs = axes[ax].get("factors", [])
        if not fs:
            errors.append(f"axes.{ax}.factors is empty")
            continue
        total = sum(f.get("weight", 0) for f in fs)
        if abs(total - 1.0) > 0.005:
            errors.append(f"axes.{ax} weights sum to {total:.3f}, must be 1.00 -- agree weights before scoring")
        if not 3 <= len(fs) <= 7:
            warnings.append(f"axes.{ax} has {len(fs)} factors; 4-6 that truly drive value is the norm")
    for u in data.get("units", []):
        missing, n = [], 0
        for ax in ("attractiveness", "strength"):
            sc = u.get("scores", {}).get(ax, {})
            for f in axes.get(ax, {}).get("factors", []):
                if f["name"] not in sc:
                    errors.append(f"{u['name']}: no {ax} score for '{f['name']}'")
                    continue
                n += 1
                v = float(sc[f["name"]])
                if not 1 <= v <= 5:
                    errors.append(f"{u['name']}: {ax} '{f['name']}' = {v} outside 1-5")
                ev = u.get("evidence", {}).get(ax, {}).get(f["name"], "")
                if not str(ev).strip():
                    missing.append(f["name"])
        if missing:
            warnings.append(f"{u['name']}: {len(missing)} of {n} scores have no evidence "
                            f"({'; '.join(missing)})")


def stress(factors, scores, base_band, step=0.05):
    """Return list of (factor, direction, new_band) where the band flips."""
    flips = []
    for i, f in enumerate(factors):
        for d in (+step, -step):
            w = [g["weight"] for g in factors]
            new_wi = min(max(w[i] + d, 0.0), 1.0)
            rest = sum(w) - w[i]
            if rest <= 0:
                continue
            scale = (1.0 - new_wi) / rest
            w2 = [new_wi if j == i else w[j] * scale for j in range(len(w))]
            val = sum(w2[j] * float(scores[factors[j]["name"]]) for j in range(len(w)))
            b = band(val)
            if b != base_band:
                flips.append((f["name"], f"{'+' if d > 0 else '-'}{int(step * 100)}pp", b, val))
    return flips


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--out", default="matrix_out")
    ap.add_argument("--mode", choices=["ge", "bid"], help="overrides 'mode' in the JSON")
    args = ap.parse_args()

    with open(args.input) as fh:
        data = json.load(fh)
    mode = args.mode or data.get("mode", "ge")
    cells = BID_CELLS if mode == "bid" else GE_CELLS
    y_name = "Opportunity attractiveness" if mode == "bid" else "Industry / market attractiveness"
    x_name = "Ability to win" if mode == "bid" else "Business-unit strength"

    errors, warnings = [], []
    validate(data, errors, warnings)
    if errors:
        print("INPUT ERRORS -- fix before scoring:", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
        sys.exit(2)

    fa = data["axes"]["attractiveness"]["factors"]
    fs = data["axes"]["strength"]["factors"]
    rows = []
    for u in data["units"]:
        a = weighted(fa, u["scores"]["attractiveness"])
        s = weighted(fs, u["scores"]["strength"])
        ab, sb = band(a), band(s)
        label, posture, colour = cells[(ab, sb)]
        gate_fail = [g["name"] for g in u.get("gates", []) if not g.get("pass", False)]
        if mode == "bid" and gate_fail:
            label, posture, colour = "NO-BID (gate failed)", "Failed: " + "; ".join(gate_fail), "red"
        flips = [("attractiveness",) + f for f in stress(fa, u["scores"]["attractiveness"], ab)]
        flips += [("strength",) + f for f in stress(fs, u["scores"]["strength"], sb)]
        rows.append(dict(name=u["name"], a=a, s=s, ab=ab, sb=sb, label=label, posture=posture,
                         colour=colour, size=float(u.get("size", 1.0)), traj=u.get("trajectory"),
                         flips=flips, gates=u.get("gates", []), notes=u.get("notes", "")))

    os.makedirs(args.out, exist_ok=True)
    md = [f"# {data.get('title', 'Weighted matrix')}", ""]
    md.append(f"Mode: **{'Bid / no-bid' if mode == 'bid' else 'GE-McKinsey portfolio'}** · "
              f"bands: Low < 2.33 ≤ Medium ≤ 3.67 < High (1-5 scale)")
    if data.get("size_label"):
        md.append(f"Bubble size = {data['size_label']}")
    md += ["", "## Weights (agreed before scoring)", ""]
    for ax, fl in (("Attractiveness", fa), ("Strength / ability to win", fs)):
        md.append(f"- **{ax}:** " + ", ".join(f"{f['name']} {f['weight'] * 100:.0f}%" for f in fl))
    md += ["", "## Results", "",
           f"| Unit | {'Opportunity attractiveness' if mode == 'bid' else 'Attractiveness'} | {x_name} | Cell | Call | Robust to ±5pp weights? |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        robust = "yes" if not r["flips"] else f"**no** ({len(r['flips'])} flips)"
        md.append(f"| {r['name']} | {r['a']:.2f} ({r['ab']}) | {r['s']:.2f} ({r['sb']}) | "
                  f"{r['ab']}/{r['sb']} | {r['label']} — {r['posture']} | {robust} |")
    if mode == "bid":
        md += ["", "## Gates (pass/fail — override the score)", ""]
        for r in rows:
            for g in r["gates"]:
                md.append(f"- {r['name']} · {g['name']}: {'PASS' if g.get('pass') else '**FAIL**'}"
                          + (f" — {g['basis']}" if g.get("basis") else ""))
    fragile = [r for r in rows if r["flips"]]
    if fragile:
        md += ["", "## Fragile classifications", "",
               "These calls change if a single weight moves by 5 percentage points. Treat the cell as "
               "a range, not a verdict, and get better evidence on the factor named before committing money.", ""]
        for r in fragile:
            for ax, fac, d, nb, val in r["flips"]:
                md.append(f"- {r['name']}: {ax} '{fac}' {d} → {nb} ({val:.2f})")
    if warnings:
        md += ["", "## Unevidenced scores / warnings", ""] + [f"- {w}" for w in warnings]
    md += ["", "_Screening tool. A weighted grid organises judgement; it does not replace the "
           "evidence behind each score or the decision-maker's accountability._", ""]
    with open(os.path.join(args.out, "matrix_summary.md"), "w") as fh:
        fh.write("\n".join(md))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except ImportError:
        print("matplotlib not installed -- wrote markdown only (pip install matplotlib)")
        print("\n".join(md))
        return

    fig, ax = plt.subplots(figsize=(9, 8))
    edges = [1, LOW_HI, MED_HI, 5]
    for (ab, sb), (label, _, col) in cells.items():
        xi, yi = BANDS.index(sb), BANDS.index(ab)
        ax.add_patch(Rectangle((edges[xi], edges[yi]), edges[xi + 1] - edges[xi], edges[yi + 1] - edges[yi],
                               facecolor=COLOURS[col], alpha=0.13, edgecolor="#888", lw=0.8))
        ax.text(edges[xi] + 0.05, edges[yi] + 0.07, label, fontsize=8, color=COLOURS[col], weight="bold")
    smax = max(r["size"] for r in rows) or 1.0
    for r in rows:
        area = 250 + 1800 * (r["size"] / smax)
        ax.scatter(r["s"], r["a"], s=area, color=COLOURS[r["colour"]], alpha=0.75,
                   edgecolor="white", lw=1.5, zorder=3)
        ax.annotate(r["name"], (r["s"], r["a"]), xytext=(0, -16 - area ** 0.5 / 3),
                    textcoords="offset points", ha="center", fontsize=8, zorder=4)
        if r["traj"]:
            dx, dy = r["traj"]
            ax.annotate("", xy=(r["s"] + dx, r["a"] + dy), xytext=(r["s"], r["a"]),
                        arrowprops=dict(arrowstyle="->", color="#333", lw=1.3), zorder=4)
    ax.set_xlim(1, 5)
    ax.set_ylim(1, 5)
    ax.set_xlabel(f"{x_name} (weighted score, 1-5)")
    ax.set_ylabel(f"{y_name} (weighted score, 1-5)")
    ax.set_title(data.get("title", "Weighted matrix"), fontsize=12, weight="bold")
    note = "Bubble size = " + data.get("size_label", "relative size") + " · arrow = expected trajectory"
    fig.text(0.5, 0.01, note, ha="center", fontsize=8, color="#555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(os.path.join(args.out, "matrix.png"), dpi=150)
    print("\n".join(md))
    print(f"\nWrote {args.out}/matrix_summary.md and {args.out}/matrix.png")


if __name__ == "__main__":
    main()
