# Strategic control map — hunter or hunted?

## What it is and where it comes from
Plot every company in an industry by **size** (book value, log scale) and **performance**
(market-to-book ratio, log scale). Since market cap = book value × market-to-book, the diagonals
are lines of equal market cap; further up and right means more control. Quadrants: **strategic
control** (large, highly valued: hunters), **niche performers** (small, highly valued), **under-
performing giants** (big, cheap), **takeover targets** (small, cheap). Cite McKinsey Quarterly,
"Enduring Ideas: The strategic control map" (July 2010). McKinsey attributes its development to
Vijay D'Silva, Bob Fallon and Asheet Mehta in 1996, but no public 1996 publication was found.

## Fit check: it needs market values
The map only works for **listed** companies. EcoEnergy is a private Sdn Bhd and has no market
value, so don't force the firm onto the map. Use it for:

1. **Buy-side / sell-side opportunity scanning (firm level).** Plot Bursa-listed solar
   EPC-developers and IPPs (peer list in `malaysia-context.md`). *Hunters* (strategic control) are
   prospective clients for **buy-side due diligence and lender's TA** on acquisitions of awarded LSS
   or CRESS projects. *Takeover targets* and *under-performing giants* are prospective clients for
   **sell-side readiness**: vendor DD, model clean-up, bankability fixes. This links directly to
   the Stage 03 Transaction Advisory offer.
2. **Partner risk in a bid consortium (client level).** A consortium partner in the takeover-target
   quadrant may change hands mid-project. Make sure change-of-control, pre-emption and
   lender-consent clauses are in the consortium or shareholders' agreement; hand to
   `legal-corporate-dd`.
3. **Post-award consolidation (client level).** After an LSS round, winners that struggle to finance
   become acquisition targets. A client on the hunter side can buy awarded capacity rather than bid.
   Check the RFP and PPA rules on change of shareholding before advising this.

## Build it
1. Pull book value and market cap for 10–20 listed peers in **one** industry, from Bursa
   announcements and annual reports or a market-data connector if available. Fetch them live,
   because valuations move daily; never hard-code them in a deliverable.
2. Plot on log scales and split at the peer medians.
3. Plot five years of history to see each company's trajectory.
4. Decide: who could buy whom, who could buy the client, and what move keeps the client in control.

## Where it misleads
- **Compare within one industry only.** Normal multiples differ widely across sectors.
- **Asset-light firms look small on book value.** Consultancies, software and services firms carry
  intangibles that don't show on the balance sheet.
- **Bursa small caps:** thin liquidity and sentiment (e.g. share-price spikes on LSS award
  announcements) distort market-to-book. Check return on capital before reading much into a
  multiple.
- **Take-over rules shape who can actually buy.** Mandatory-offer and other requirements under
  Malaysia's take-over code apply to listed targets. Hand any real transaction to
  `legal-corporate-dd`.
