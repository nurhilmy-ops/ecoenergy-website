#!/usr/bin/env python3
"""Screening-grade tariff-at-hurdle-IRR engine for competitor archetypes (solar or solar+BESS).

Why: since LSS5 the Energy Commission has not disclosed winning tariffs, so a bid supply curve has
to be built bottom-up. Absolute LCOE models disagree by several sen; RELATIVE positions are far more
robust. This engine prices every archetype on the same simplified project-finance model and
calibrates the whole set so one anchor archetype (usually our client, whose real financial-model
floor is known) reproduces its known tariff. Competitors are then expressed relative to that anchor.

It is a screening tool, not the client's financial model. The floor itself always comes from the
full model (fin-model-engineer); tax settings (capital allowances, GITA) must be confirmed with
solar-accountant before any number leaves the building.

Model, per MWac, annual, nominal:
  capex t0 = solar RM/MWac + BESS (ratio x hours x RM/kWh); revenue = flat tariff x energy at POI
  energy = yield x yield_factor x (1 - bess_loss) x (1 - deg)^(t-1)
  opex = (fixed O&M + BESS O&M % + insurance % + land) escalated; augmentation capex in listed years
  tax on (EBITDA - interest - capital allowances), losses carried forward, optional GITA offset
  debt sculpted to target DSCR over its tenor, capped at max gearing
  tariff solved so post-tax equity IRR = hurdle

Input JSON (see assets/archetypes_template.json):
  common      default parameters (any key below)
  archetypes  {name: {overrides...}, ...}
  anchor      {"archetype": name, "tariff": 23.8}           optional calibration
  ranges      {"low": {overrides}, "high": {overrides}}     shocks for low/high tariffs
  field       [{"name","archetype","mw","yield_factor","p_compliant","us"}]  optional bid list

Usage:
  python archetype_tariff.py input.json --out outdir
Writes outdir/archetype_tariffs.csv and, if a field is given, outdir/bids.csv ready for
bid_supply_curve.py.
"""
import argparse
import csv
import json
import os

DEFAULTS = dict(
    solar_rm_per_mwac=2.2e6, bess_ratio=0.0, bess_hours=0.0, bess_rm_per_kwh=550.0,
    yield_kwh_per_kwac=1500.0, yield_factor=1.0, deg=0.005, bess_loss=0.0,
    om_fixed_rm_per_mwac=28000.0, om_bess_pct=0.012, insurance_pct=0.0035, land_rm_per_mwac=10000.0,
    escalation=0.025, aug_years=[], aug_pct_of_bess=0.15,
    years=21, debt_tenor=18, debt_rate=0.055, max_gearing=0.75, dscr=1.30, hurdle_irr=0.09,
    tax_rate=0.24, ca_schedule=[0.34, 0.14, 0.14, 0.14, 0.14, 0.10], qualifying_share=0.90,
    gita_pct=0.0, gita_cap_of_si=0.70,
)


def irr(cfs, lo=-0.9, hi=1.0):
    f = lambda r: sum(c / (1 + r) ** t for t, c in enumerate(cfs))
    if f(lo) * f(hi) > 0:
        return float("nan")
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if f(lo) * f(mid) <= 0 else (mid, hi)
    return (lo + hi) / 2


def project(tariff_sen, p):
    n = int(p["years"])
    cap_b = p["bess_ratio"] * p["bess_hours"] * 1000 * p["bess_rm_per_kwh"]
    capex = p["solar_rm_per_mwac"] + cap_b
    yrs = range(1, n + 1)
    energy = [p["yield_kwh_per_kwac"] * 1000 * p["yield_factor"] * (1 - p["bess_loss"])
              * (1 - p["deg"]) ** (t - 1) / 1000 for t in yrs]                     # MWh per MWac
    rev = [tariff_sen * 10 * e for e in energy]                                     # sen/kWh -> RM/MWh
    opex = [(p["om_fixed_rm_per_mwac"] + p["om_bess_pct"] * cap_b + p["insurance_pct"] * capex
             + p["land_rm_per_mwac"]) * (1 + p["escalation"]) ** (t - 1) for t in yrs]
    aug = [p["aug_pct_of_bess"] * cap_b if t in p["aug_years"] else 0.0 for t in yrs]
    ebitda = [r - o for r, o in zip(rev, opex)]
    q = p["qualifying_share"] * capex
    interest, ds, debt = [0.0] * n, [0.0] * n, 0.0
    for _ in range(6):                      # tax <-> interest circularity
        tax, loss_cf, gita_cf = [], 0.0, p["gita_pct"] * q
        for i in range(n):
            ca = (p["ca_schedule"][i] * q if i < len(p["ca_schedule"]) else 0.0) + aug[i]
            si = ebitda[i] - interest[i] - ca - loss_cf
            loss_cf, si = (-si, 0.0) if si < 0 else (0.0, si)
            use = min(gita_cf, p["gita_cap_of_si"] * si)
            gita_cf -= use
            tax.append(p["tax_rate"] * (si - use))
        cfads = [e - a - t for e, a, t in zip(ebitda, aug, tax)]
        tenor = int(p["debt_tenor"])
        sculpt = [max(cfads[i], 0) / p["dscr"] if i < tenor else 0.0 for i in range(n)]
        pv = sum(s / (1 + p["debt_rate"]) ** (i + 1) for i, s in enumerate(sculpt))
        debt = min(p["max_gearing"] * capex, pv)
        ds = [s * (debt / pv if pv > 0 else 0.0) for s in sculpt]
        bal, interest = debt, []
        for i in range(n):
            it = bal * p["debt_rate"]
            interest.append(it)
            bal = max(bal - (ds[i] - it), 0.0)
    eq = [-(capex - debt)] + [c - d for c, d in zip(cfads, ds)]
    return eq, debt / capex, capex


def solve(p):
    """Tariff at which equity NPV at the hurdle rate is zero (i.e. equity IRR = hurdle).
    Solving on the NPV sign is monotonic in tariff and avoids IRR's undefined cases."""
    npv = lambda t: sum(c / (1 + p["hurdle_irr"]) ** i for i, c in enumerate(project(t, p)[0]))
    lo, hi = 0.5, 200.0
    if npv(hi) < 0:
        raise SystemExit("No tariff below 200 sen/kWh reaches the hurdle -- check the inputs")
    for _ in range(70):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if npv(mid) < 0 else (lo, mid)
    return (lo + hi) / 2


def params(common, over, shock=None):
    p = dict(DEFAULTS)
    p.update(common or {})
    p.update(over or {})
    for k, v in (shock or {}).items():
        if k.endswith("_add"):
            p[k[:-4]] += v
        elif k.endswith("_mult"):
            p[k[:-5]] *= v
        else:
            p[k] = v
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--out", default="tariff_out")
    a = ap.parse_args()
    cfg = json.load(open(a.input))
    common, arch = cfg.get("common", {}), cfg["archetypes"]
    rng = cfg.get("ranges", {})

    raw = {n: solve(params(common, o)) for n, o in arch.items()}
    k = 1.0
    anc = cfg.get("anchor")
    if anc:
        k = anc["tariff"] / raw[anc["archetype"]]
    rows = []
    for n, o in arch.items():
        lo = solve(params(common, o, rng.get("low"))) * k if rng.get("low") else raw[n] * k
        hi = solve(params(common, o, rng.get("high"))) * k if rng.get("high") else raw[n] * k
        eq, g, capex = project(raw[n], params(common, o))
        rows.append(dict(archetype=n, raw=raw[n], central=raw[n] * k, low=min(lo, hi), high=max(lo, hi),
                         gearing=g, capex_rm_m_per_mwac=capex / 1e6, equity_irr_check=irr(eq)))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "archetype_tariffs.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({kk: (round(v, 3) if isinstance(v, float) else v) for kk, v in r.items()})
    print(f"Calibration factor k = {k:.3f}" + (f" (anchor {anc['archetype']} = {anc['tariff']} sen/kWh)" if anc else " (uncalibrated)"))
    print(f"{'Archetype':40s} {'raw':>7s} {'central':>8s} {'low':>7s} {'high':>7s} {'gear':>5s} {'capex':>6s} {'IRR':>6s}")
    for r in sorted(rows, key=lambda r: r["central"]):
        print(f"{r['archetype'][:40]:40s} {r['raw']:7.2f} {r['central']:8.2f} {r['low']:7.2f} {r['high']:7.2f} "
              f"{r['gearing']:5.2f} {r['capex_rm_m_per_mwac']:6.2f} {r['equity_irr_check']:6.1%}")
    if raw and k and abs(k - 1) > 0.15:
        print(f"WARNING: calibration factor {k:.2f} is far from 1 -- the common inputs don't describe the "
              "anchor's model well; fix the inputs rather than trusting the scaled numbers.")

    field = cfg.get("field")
    if field:
        by = {r["archetype"]: r for r in rows}
        with open(os.path.join(a.out, "bids.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["name", "capacity_mw", "cost", "low", "high", "p_compliant", "adj", "us"])
            for b in field:
                base = by[b["archetype"]]
                yf = b.get("yield_factor", 1.0)
                # tariff scales ~inversely with energy; adjust for site yield relative to the archetype
                c, l, h = (base["central"] / yf, base["low"] / yf, base["high"] / yf)
                w.writerow([b["name"], b["mw"], round(c, 2), round(l, 2), round(h, 2),
                            b.get("p_compliant", 1.0), b.get("adj", 0.0), 1 if b.get("us") else ""])
        print(f"Wrote {a.out}/bids.csv for bid_supply_curve.py")


if __name__ == "__main__":
    main()
