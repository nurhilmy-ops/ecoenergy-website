# Industry cost curve → bid supply curve — what tariff wins, who survives a downturn

## What it is and where it comes from
Sort all producers from cheapest to most expensive cash cost per unit, with bar width = capacity.
Overlay demand; in a commodity market the **price is set by the last producer needed to meet
demand**, and each producer's margin is price minus its own cost. It is a long-standing
McKinsey/commodity-economics tool, built for undifferentiated products (metals, chemicals,
bulk power). The infographic's example (demand falls 21% from 70M to 55M units; price falls 28%
from $50 to $36) is arithmetically correct and illustrative.

## Three uses at EcoEnergy — know which rule applies
| Use | Pricing rule | What the curve predicts |
|---|---|---|
| **LSS and other quota auctions** (client bids) | **Pay-as-bid**: each winner is paid its own bid; capacity is awarded cheapest-first up to the quota (confirm in each RFP) | The **cut-off tariff** and your **probability of winning** at each bid price, not a single market price |
| **SMP / merit order** (CRESS excess energy, merchant tails) | **Uniform/marginal**: the most expensive dispatched unit sets the half-hourly price | How much solar depresses midday SMP; what surplus energy is worth |
| **EcoEnergy's own fees** | Not a commodity | Mostly **not applicable**. Use only for price-ranked consultancy tenders, as a fee-benchmark stack |

### 1. LSS bid supply curve (pay-as-bid)
- **x-axis:** MW offered by each expected bidder (LSS6 Pakej 1 bids 60–500 MW per bidder).
- **y-axis:** the tariff each bidder needs at its hurdle IRR (sen/kWh, levelised as the RFP
  defines it). For your own bid this is the **floor** from `fin-model-engineer`. It is never a
  number you pick.
- **Demand line:** the package quota (e.g. LSS6 Pakej 1: 2,200 MW solar + 1,100 MW BESS).
  Oversubscription has fallen from about 13× (LSS3: 6.73 GW offered for 500 MW) to about 2×
  (LSS5+: 1,975 MW awarded from 4,073 MW bid) as lots grew and qualification tightened. Plan for
  roughly half of well-prepared bidders to lose.
- **Lumpiness:** projects are awarded whole. A cheap bid can still miss the quota if its lot doesn't
  fit. Lot size is a strategic lever; test a smaller lot (`--lumpy stop|skip`, and rerun with a
  resized row). LSS4 awarded 823 MW against a 1,000 MW quota, so the quota isn't always filled.
- **Calibration problem:** since LSS5, the Energy Commission has not disclosed winning tariffs.
  Old results (LSS3 lowest 17.777 sen/kWh; LSS4 winners 18.50–24.81 sen in Pakej 1 and 17.68–19.70
  sen in Pakej 2) are solar-only and pre-BESS, so they are not comparable with a solar+BESS hybrid
  bid (LSS6 Pakej 1–2 BESS is 1,250 MW / 6,000 MWh, about 4.8 hours). Build competitor costs
  **bottom-up by archetype** instead:

| Archetype | Typical cost-curve position (hypothesis to test) | Main drivers |
|---|---|---|
| Utility subsidiaries / GLC-backed developers | Left (cheapest) | Low cost of capital, land banks, grid knowledge |
| Listed EPC-developers | Left-centre | In-house EPC margin, procurement scale, track record |
| Foreign IPP + local partner | Centre | Cheap equity but higher return hurdle; must meet Malaysian equity rules |
| Mid-cap / regional developers | Centre-right | Higher debt margins, smaller lots |
| Landowner-developers, new entrants | Right | Land is cheap but cost of capital and execution risk high; lower compliance probability |

For each archetype estimate: capex (solar RM/MWac + BESS RM/kWh at the RFP's ratio), specific yield
for its likely region (the LSS6 steer is to the southern Peninsula), O&M, degradation and
augmentation, land and grid-connection cost, gearing and cost of debt, and hurdle equity IRR. Get
engineering inputs from `pv-lead-engineer`/`pv-scada-bess` and the client's real floor from
`fin-model-engineer`. Give each archetype a low/central/high range and each bid a probability of
passing evaluation (`p_compliant`).

**Price everyone on one engine, anchored to a known number.** `scripts/archetype_tariff.py` solves
each archetype's tariff at its hurdle IRR on the same simplified project-finance model, with sculpted
debt capped at max gearing, capital allowances and optional GITA. It then scales the whole set so
the client's archetype reproduces the client's real floor. Absolute LCOE models disagree by several
sen, but relative positions on one engine are far more robust. If the calibration factor is far from
1, the common inputs don't describe the client's model; fix them rather than trusting the scaling.
Tax and GITA settings are placeholders until `solar-accountant` confirms them.

```bash
python scripts/archetype_tariff.py archetypes.json --out out/lss6     # writes out/lss6/bids.csv
python scripts/bid_supply_curve.py out/lss6/bids.csv --quota 2200 --quota 1650 \
       --title "LSS6 Pakej 1 — central vs stress" --out out/lss6
```

Outputs: the stack, cut-off per scenario, whether your floor is in, P10/P50/P90 competitor cut-off
from Monte Carlo, and a P(win) curve against your bid price.

**Choosing the bid:** the script reports the bid that maximises P(win) × margin over floor. That is
the classic expected-value rule from Friedman (1956), "A competitive-bidding strategy", *Operations
Research* 4(1). Treat it as one input:
- **Winner's curse.** In common-value auctions, the winner tends to be the bidder who most
  under-estimated cost (Capen, Clapp & Campbell, 1971, *Journal of Petroleum Technology*). LSS3 is
  the local lesson: some winners struggled to finance at their own numbers.
- **Never bid below the floor** that survives the lender's downside case (`corporate-banker`). A
  tariff that wins but can't reach financial close is an option premium paid to discover the project
  is unbankable.
- **Evaluation rules can re-rank bids.** Domestic-module preferences and Bumiputera packages change
  the order. Model them in the `adj` column only as the RFP defines them.

### 2. SMP merit order (uniform price)
Use `--pricing marginal` with generator classes (solar, gas CCGT, coal, OCGT) and their marginal
costs to show why midday SMP softens as solar grows. This is the merit-order effect documented for
Germany by Sensfuß, Ragwitz & Genoese (2008), *Energy Policy* 36(8). For CRESS deals this is the
basis of the rule in EcoEnergy's CRESS article: value excess energy at zero in the base case and
SMP upside as a sensitivity only.

### 3. EcoEnergy's own fees
Consultancy is differentiated and usually scored on quality and price, so a cost curve of rivals'
fees misleads more than it informs. Use the tender's own scoring formula instead
(`tender-playbook.md`, price-to-win arithmetic).

## The five strategy questions, localised
1. *Where will the cut-off settle if the quota shrinks or more bidders enter?* Rerun with a smaller
   quota or added rows.
2. *Who drops out first?* Bids on the far right, and those with low `p_compliant` (weak land
   control, no financing letter).
3. *Should the client add capacity (a bigger lot)?* A bigger lot can push itself out under the
   lumpy-award rule.
4. *Which projects are worth buying?* Post-award, left-side winners with financing difficulty are
   M&A targets. Right-side winners are cheap for a reason.
5. *How much cost must we cut?* Enough to move left of the P50 cut-off in the stress scenario.
   Translate into capex RM/MWac and yield targets for the engineers.

## Where it misleads
- Competitor costs are **estimates**; publish ranges, not points.
- Bids are not costs. Strategic bidders may bid below cost to win a reference; under-capitalised
  ones may bid above cost to protect returns. Widen ranges for those archetypes.
- Pay-as-bid award mechanics vary by RFP (lot sizes, ties, partial awards, regional caps). Confirm
  them in the tender documents and set `--lumpy` accordingly.
- **Never obtain, exchange or coordinate bid prices with competitors.** That is bid rigging, a
  prohibited agreement under the Competition Act 2010; see `malaysia-context.md`. Build the curve
  only from public information, your own data and engineering estimates.
