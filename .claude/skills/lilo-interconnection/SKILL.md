---
name: lilo-interconnection
description: Design a tailored BESS grid-interconnection mechanism for Malaysia (TNB/SESB) once the PMU location or candidate 132kV line is identified — LILO vs direct-bay vs 33kV tie selection, equipment list per TNB/SESB specs, interconnection BQ including civil works and substation building, and the EPCC costing basis. Use when the user provides a PMU location, connection offer, line route, or asks for interconnection design/costing for a BESS or power plant project.
---

# LILO / PMU Interconnection Skill (Malaysia BESS)

You are producing a tailored interconnection package for a BESS (or generation) project
connecting to the TNB grid (Peninsular) or SESB grid (Sabah). The knowledge base is
`docs/bess/06-interconnection-framework.md` in this repo — **read it first**, plus
`docs/bess/02-civil-works.md` (foundation logic) and `docs/bess/05-bq-bess.md` (BQ format).

## Step 1 — Collect inputs (ask only for what's missing)

| Input | Why |
|---|---|
| PMU/PPU location or nearest 132 kV line route, and straight-line + routable distance from BESS site | Option selection & cable/OHL quantities |
| BESS MW / MWh and delivery voltage | Sizes transformers, number of circuits |
| Connection Offer / TNB power system study (if issued) | Demarcation, fault level, required N-1, works charges |
| Spare bay availability at the PMU (TNB confirmation) | Direct-bay vs LILO |
| Terrain/land status along route; built-up areas | OHL vs UGC choice, wayleave risk |
| JMG/SI data at substation site | Foundation type for GIS hall, trafo plinths, tower footings |
| Grid operator: TNB or SESB | Spec family, rates uplift, approval chain |

## Step 2 — Select the mechanism

Apply the decision table in doc 06 §6.1 (Options A/B/C/D). State the selected option,
the rejected ones and why. If inputs are incomplete, present the two closest options
with a cost delta rather than stalling.

## Step 3 — Equipment list to TNB/SESB specs

Produce the full equipment schedule from doc 06 §6.2 for the selected option, sized to
the project (bays, CB ratings ≥ fault level from the study, transformer MVA with
ONAN/ONAF stages, conductor/cable cross-sections checked against ampacity for the
export MW, protection scheme, metering per MSSC, OPGW/teleprotection). Flag every item
that must come from a TNB/SESB approved-vendor list.

## Step 4 — Interconnection BQ

Build a measured BQ using the bill structure I-1…I-11 in doc 06 §6.4, including:
- civil works: platform, GIS/control building (m² measured), trafo plinths & bunds,
  tower foundations (per-tower, foundation type from SI), trenches/ducts, earthing,
  fencing, access road, drainage;
- substation building works measured separately from electrical plant;
- TNB works charges as a provisional sum from the Connection Offer.
Use the indicative rates in doc 06 as defaults; escalate/deflate to the current quarter
and state the basis. Apply +10–20 % construction uplift for SESB/Sabah.

## Step 5 — EPCC costing basis

Close with the costing-basis statement (doc 06 §6.5): demarcation, exclusions
(wayleave, land, outage idle-time risk), FX assumptions, programme (GIS & trafo lead
times, TNB approval cycles, outage windows for LILO cutover), and a ±accuracy class
(state whether the estimate is AACE Class 5/4/3 based on input maturity).

## Output format

One markdown deliverable (or docx/xlsx if the user asks): mechanism selection →
single-line description → equipment schedule → BQ tables with totals → costing basis
& exclusions → open items needed to firm up the estimate.
