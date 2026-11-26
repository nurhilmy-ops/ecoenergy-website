# GE-McKinsey nine-box matrix — where to invest, hold or exit

## What it is and where it comes from
Plot each business unit by **industry attractiveness** (is this a good market to be in?) and
**business-unit strength** (can we win in it?), each a weighted bundle of factors scored 1–5.
Green cells: invest. Yellow: selective. Red: harvest or exit. It was developed by McKinsey with
General Electric in the early 1970s as a richer alternative to the BCG growth-share matrix, which
uses only two single factors. The bands are Low < 2.33 ≤ Medium ≤ 3.67 < High, which splits the 1–5
range into thirds.

**The same machinery drives the bid/no-bid matrix** (opportunity attractiveness × ability to win);
see `tender-playbook.md`. `scripts/weighted_matrix.py` runs both.

## When to use it
- **Firm level:** annual allocation of partner time, hiring and marketing across service lines ×
  client segments × technologies (solar, BESS, hydro, WtE).
- **Client level:** a developer ranking its candidate sites or schemes. Attractiveness = scheme
  economics and policy visibility; strength = site quality, grid access, land control, sponsor
  balance sheet.

## Factor library (pick 4–6 per axis that truly drive value; agree weights before scoring)
**Firm-level attractiveness:** market growth (MW pipeline per year in the scheme), fee margin
achievable, policy visibility (published quotas, rules, dates), competitive intensity, client ability
to pay and payment risk, regulatory/disruption risk.

**Firm-level strength:** track record and references (count them), team capability (BEM-registered
PE, modellers, regulatory and legal access), credibility with lenders (independence), relationships
and channels, cost to serve.

**Client site-portfolio attractiveness:** scheme tariff vs required IRR, quota or market depth,
policy visibility, offtaker credit (for CRESS), curtailment and SMP exposure.
**Client site-portfolio strength:** specific yield, slope class and earthworks, grid distance and
capacity, land tenure and conversion risk, sponsor equity capacity.

## Evidence sources (score with data, not opinion)
| Factor | Source |
|---|---|
| Market growth, policy visibility | ST/PETRA RFP announcements, SEDA quotas, NETR targets: `malaysia-context.md` |
| Fee margin by service line | Ledger via `eco-bookkeeper-agent` (revenue and direct cost by job) |
| Win rate / track record | Quotation → work-order conversion via `eco-sales-documents-agent` |
| Competitive intensity | Count of credible rivals seen in the last 12 months of bids; SSM filings for private rivals |
| Site strength | `kml-terrain-screening`, `pv-lead-engineer`, `legal-land-realestate` |

## Method (5 steps)
1. Pick 4–6 factors per axis.
2. Agree the weights (summing to 100%) **before** anyone scores. This stops weights being tuned to
   reach a wanted answer.
3. Score each factor 1–5 with written evidence. The script flags unevidenced scores.
4. Multiply and add, then place each unit in its cell. Bubble size = revenue (or fee value); the
   arrow shows where the unit is heading.
5. Read the robustness table. If a cell flips when one weight moves ±5 pp, report it as fragile and
   get better evidence on that factor before committing money.

```bash
python scripts/weighted_matrix.py assets/ge_matrix_template.json --out out/ge --mode ge
```

## Worked example (from the template; illustrative scores)
CRESS structuring scores 4.05 attractiveness / 3.30 strength → *Invest to build*: fund the
capability gap (relationships and channels with corporate offtakers) before adding marketing spend.
LSS feasibility scores 3.40 / 3.45 → *Selectivity*: manage for earnings and fix the weakest
strength factor. The point is the method; the template's numbers are not a view on the market.

## Where it misleads
- **Subjectivity.** Wind, Mahajan & Swire (1983, *Journal of Marketing* 47(2)) applied several
  standard portfolio models to 15 business units of one firm (PIMS data) and found the same units
  landed in different cells depending on the model, the measures, the cut-off lines and the weights. Hence agreed weights, evidence per score and the
  robustness test.
- **Static snapshot.** Re-score annually and after policy events; draw trajectories.
- **Units are not independent.** A "harvest" unit may feed a "grow" one. For example, low-margin
  SELCO/ATAP work with factories can be the origination channel for CRESS mandates with the same
  owners. Check cross-unit flows before exiting anything.
- **The grid is not a strategy.** It says where to put resources, not how to win there. Follow with
  the business system or a decision-journey analysis.
