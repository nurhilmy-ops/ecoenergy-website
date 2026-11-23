# EcoEnergy Careers Portal — invited-candidate forms

Password-gated, non-indexed candidate forms for EcoEnergy Consultancy Sdn Bhd.
Candidates fill the forms in the browser, the server produces the signed PDF, stores it, and (optionally) emails HR.

| Route | What it does |
|---|---|
| `GET /careers/apply/<token>` | Gate page for one invited candidate. Unknown or expired token returns an identical 404. |
| `POST /careers/api/verify` | Password check (bcrypt). 5 attempts per 15 min per IP + token, then HTTP 429. Sets a signed, `HttpOnly`, `SameSite=Strict` cookie for 4 h. |
| `GET /careers/api/invite` | Candidate name, position, stage, which forms are due. |
| `POST /careers/api/submit` | Validates against `public/schema.js`, renders the PDF (`lib/pdf.js`), writes `data/submissions/<token>/<ref>.pdf` + `.json`, emails HR if SMTP is configured. |
| `GET /careers/api/pdf/<ref>` | Candidate downloads their own signed copy (session-bound). |

Forms in the portal: **HR-REC-01** Job Application, **HR-REC-02** PDPA Notice & Consent (bilingual), **HR-REC-05** Pre-Employment Declaration, **HR-REC-06** New Employee Particulars.
Which forms a candidate sees is set by the invite `stage`: `application` → 01 + 02; `offer` → 05; `onboarding` → 06.
HR-REC-03 (interview assessment) and HR-REC-04 (reference check) are internal HR forms and stay in the DOCX pack.

## Run locally
```bash
npm install
cp .env.example .env            # set SESSION_SECRET at minimum
npm start                       # http://localhost:3000
node invite.js new --name "Aisyah Rahman" --email a@x.com --position "Solar PV Engineer" --ref EE-2026-07
```
`invite.js new` prints the link and a one-time password. **Send the link by email and the password by a different channel** (WhatsApp / SMS / phone). `node invite.js list | revoke <token> | extend <token> --days 7`.

## Deploy on ecoconsultancy.services
The rest of the site can stay where it is. Only `/careers/*` needs to reach this service.

1. **Render (matches the existing `online-solar-pack` setup)**: new Web Service from this repo, Node 20, build `npm install`, start `npm start`.
   Attach a **persistent disk** (e.g. 1 GB mounted at `/var/data`) and set `DATA_DIR=/var/data`; without a disk, Render's filesystem is wiped on every deploy and you lose invites and submissions.
   The free tier has no persistent disk, so this needs the Starter plan or an external store.
2. Environment variables: everything in `.env.example`. `SESSION_SECRET` = 64 random hex chars (`openssl rand -hex 32`). `NODE_ENV=production` turns on the `Secure` cookie flag.
3. **Routing**: point `www.ecoconsultancy.services/careers/*` at this service. Options, in order of simplicity:
   - a reverse-proxy rule on the main site (Nginx `location /careers/ { proxy_pass https://<render-host>; }`; Netlify/Vercel rewrites; Cloudflare Worker route); or
   - a subdomain `careers.ecoconsultancy.services` as a CNAME to the Render host, then set `BASE_URL` accordingly.
   The app assumes it is served under `/careers`; do not strip that prefix in the proxy.
4. SMTP (optional but recommended): Google Workspace with an app password, or Amazon SES. The PDF is attached to the HR notification; the submission is stored even if email fails.

## Search engines and access
- `X-Robots-Tag: noindex, nofollow, noarchive` on every response, `<meta name="robots">` in the page, `robots.txt` disallows `/careers/*`. That stops well-behaved crawlers. It does not stop a person who has the URL, which is why the password and the per-candidate token both exist.
- The token alone (128-bit random, in the URL) is not treated as a credential: the page shows nothing until the password is verified server-side.
- Passwords are 3-part phrases with ~34 bits of entropy, adequate only because of the 5-per-15-minute lock-out and the 14-day expiry. Do not reuse a password across candidates.

## PDPA 2010 operating notes
- Submissions are personal data. Restrict who can read `DATA_DIR` and the HR mailbox; Security Principle, s.9 and the Personal Data Protection Standard 2015.
- Delete unsuccessful candidates' folders under `data/submissions/` on the retention date stated in HR-REC-02 (12 months unless they opted in to future vacancies). A cron job that removes folders older than N days is the simplest way to keep this honest.
- Render's data centres are outside Malaysia. HR-REC-02 already discloses cross-border storage under s.129; keep that clause if you change host.
- If Malaysia's Personal Data Protection (Amendment) Act 2024 breach-notification duties apply to a leak of this data, notification to the Commissioner is required; keep the server logs (`request completed` lines include IP and route) for at least the period your DPO advises.
