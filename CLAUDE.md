# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Marketing website for EcoEnergy Consultancy Sdn. Bhd., a Malaysian renewable-energy advisory firm. It is a hand-written static site — no framework, no build system, no package.json, no tests, no linters. Plain HTML files with all CSS and JavaScript inlined in each page.

**Deployment:** GitHub Pages from the `main` branch at the custom domain `www.ecoconsultancy.services` (see `CNAME`). Anything merged to `main` is live in production within minutes. Do not delete or modify `CNAME` or `google7d2565a6f838fcaf.html` (Google Search Console verification).

## Development

There is no build or test step. To preview locally:

```bash
python3 -m http.server 8000   # then open http://localhost:8000
```

Verification is manual: check the page in a browser, ideally at mobile and desktop widths. When editing JSON-LD blocks, validate the JSON parses (e.g. paste into `python3 -c "import json,sys; json.load(sys.stdin)"`).

`.gitignore` excludes `design-variants.html` and `variant-*.html` — use those filenames for local design experiments that shouldn't be committed.

## Pages

- `index.html` — single-page marketing site. Fixed header navigates to anchored sections: `#services`, `#sectors`, `#approach`, `#models` (engagement models), `#record`, `#guarantee`, `#faq`, `#contact`. Also has a scroll-progress bar, sticky `#bookbar` CTA, and a one-time `#nudge` slide-in (dismissal stored in `sessionStorage` under `ecoNudge`).
- `consult/index.html` — LSS/CRESS lead-capture landing page. Its form posts to **formsubmit.co** (`https://formsubmit.co/ajax/contact@ecoconsultancy.services` via fetch, with a non-JS `action` fallback to the same service). Keep the recipient address in sync with the site-wide contact email.
- `insights/index.html` — blog listing page with `Blog` JSON-LD containing a `blogPost` array.
- `insights/*.html` — individual articles (currently one), each with `BlogPosting` JSON-LD including `datePublished`/`dateModified`.

There is no server-side code anywhere; the only external services are Google Fonts and formsubmit.co.

## Architecture: self-contained pages sharing a duplicated design system

Every page carries its own complete `<style>` and `<script>` blocks — there are no shared .css or .js files. The design system is **copy-pasted into each page** and must be kept visually consistent when you edit or add pages:

- **Design tokens** — each page's `:root` defines the same palette: `--navy-deep:#081527` (background), `--navy`, `--navy-raised`, `--navy-line`, `--gold:#D4A23A` / `--gold-deep` (accent), `--paper:#F4EFE6` (text), `--cloud`/`--cloud-dim` (muted text), plus `--ease:cubic-bezier(.22,.8,.24,1)`.
- **Typography** — Google Fonts trio used everywhere: Fraunces (`--serif`, headings, with gold italic `<em>` accents), Hanken Grotesk (`--sans`, body), Spline Sans Mono (`--mono`, kickers/labels/CTAs).
- **Recurring components** — `.wrap` (max-width container), `.kicker` (mono uppercase label with gold dash), gold `h2 em` italics, `.btn-gold`/`.btn-ghost` buttons, fixed blurred-navy header with gold underline link hover.
- **JavaScript idiom** — a single vanilla-JS IIFE at the bottom of the body (no libraries): `IntersectionObserver` for `.reveal` scroll-reveal animations and count-ups, one rAF-throttled scroll handler, and `prefers-reduced-motion` respected for all motion. A tiny `document.documentElement.className+=' js'` snippet in `<head>` gates animation styles so content stays visible without JS.

When creating a new page, start from an existing page (e.g. `consult/index.html`) to inherit the tokens, header, and conventions. Subdirectory pages reference assets with `../assets/...`.

## SEO conventions (applied to every page)

Each page's `<head>` includes: unique `<title>` and `meta description`, `<link rel="canonical">` with the full `https://www.ecoconsultancy.services/...` URL, `meta name="robots"`, `theme-color` `#081527`, full Open Graph + Twitter card tags (sharing `assets/og-image.png`), `og:locale` `en_MY`, and a JSON-LD block appropriate to the page type (`ProfessionalService` on the homepage, `Blog` on the insights index, `BlogPosting` on articles).

**When adding or materially changing a page**, update all of:
1. `sitemap.xml` — add/update the `<url>` entry with a fresh `<lastmod>`.
2. For a new insights article: add a card to `insights/index.html` **and** an entry to its `Blog` JSON-LD `blogPost` array.
3. Cross-links from relevant existing pages (the main nav on `index.html` links to `insights/index.html`).

## Domain terminology

Content is written around Malaysian renewable-energy schemes and regulators — NEM, SELCO, Solar ATAP, LSS/LSS6, CGPP, CRESS, Corporate PPA, the Energy Commission (Suruhanjaya Tenaga), TNB, BESS, FPV. Use these terms as-is; they are scheme names, not typos. Contact details used across pages: `contact@ecoconsultancy.services`, `+60 3 8744 6478` (`tel:+60387446478`), Level 22, Menara Merdeka 118, Kuala Lumpur — keep them consistent everywhere, including JSON-LD.
