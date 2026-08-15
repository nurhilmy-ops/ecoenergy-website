# BESS Installation in Malaysia — EPCC Knowledge Base

Working reference for EcoEnergy BESS engagements. Baseline design used throughout:
**100 MW / 400 MWh (4-hour) LFP containerised BESS, 33 kV collection, grid-connected via TNB PMU (Peninsular) or SESB (Sabah)** — the MyBEST-scale block. All quantities and costs scale approximately linearly for 25–200 MW blocks; costs are indicative Q3-2026 estimates and must be validated against live vendor quotes and the project's Connection Offer.

| # | Document | Scope item |
|---|----------|-----------|
| 1 | [01-components.md](01-components.md) | Required BESS infrastructure components, detail of each component and cabling |
| 2 | [02-civil-works.md](02-civil-works.md) | Civil works; structural/foundation selection driven by JMG report or SI data |
| 3 | [03-epcc-cost.md](03-epcc-cost.md) | EPCC cost for installation and construction of a BESS facility in Malaysia |
| 4 | [04-cost-breakdown.md](04-cost-breakdown.md) | Cost components and work components breaking down the EPCC price |
| 5 | [05-bq-bess.md](05-bq-bess.md) | Detailed Bill of Quantities (BQ), bills 1–8 |
| 6–9 | [06-interconnection-framework.md](06-interconnection-framework.md) | PMU interconnection / LILO framework, TNB & SESB equipment specs, interconnection BQ and EPCC costing basis |

## LILO skill

Items 6–9 are also packaged as a callable project skill:
`.claude/skills/lilo-interconnection/` — invoke **`/lilo-interconnection`** in any session
once the PMU location, voltage level and route data are known. It produces a tailored
interconnection mechanism, equipment list to TNB/SESB specs, interconnection BQ
(including civil works and substation building) and the EPCC costing basis.

## Key references

- TNB Electricity Supply Application Handbook (ESAH) v3.1, 2022
- TNB Handbook of Bulk Supply Interconnection, 2019
- TNB Substation Design Manual
- Malaysian Grid Code / Distribution Code; Energy Commission MyBEST RFP documents
- SESB Transmission & Distribution planning guidelines (Sabah projects)
- MS IEC 61439, MS IEC 62271, IEC 62933 (EES systems), NFPA 855 / UL 9540A (fire safety)
- JKR Standard Specifications (civil), JPS MSMA 2nd Ed. (drainage), CIDB SMM2 (BQ measurement)
