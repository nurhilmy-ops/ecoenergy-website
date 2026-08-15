# 6–9. Grid Interconnection Framework — PMU / LILO (TNB & SESB)

This document is the knowledge base behind the **`/lilo-interconnection`** skill. Once the PMU location (or candidate line for LILO) is identified, the skill tailors: the interconnection mechanism, equipment list to TNB/SESB specs, the interconnection BQ (civil + substation building included), and the EPCC costing basis.

## 6.1 Connection options (TNB ESAH v3.1 / Bulk Supply Interconnection Handbook)

| Option | When it applies | Mechanism |
|---|---|---|
| **A. Direct bay at existing PMU** | BESS within ~2–5 km of a PMU (Pencawang Masuk Utama, 275/132 kV or 132/33 kV) with spare bay & busbar capacity | New 132 kV (or 33 kV) bay in the PMU + dedicated feeder cable/OHL from BESS substation |
| **B. LILO of existing 132 kV line** | No spare bay / PMU distant, but a 132 kV double-circuit OHL passes near site | Cut the line into a **new 132 kV switching station (SSU/PMU) at the BESS site**: 4 line bays (in/out ×2 circuits) + 2 transformer/feeder bays; existing line towers modified with LILO towers |
| **C. LILO at 275 kV** | Large multi-block BESS (≥300 MW) near 275 kV corridor | As B but 275 kV GIS + 275/33 kV or 275/132/33 kV transformation — significantly higher cost |
| **D. 33 kV / 11 kV distribution tie (PPU/SSU)** | Small BESS ≤ ~30 MW near a PPU with firm capacity | 33 kV feeder(s) into PPU switchboard; fastest & cheapest, capacity-limited |
| **Sabah (SESB)** | State grid 275/132/66/33 kV | Same topology logic; 66 kV appears as sub-transmission; SESB specs & approval chain (SESB planning + Energy Commission Sabah); logistics premium |

**Decision inputs required:** Connection Offer / Power System Study by TNB (fault levels, N-1), distance & ROW to PMU or line, spare-bay audit, soil data at substation site, OHL vs UGC constraints (built-up areas force underground).

## 6.2 Equipment requirements per option (TNB/SESB specification families)

### Option A — bay extension + feeder
- **132 kV bay equipment (TNB spec):** SF₆/vacuum 132 kV CB (40 kA, 3150 A), disconnectors + earth switches, CTs (multi-core, 0.2s metering core), CVTs, surge arresters (120 kV MCOV class), bay marshalling kiosk, busbar extension works inside PMU (by TNB or TNB-approved contractor).
- **Feeder:** 132 kV XLPE 1C Cu 800–1200 mm² UGC (typ. 2 circuits) or 132 kV DC OHL on lattice towers (ACSR Zebra/Batang or equivalent, OPGW 24/48C).
- **Protection:** line differential (dual, IEC 61850) + distance backup, teleprotection over OPGW/fibre, breaker-fail, AR (OHL only); settings coordinated & approved by TNB Protection unit.
- **Metering at delivery point:** main + check 0.2s, MSSC-compliant, sealed by TNB.

### Option B — 132 kV LILO switching station at BESS site
- **Switchgear:** 132 kV **GIS preferred by TNB for new stations** (compact, tropical reliability): 4 line bays + 2 trafo bays + bus section ≈ 7-bay GIS hall; AIS possible on cheap land.
- **Power transformers:** 2 × 132/33 kV 60/90 MVA YNd1 c/w OLTC, NER 33 kV side.
- **Line works:** 2 LILO tension towers + slack-span or short DC line into the station gantries; tower modifications, sag/tension re-profiling, outage-managed cutover (TNB live-line planning); OPGW splice to existing line comms.
- **Station auxiliaries:** 110 Vdc, LVAC + aux trafo, SCADA RTU (station events to GSO), fire protection per TNB substation standard, control building.
- **TNB interfacing:** station typically built to TNB Substation Design Manual, then the line bays + busbar handed over/adopted by TNB (asset demarcation at CT/metering point per Connection Offer) — mirror SESB practice in Sabah.

### Option D — 33 kV tie
- 33 kV XLPE 3×1C 630 mm² circuits (1–3 nos.), 33 kV metering panel at PPU, feeder protection (OC/EF + intertrip), fibre pilot.

## 6.3 Civil & building works for interconnection (work component)

1. Substation platform earthworks & foundations (same SI/JMG logic as doc 02 — GIS hall is settlement-sensitive: raft or piled raft on soft ground).
2. **GIS building** (steel portal/RC, EOT crane 10–20 t, gas handling room) or AIS gantries/equipment plinths.
3. Control building (protection rooms, battery room, SCADA).
4. Transformer plinths + blast walls + oil bunds/interceptor; fire walls per TNB standard.
5. Cable basements/trenches, duct banks, sealing ends compound (UGC↔OHL transition).
6. Tower foundations along LILO/feeder route (pad & chimney or piled, per per-tower SI).
7. TNB-spec fencing, access road to station, drainage, earthing grid (design to measured resistivity + PMU fault level).

## 6.4 Interconnection BQ template & indicative rates (Q3-2026, RM)

| Bill | Item | Unit | Indicative rate |
|---|---|---|---|
| I-1 | Preliminaries, TNB liaison, outage management, wayleave survey | LS | 5–8 % of interconnection cost |
| I-2 | 132 kV GIS bay (supply, install, T&C) | per bay | 6.5–9.0 mil |
| I-2a | 132 kV AIS bay | per bay | 3.5–5.0 mil |
| I-3 | 132/33 kV 60/90 MVA transformer c/w OLTC | per unit | 6.0–8.0 mil |
| I-4 | 33 kV switchboard at station | LS | 3–6 mil |
| I-5 | Protection, control, SCADA, metering & telecom for station | LS | 4–8 mil |
| I-6 | 132 kV UGC 1C Cu 1000 mm², 2 cct, supply/install/joint/test | per km (2 cct) | 6.0–9.0 mil |
| I-7 | 132 kV DC OHL on lattice towers incl. foundations, stringing, OPGW | per km | 1.4–2.0 mil |
| I-8 | LILO tower modifications, cutover works, re-tensioning (2 circuits) | LS | 3–6 mil |
| I-9 | GIS building + control building civil | m² | 3,500–5,000 |
| I-10 | Substation earthworks, roads, drainage, fence, earthing | LS | 3–8 mil |
| I-11 | TNB works charges (busbar mods, protection at remote ends, adoption) | LS | per Connection Offer (2–15 mil) |

### Worked examples (planning-grade EPCC costing basis — item 9)

| Scenario | Build-up | EPCC estimate |
|---|---|---|
| **A:** spare 132 kV bay at PMU 3 km away, UGC | 1 GIS bay (8) + 3 km UGC (22) + protection/metering (5) + civil (3) + TNB charges (5) + prelims | **≈ RM 46–50 mil** |
| **B:** 132 kV LILO station at site, line 0.8 km away | 7-bay GIS (52) + 2×90 MVA trafo (14) + 33 kV board (5) + prot/SCADA (7) + LILO towers & cutover (5) + buildings/civil (14) + TNB charges (8) + prelims | **≈ RM 105–120 mil** |
| **D:** 2×33 kV feeders to PPU 2 km | 4 km cct UGC 33 kV (6) + PPU panels & metering (3) + civil (1.5) + TNB charges (2) | **≈ RM 12–15 mil** |

**Sabah/SESB adjustment:** +10–20 % construction rates; barge/road logistics for transformers; SESB approval milestones (planning study → connection agreement → design approval → witness testing) typically add 3–6 months.

## 6.5 Costing basis & assumptions (carry into any EPCC bid)

- Demarcation per Connection Offer decides who buys what — bays inside TNB PMU are usually TNB-executed at the developer's cost (works charges), not EPCC scope.
- Wayleave/ROW acquisition, tree-cutting compensation and land for the switching station are owner's cost, excluded from EPCC.
- Outage windows for LILO cutover are TNB-controlled; price outage-driven idle time and night work.
- Protection settings/approval cycles with TNB: allow 4–6 months elapsed; SAT witnessed by TNB/SESB.
- All HV plant type-tested to TNB technical specification (or SESB equivalent); vendor pre-qualification against TNB approved-vendor lists is a tender gate — check before pricing exotic OEMs.
