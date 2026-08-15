# 1. BESS Infrastructure — Required Components & Cabling

Reference design: **100 MW / 400 MWh, LFP, 1500 Vdc, 33 kV collection**. Adjust container/PCS counts pro-rata for other block sizes.

## 1.1 System architecture (single-line, simplified)

```
LFP racks (1500Vdc) ── DC cables ── PCS (bidirectional inverter, 690–800Vac)
   ── LV busduct/cable ── MV step-up transformer (0.69/33kV)
   ── 33kV XLPE collection cables ── 33kV switchgear (e-house)
   ── main power transformer 33/132kV (if transmission-connected)
   ── interconnection facility (PMU busbar / LILO switching station)
```

## 1.2 Component detail

### A. Battery storage units
| Item | Detail |
|---|---|
| Cell chemistry | LiFePO₄ (LFP), 280–314 Ah prismatic cells, ≥6,000 cycle design life |
| Enclosure | 20-ft ISO containerised / integrated cabinet, 3.7–5.0 MWh per unit (e.g. CATL EnerC+, Sungrow PowerTitan 2.0, Tesla Megapack, BYD MC Cube). ~**80–110 units** for 400 MWh incl. degradation & augmentation overbuild |
| Thermal management | Integrated liquid cooling (preferred in Malaysian ambient 24–35 °C, ~85 % RH); HVAC for cabin-type |
| Fire safety | Per NFPA 855 / UL 9540A: cell-level gas (off-gas) detection, smoke/heat detection, aerosol or NOVEC/perfluoroketone suppression per container, deflagration venting per NFPA 68/69, min. separation to Bomba requirements (typ. ≥3 m between rows or fire-rated barrier), external hydrant coverage |
| BMS | 3-tier (cell/module → rack → system); SOC/SOH estimation, cell balancing, protective interlocks; interfaces to EMS via Modbus TCP / IEC 61850 |
| Degradation strategy | DC-side overbuild (~5–10 %) plus augmentation bays/space reserved for years 5–10 |

### B. Power conversion system (PCS)
| Item | Detail |
|---|---|
| Type | Bidirectional grid-forming or grid-following inverter, central skid (2.5–5 MVA) or string PCS integrated per container |
| Count | ~**25–30 × 3.45–4.2 MVA** skids for 100 MW (with reactive capability ±0.85 pf per Grid Code) |
| DC input | 1000–1500 Vdc; AC output 690–800 V, 50 Hz |
| Compliance | Malaysian Grid Code / Distribution Code, LVRT/HVRT, frequency response (primary reserve if contracted), IEEE 519 harmonics |

### C. Medium-voltage step-up transformers
- Pad-mount / skid-mount **0.69(0.8)/33 kV, 3.5–7 MVA**, ONAN, Dyn11, typically integrated on the PCS skid ("MV skid").
- Oil-immersed (mineral or ester); bunded plinth with oil containment (see civil works).

### D. 33 kV collection & main switchgear
- **33 kV, 25 kA, single-busbar switchboard** in air-conditioned e-house: incomer(s), feeder panels (1 per 2–4 MV skids, typ. 8–12 feeders), bus section, aux transformer feeder, metering panel, VCB, numerical protection relays (feeder OC/EF, busbar, transformer diff for main trafo).
- If transmission connected: **main power transformer(s) 33/132 kV, 2 × 60/90 MVA ONAN/ONAF** (N-1 optional per Connection Offer), NER/NGR earthing as required by TNB.

### E. Control, metering & communications
| Item | Detail |
|---|---|
| EMS / PPC | Site energy management system + power plant controller: dispatch (P/Q setpoints), AGC interface, SOC management, peak shaving/arbitrage logic |
| SCADA & RTU | IEC 60870-5-104 / DNP3 RTU to TNB Grid System Operator (GSO) or SESB control centre; hardwired intertrip as per Connection Offer |
| Metering | Bulk supply billing metering per Malaysian Metering Code — main & check meters, class 0.2s CTs / 3P VTs, sited at the delivery point |
| Telecoms | OPGW/fibre to TNB (teleprotection + SCADA), redundant LAN, GPS time sync, CCTV & access control |

### F. Auxiliary & balance of plant (electrical)
- Auxiliary transformer(s) 33/0.415 kV 500–1000 kVA (+ backup genset 200–500 kVA), LVAC switchboard.
- 110 Vdc battery & charger (protection/switchgear), 48 Vdc (telecoms), UPS for EMS/SCADA.
- Earthing & lightning protection: buried bare copper grid (typ. 70–120 mm² conductor) under BESS yard and switchyard, earth rods, equipotential bonding of containers/skids, air terminals/masts per MS IEC 62305; design to IEEE 80 (step/touch) with measured soil resistivity.
- Yard lighting, small power, fire alarm main panel, public address.

## 1.3 Cabling schedule (typical, 100 MW / 400 MWh)

| Cable system | Typical spec | Route | Indicative qty |
|---|---|---|---|
| DC battery ↔ PCS | 1× Cu XLPE 1.8/3 kV DC single-core, 300–400 mm², UV-resistant | Tray/ladder between container and PCS skid (<20 m runs) | 25–40 km |
| LV AC PCS ↔ MV skid trafo | Busduct or 1× Cu XLPE 0.6/1 kV multiple parallel runs | On-skid / short tray | included in skids |
| 33 kV collection | 3× single-core or 3-core Al/Cu XLPE 19/33 kV, 240–630 mm², screened, STA | Directly buried in sand-bedded trench with tiles/warning tape, or concrete-encased ducts at road crossings | 6–12 km |
| 33 kV export (to main trafo / PMU) | 1–2 circuits, single-core Cu XLPE 630–1000 mm² | Trench/duct bank | per layout |
| Auxiliary LV | Cu XLPE/PVC 0.6/1 kV, various | Trays + trenches | 8–15 km |
| Control & protection | Multicore Cu 2.5 mm² screened; separate from power | Trench with segregation | 20–40 km |
| Fibre optic | Single-mode armoured 24–48 core + patch | With control routes; OPGW on OHL | 5–10 km + line length |
| Earthing | Bare stranded Cu 70–120 mm², rods 5/8″×1.8 m | Buried grid 0.6–0.8 m | 10–20 km grid |

**Cabling rules of practice (TNB context):** MV joints minimised and pre-agreed; screens solidly bonded (single-point bonding for long single-core runs with SVLs); minimum burial 0.9 m for 33 kV (1.1 m under roads, ducted); segregation power/control ≥300 mm; all penetrations into e-house fire-stopped; cable schedules and drum management to be part of EPCC QA records.

## 1.4 Non-electrical BOP
- E-house / control building (switchgear, EMS, office, store), guard house.
- Internal roads (crane-rated for container placement), hardstanding, fencing (anti-climb 2.4 m + barbed, TNB substation standard at interconnection compound), gates, drainage, water supply & fire hydrant/hose reel system as required by Bomba, sanitary system.
