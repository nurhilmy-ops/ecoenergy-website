# Tender playbook — bid/no-bid, win strategy and pricing

The frameworks help decide **whether** to bid, **how to position** and **how to price**. Winning
is decided by the RFP's own compliance rules and evaluation criteria, so this playbook wraps the
frameworks around a standard capture-and-proposal process. The process follows recognised bid
practice (APMP Body of Knowledge; *Shipley Proposal Guide*). Benchmark for context: in the
Loopio/APMP 2025 benchmark survey (1,544 respondents), the self-reported average win rate was 45%
and 83% of teams used a go/no-go process. These figures are self-reported and correlational, so
don't promise a win-rate uplift from the gate. See `source-notes.md`.

## Which tender are we in?
| Type | EcoEnergy's role | Decided mainly on | Frameworks that matter most |
|---|---|---|---|
| ST/PETRA quota auction (LSS) | Advisor to a bidding client | Compliance, then evaluated tariff (with RFP-defined preferences) | SCP → business system → **bid supply curve** → 7S on the consortium |
| Government / state-agency consultancy tender | Bidder | Federal: two-envelope, technical 80 / cost 20 (Treasury PK 3.3); others per the RFP formula; registration and eligibility gates | **Bid/no-bid matrix** → decision journey → business system (win themes) → price-to-win |
| GLC procurement | Bidder | Vendor registration, technical/commercial evaluation per the GLC's policy | Same as above |
| Financier mandate (lender's TA, E&S advisor) | Bidder | Independence, credentials, named team, fee | Bid/no-bid with a hard **conflict gate** → 7S on the team |
| Private developer RFP (feasibility, owner's engineer) | Bidder | Relationship, credibility with their lender, fee | Decision journey → business system → GE matrix to prioritise accounts |

## The process and where each framework plugs in
1. **Opportunity identification.** Keep a pipeline register (scheme, client, value, dates).
   Prioritise accounts with the GE matrix (portfolio mode).
2. **Capture (before the RFP).** Understand the buyer's problem, evaluation habits and likely
   rivals using legitimate means only: public documents, past awards, briefings, your own history.
   Use SCP for market context and the decision journey for how this buyer chooses.
3. **Gate 1, pursue?** A quick bid/no-bid on what's known.
4. **RFP release.** Build the **compliance matrix**: every "shall/must", every mandatory document,
   format and page limit, the evaluation criteria and weights. Nothing else starts until this exists.
5. **Gate 2, bid?** Full bid/no-bid matrix with gates (below). Write down the decision and its
   conditions.
6. **Solution and win themes.** Use the business system to find what only EcoEnergy offers here.
   Run the 7S on the proposed team; evaluators score the methodology and the named people.
7. **Pricing.** For an LSS client, use the bid supply curve. For a consultancy tender, use the
   price-to-win arithmetic below.
8. **Review.** An independent reader scores the draft against the RFP's own criteria before
   submission ("red team"). `big4-finance-consultant` can red-team a client's financial bid.
9. **Submit, clarify, debrief.** Request a debrief win or lose. Log the result in the register: it
   is the evidence for next year's "ability to win" scores.

## Bid/no-bid: gates first, then the matrix
**Gates are pass/fail. Any fail means no-bid, whatever the score.** Typical gates (confirm against
each RFP):
- Registrations required by the RFP are valid on the closing date (e.g. MOF consultant
  registration in the specified field code; BEM-registered Engineering Consultancy Practice where
  engineering services or PE submissions are in scope; any agency vendor registration).
- Eligibility conditions (e.g. Bumiputera status for Bumiputera-reserved packages) are met.
- **No conflict of interest.** Not advising a competing bidder, the evaluator or the counter-party
  on the same project or package; not acting as lender's TA on a project whose bid the firm
  prepared. Check the conflicts register; independence is the firm's value proposition.
  - A **former-client** conflict (e.g. we screened the same site for a developer last year) can
    sometimes be cured, but only if all of these hold: the earlier engagement is closed; its
    confidential information is not material to the new work or can't be used; the former client
    consents in writing; the buyer accepts the disclosure in writing through the RFP channel; and
    the people who did the earlier work are excluded.
  - **A current-client conflict is a no-bid.** Don't drop a client to take a tender.
  - **Be honest about ethical walls in a small firm.** With a team of about ten, an information
    barrier is weak, and evaluators and lenders know it. If the only qualified person for a key role
    worked on the conflicting engagement, the wall isn't credible: no-bid. When in doubt, decline.
    The firm's independence is worth more than one fee.
- Contract terms are acceptable or priceable (liability cap, indemnities, IP ownership, payment
  terms, professional indemnity insurance level). Hand to `legal-commercial-contracts`.
- The named key personnel are available for the contract period.
- The proposal can be produced to standard before the deadline.

**Then score the matrix** (`scripts/weighted_matrix.py --mode bid`, template
`assets/bid_no_bid_template.json`):

| Opportunity attractiveness | How to evidence |
|---|---|
| Fee value & margin | Estimate from effort × rates; compare with ledger margins on similar jobs |
| Strategic fit (horizon, reference value) | Three Horizons tag; will it create a reference for an H2 line? |
| Client payment & contract risk | Payment history (AR ageing via `eco-bookkeeper-agent`), contract terms |
| Evaluation transparency | Are criteria and weights published? Is price formula stated? |
| Follow-on potential | Next stages (feasibility → TA), sister sites, framework agreements |
| Bid cost vs value | Hours to bid × rate vs expected value |

| Ability to win | How to evidence |
|---|---|
| Mandatory-requirement & track-record match | Compliance matrix vs references we can document |
| Named key personnel available | Staff plan; CVs meeting the RFP's minimums |
| Differentiators / win themes | Business-system analysis; are they provable in the proposal? |
| Client insight before the RFP (legitimate) | Prior work, briefings attended, public documents studied |
| Price competitiveness | Price-to-win analysis; past fee outcomes |

Reading the result: green cells mean bid; amber means bid only if named conditions are met by the
gate (e.g. secure a teaming partner, confirm a key person); red means decline politely and keep the
relationship. Expected value is a useful cross-check: **P(win) × margin − bid cost**. When you can't
estimate P(win) from history, say so rather than inventing one.

## Malaysian public-procurement rules that shape the bid
(Details and sources in `malaysia-context.md` §6–8; re-check before each bid.)
- **Federal consultancy (Treasury circular PK 3.3, 2022):** two stages, technical 80% / cost 20%,
  two envelopes (PK 3.6). For *studies*, the technical score weights firm 25 / staff 35 /
  methodology 35 / QA 5. **Named staff and a site-specific methodology carry 70% of the technical
  score**, so put effort there before polishing the firm profile.
- **Thresholds:** studies up to RM500k can go by direct appointment from a shortlist of at least
  three firms; above that, open tender. Being registered in the right MOF codes is what gets you on
  shortlists.
- **Integrity Pact (PK 1.6, in force 1 Jun 2025):** mandatory bidder's declaration with the bid,
  including beneficial-owner and forced-labour declarations.
- **Government Procurement Act 2026 [Act 882]** is gazetted but **not yet in force** (expected
  2027). Until commencement, the circulars apply. Watch for the commencement order and its
  regulations.
- State agencies, GLCs and statutory bodies may run their own procurement policies. Read each RFP's
  evaluation section rather than assuming the federal formula.

## Price-to-win arithmetic for quality-and-cost tenders
Many consultancy tenders combine a technical score T and a financial score F with RFP-stated
weights (federal default 80:20), and often score price as F = 100 × (lowest price ÷ your price).
Always use the formula the RFP actually states. If you price x% above the lowest compliant bid, you lose

  ΔTotal = W_f × 100 × x / (1 + x)

points, and you need a technical lead of at least ΔTotal ÷ W_t to break even.

*Example:* weights 80:20, priced 15% above the lowest bid: ΔTotal = 0.20 × 100 × 0.15/1.15 = 2.6
points, so you need a technical score at least 3.3 points (out of 100) higher than the cheapest
compliant rival. If the RFP is price-only after a technical pass mark, quality above the pass
mark earns nothing and the cost curve logic applies to fees.

## Win themes EcoEnergy can usually prove
Use only those you can evidence in this proposal:
- **Independence.** Not tied to an EPC; willing to say no; staged gates. Prove it with the
  conflicts policy and an example of a no-go recommendation.
- **Integrated disciplines.** Engineering, finance, regulatory and legal in one accountable team.
  Prove it with the named team and the hand-off method.
- **Lender-grade outputs.** Models reconcile to source rows and have been defended in DD. Prove it
  with an anonymised case.
- **Regulatory currency.** Published analysis of current rules (LSS6, CRESS SAC, SELCO revisions).

## Integrity checklist (every bid)
- Communication only through the RFP's named channel during the tender.
- No gifts, hospitality or favours to the buyer's staff or evaluators. Record anything offered or
  requested. Corporate liability under MACC Act 2009 s.17A applies unless "adequate procedures" are
  in place.
- Sign and honour the Integrity Pact (mandatory in federal procurement under PK 1.6). Bid-rigging
  and corruption clauses go into every contract.
- No contact with competitors about prices, bid/no-bid intentions or market sharing (Competition
  Act 2010). Teaming agreements must be genuine and documented, and legal should review them.
- Client confidentiality: never reuse one client's bid data in another client's analysis.
