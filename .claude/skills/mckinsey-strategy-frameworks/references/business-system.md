# Business system — find the edge by doing one step differently

## What it is and where it comes from
Map every step from technology to after-sales service. At each step you make a choice, and
advantage comes from choices rivals don't make that all reinforce the same value proposition. The
concept comes from an internal McKinsey staff paper, Bales, Chatterjee, Gogel & Puri, "Competitive
cost analysis" (March 1980); Fred Gluck later presented it publicly. Porter (1985), *Competitive
Advantage*, cites it as a precursor of the value chain (McKinsey Quarterly, "Enduring Ideas: The
business system", 2009). The value chain adds support activities (HR,
procurement, infrastructure) and margin. Use the business system to find the move, and the value
chain to cost it in detail.

## Two business systems EcoEnergy works with

### A. The RE project's business system (client level)
| Step | Key choices | Benchmarks to collect | Skill for the input |
|---|---|---|---|
| Land & site | Own/lease/option; flat vs undulating vs floating; distance to substation | Land cost RM/acre/yr, slope class, grid distance (km) | `kml-terrain-screening`, `legal-land-realestate`, `pv-civil-geotechnical` |
| Scheme & permits | LSS / CRESS / SELCO / ATAP; licence path | Eligibility, timeline to approvals | `malaysia-re-schemes`, `legal-energy-regulatory` |
| Engineering & yield | Bifacial, tracker vs fixed, DC/AC ratio, BESS sizing | Specific yield kWh/kWp/yr, P50/P90, availability | `pv-lead-engineer` and disciplines |
| Procurement | Module origin (domestic preference in LSS6), inverter/BESS vendors | Capex RM/Wp or RM/MWac, BESS RM/kWh | `pv-electrical`, `pv-scada-bess` |
| Construction | EPC lump-sum vs multi-contract | LDs, schedule, EPC margin | `legal-commercial-contracts` |
| Financing | Conventional vs sukuk; gearing; tenor | Margin over benchmark, DSCR, gearing | `corporate-banker`, `sukuk-expert`, `fin-model-engineer` |
| O&M & offtake | O&M scope, PPA vs CRESS PPA, SMP exposure | O&M RM/kWp/yr, availability guarantee | `fin-model-engineer`, `legal-commercial-contracts` |

**Where the edge usually lives in LSS:** tariffs fell about 4x across LSS1–LSS5 while quotas grew
about 7x (EcoEnergy's own LSS1–LSS6 analysis, Aug 2026). Margin now lives in capex discipline,
yield and financing cost, not in the tariff. For each step ask the four questions: *How well do we
perform here? Is there a better way? How do competitors do it? Who has the lower cost here, us or
them?*

Malaysian examples of a step done differently (use as prompts, not templates):
- **Land:** floating PV on ex-mining ponds or reservoirs near load centres avoids agricultural-land
  conversion. LSS5+ ran a dedicated floating package (EcoEnergy's LSS1–LSS6 article). It needs
  bathymetry and mooring design (`pv-mechanical-mounting`).
- **Procurement:** domestic modules can carry an LSS6 evaluation preference that offsets a capex
  premium. Run it as a sensitivity, not a footnote.
- **Offtake:** CRESS firm supply carries a lower System Access Charge than non-firm. Firming with
  BESS turns an engineering cost into an offtake-price advantage (see the CRESS article for current
  rates).

### B. EcoEnergy's own business system (firm level)
| Step | EcoEnergy's choice | Typical rival choice |
|---|---|---|
| Origination | Insights articles + free 30-min scheme-fit consult with KML pre-screen | EPC offers "free" feasibility tied to an EPC contract; Big 4 sells via audit relationships |
| Screening | Fast, cheap desktop screen (terrain, geology, grid, scheme fit, red flags) | Rivals skip it and sell a full study |
| Feasibility | Bank-grade, integrated engineering + finance + regulatory | Single-discipline consultants; finance-only Big 4 |
| Transaction | Defends its numbers through lender DD | Hand-over at report issue |
| After-sales | Available to defend the study before the board, offtaker or financier; referrals | One-off |

**Why it is a system:** the cheap screen lowers the client's cost to start. Staged gates make a
"no" affordable. Affordable "no"s make the "yes" credible to lenders. Credible "yes"es earn
referrals from lenders. A rival copying one step (say, a free consult) gets nothing without the
others. **Test fit before adding any new offer:** does it strengthen every other step, or fight one?
For example, success fees or EPC-management fight independence.

Competitor cost per step is hard to see for private firms. Their filed financial statements
(revenue, profit, staff cost) can be bought from SSM (Companies Commission of Malaysia) e-Info
services. Use them for order-of-magnitude benchmarks only.

## Run it
1. Map the six-to-eight steps for you and your top rival, with cost per step where you can.
2. Circle the step where you could make a choice nobody else makes.
3. Test fit: does that choice strengthen every other step, or fight them?
4. Before an acquisition, partnership or consortium, overlay the other party's system on yours to
   find real synergies, and duplicated or conflicting steps.

## Where it misleads
- It assumes a linear chain. Platform and ecosystem plays (aggregators under CREAM, CRESS
  portfolios) create value across chains.
- It rewards differentiation at a step, but in a price-ranked auction (LSS) a differentiation that
  doesn't lower the levelised tariff or raise the evaluation score is worthless at the bid box.
- Cost-per-step data for rivals is usually estimated. State the basis and the range.
