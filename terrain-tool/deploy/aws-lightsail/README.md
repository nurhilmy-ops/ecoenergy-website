# Put the terrain screening tool online — Amazon Lightsail in Malaysia

This guide takes you from nothing to the tool running at **https://tools.ecoconsultancy.services**
on a small Amazon Web Services (AWS) server in the **Asia Pacific (Malaysia)** region, with
sign-in emails sent by **Amazon SES** in the same region. No programming is needed: you click
through the AWS and Namecheap websites, and paste **one command** into a browser window.

| | |
|---|---|
| **Time** | about 1 hour of clicking, plus waiting (region: minutes to hours; DNS: usually under 30 minutes; SES production access: up to about 4 days) |
| **Cost** | about **US$12–13 a month** (details in [Part H](#what-it-costs)) |
| **You need** | a credit or debit card for AWS, your Namecheap login, and access to the `contact@ecoconsultancy.services` mailbox |

**The parts, in order:**
[A. AWS account and the Malaysia region](#part-a--aws-account-and-the-malaysia-region) ·
[B. Create the server](#part-b--create-the-server-in-lightsail) ·
[C. Point the address at it](#part-c--point-toolsecoconsultancyservices-at-the-server-namecheap) ·
[D. Install the tool](#part-d--install-the-tool-one-command) ·
[E. Email (Amazon SES)](#part-e--email-with-amazon-ses-malaysia) ·
[F. DMARC](#part-f--dmarc-and-private-email-dkim) ·
[G. Go live](#part-g--go-live) ·
[H. Everyday](#part-h--everyday-running) ·
[Troubleshooting](#troubleshooting) ·
[What is stored where](#what-this-server-stores-and-where-for-the-privacy-notice)

> AWS changes its screens from time to time. If a button is not exactly where this guide says,
> look for the same words nearby. Names in **bold** are what you click or see.

---

## Part A — AWS account and the Malaysia region

1. If you have no AWS account yet, go to <https://aws.amazon.com>, choose **Create an AWS
   Account** and follow the steps (email, password, contact details, card, phone check). Choose
   the **Basic support – Free** plan. New accounts may get AWS Free Tier credits; the steps here
   work either way. During sign-up AWS may suggest enabling the Malaysia region: accept it.
2. Sign in to the **AWS Management Console** (<https://console.aws.amazon.com>) with the email
   and password of the account.
3. Click your **account name** at the top right, then **Account**.
4. Scroll down to the section **AWS Regions**. Find **Asia Pacific (Malaysia)**
   (code `ap-southeast-5`). If its status is **Enabled**, go to Part B.
5. Select it, click **Enable**, read the message and click **Enable region**.
6. Wait until the status is **Enabled**. This usually takes a few minutes but can take several
   hours. You cannot use the region before then (Part B will not offer it).

---

## Part B — Create the server in Lightsail

### B1. The server

1. Open the Lightsail console: <https://lightsail.aws.amazon.com>.
2. Click **Create instance**.
3. Under **Instance location**, click **Change AWS Region and Availability Zone** and choose
   **Asia Pacific (Malaysia)** (`ap-southeast-5`). Leave the Availability Zone as it is.
4. **Select a platform:** **Linux/Unix**.
5. **Select a blueprint:** click **OS Only**, then **Ubuntu 24.04 LTS**.
6. Leave **Optional** settings (launch script, SSH key) as they are. If you see
   **Enable Automatic Snapshots**, you may tick it here (otherwise do it in B4).
7. **Choose your instance plan:** keep the network type **Dual-stack** (IPv4 and IPv6; not
   IPv6-only) and choose the **US$12 per month** plan: **2 GB memory, 2 vCPUs, 60 GB SSD**.
   (In the Malaysia region the plan includes 1.5 TB of data transfer a month: far more than the
   tool uses.)
8. **Identify your instance:** type the name **`terrain-tool`**.
9. Click **Create instance**. After a minute or two the instance shows **Running**.

### B2. A fixed (static) IP address

Without this, the server's address changes whenever it is stopped and started.

1. In the Lightsail console, click **Networking** in the left menu, then **Create static IP**.
2. Make sure the region is **Asia Pacific (Malaysia)**. Under **Attach to an instance** choose
   **terrain-tool**.
3. Name it `terrain-tool-ip` and click **Create**.
4. **Write down the address** (four numbers like `43.216.12.34`). You need it in Part C.

The static IP is free while it is attached to the instance. (If you ever delete the instance,
delete the static IP too: an unattached one costs US$0.005 an hour.)

### B3. Open the HTTPS port (443)

1. Click **Instances** in the left menu, then the name **terrain-tool**.
2. Open the **Networking** tab and scroll to **IPv4 Firewall**. You will see **SSH (22)** and
   **HTTP (80)**: keep both (HTTP is needed to get the free certificate and to redirect to
   HTTPS; SSH is needed for the browser terminal).
3. Click **Add rule**, choose **Application: HTTPS**, and click **Create**.
4. (Optional) If there is also an **IPv6 Firewall** section, add **HTTPS** there in the same way.

### B4. Automatic snapshots (whole-server backups)

1. On the **terrain-tool** instance page, open the **Snapshots** tab.
2. Under **Automatic snapshots**, switch the toggle on and confirm with **Yes, enable**.
3. Click **Change snapshot time** (if shown) and choose **19:00 UTC** (03:00 in Malaysia), so
   the snapshot also contains the tool's own nightly database backup made at 02:30.

Lightsail keeps the 7 most recent daily snapshots and replaces the oldest automatically.

---

## Part C — Point tools.ecoconsultancy.services at the server (Namecheap)

Your domain's DNS stays at Namecheap (BasicDNS). You only **add** one record; do not change the
existing website (`@`, `www`) or email (`MX`, SPF) records.

1. Sign in at <https://www.namecheap.com> and open **Domain List**.
2. Click **Manage** next to **ecoconsultancy.services**, then the **Advanced DNS** tab.
3. Under **HOST RECORDS**, click **ADD NEW RECORD** and fill in:
   - **Type:** `A Record`
   - **Host:** `tools`
   - **Value:** the static IP from B2 (for example `43.216.12.34`)
   - **TTL:** `Automatic`
4. Click the **green tick** (✓) to save.

**Check it** (usually works within 5–30 minutes): open
<https://dnschecker.org/#A/tools.ecoconsultancy.services> and look for your static IP, or on a
Windows/Mac computer open a terminal and type `nslookup tools.ecoconsultancy.services`.
Part D works even if DNS is not ready yet; the HTTPS certificate simply follows once it is.

---

## Part D — Install the tool (one command)

### D1. Open the terminal in your browser

1. In Lightsail, open **Instances → terrain-tool**, the **Connect** tab, and click
   **Connect using SSH**. A black terminal window opens in a new browser window, ending with a
   line like `ubuntu@ip-172-26-…:~$`.
2. **How to paste into this window:** copy the command below as usual (Ctrl+C / Cmd+C), then
   in the terminal window click the **clipboard icon** at the bottom right, paste into the box
   that opens, and **right-click** anywhere in the black area. The command appears; press
   **Enter**.

### D2. Paste the setup command

**Before the pull request is merged** (the tool is still on the branch
`claude/admiring-albattani-j1beqs`) — use this one:

```bash
curl -fsSL https://raw.githubusercontent.com/nurhilmy-ops/ecoenergy-website/claude/admiring-albattani-j1beqs/terrain-tool/deploy/aws-lightsail/setup.sh | sudo TOOL_REF=claude/admiring-albattani-j1beqs bash
```

**After the pull request is merged into `main`** — use this one instead:

```bash
curl -fsSL https://raw.githubusercontent.com/nurhilmy-ops/ecoenergy-website/main/terrain-tool/deploy/aws-lightsail/setup.sh | sudo bash
```

It is one long line: paste it whole.

### D3. What you will see

Lines starting with `==>` show each step: preparing Ubuntu, downloading the tool, installing
packages, swap space, the app user, the Python environment, the settings file, the services,
the Caddy web server (HTTPS), starting the tool. **It takes about 3–8 minutes.** Do not close
the window while it runs.

At the end you get a **summary**:

- what was set up;
- a **status** block: whether the tool answers, whether `tools.ecoconsultancy.services` points
  to this server (**DNS: OK**) and whether HTTPS works (**HTTPS: OK**);
- **ADMIN PAGES** with the user name `admin` and a random **password**. **Copy the password
  into your password manager now.** It is shown only this once (you can display it again later
  with `sudo terrain-tool admin-password`).

If it stops with **SETUP STOPPED** or **SETUP FAILED**, read the message: it says what to do.
Running the same command again is always safe. See [Troubleshooting](#troubleshooting).

### D4. Check it

Open **https://tools.ecoconsultancy.services** in your browser. You should see the landing page
with a padlock. If HTTPS is not ready yet (status says **HTTPS: NOT YET**), wait 5 minutes after
DNS is OK and run:

```bash
sudo terrain-tool restart
sudo terrain-tool status
```

Do not use the sign-up form yet: emails can only be sent after Part E. (Until then a visitor
sees "We couldn't send the email right now — please try again later".)

---

## Part E — Email with Amazon SES (Malaysia)

The tool sends two kinds of email: the sign-in link and the "report is ready" notice, from
`EcoEnergy Consultancy <no-reply@ecoconsultancy.services>` with replies going to
`contact@ecoconsultancy.services`. They go through **Amazon SES in the Malaysia region** using
its HTTPS API (AWS offers no SES SMTP server in that region; the tool does not need one).

> **Every SES step must be done in the Asia Pacific (Malaysia) region.** In the AWS console,
> the region name is shown at the top right, next to your account name. Click it and choose
> **Asia Pacific (Malaysia) ap-southeast-5** before you start. SES settings are separate in
> every region.

### E1. Verify the domain (with DKIM)

1. Open the SES console: <https://console.aws.amazon.com/ses/> (check the region: **Malaysia**).
   If SES shows a **Get started** wizard, you can close it and use the steps below.
2. In the left menu, under **Configuration**, click **Identities**, then **Create identity**.
3. **Identity type:** **Domain**. **Domain:** `ecoconsultancy.services` (without `www`).
4. Leave **Assign a default configuration set** and **Use a custom MAIL FROM domain** unticked.
5. Open **Advanced DKIM settings**: **Identity type: Easy DKIM**, **DKIM signing key length:
   RSA_2048_BIT**, and make sure **DKIM signatures** is **Enabled**. (**Publish DNS records to
   Route53** does not apply: your DNS is at Namecheap.)
6. Click **Create identity**. The identity page opens with status **Verification pending**.
7. On its **Authentication** tab, open **Publish DNS records**. There are **three CNAME
   records**. Click **Download .csv record set** to keep a copy.

### E2. Add the three DKIM records in Namecheap

For **each** of the three records: in Namecheap, **Domain List → Manage → Advanced DNS →
ADD NEW RECORD**, then:

- **Type:** `CNAME Record`
- **Host:** the **Name** from SES **without** `.ecoconsultancy.services` at the end. Example: SES
  shows `abcd1234efgh._domainkey.ecoconsultancy.services` → type `abcd1234efgh._domainkey`
  (Namecheap adds the domain by itself).
- **Value / Target:** the **Value** from SES exactly, e.g. `abcd1234efgh.dkim.amazonses.com`
- **TTL:** `Automatic`, then the **green tick** (✓).

Do not change the existing MX or SPF (`v=spf1 include:spf.privateemail.com ~all`) records: SES
does not need SPF changes, because DKIM signs its mail for `ecoconsultancy.services`.

### E3. Wait for "Verified"

Back in SES (**Configuration → Identities**), refresh after 10–30 minutes. The domain should
show **Identity status: Verified** and **DKIM configuration: Successful**. (It can take up to
72 hours; if it does not verify, check that the Host fields have no extra
`.ecoconsultancy.services`.)

### E4. A sending-only user for the server (IAM)

The server gets its own AWS user that can **only send email from
`no-reply@ecoconsultancy.services` in the Malaysia region** — nothing else. (Lightsail servers
cannot use AWS "roles", so this user's access key is stored on the server.)

1. Open the IAM console: <https://console.aws.amazon.com/iam/> (IAM is global; the region does
   not matter here).
2. Left menu **Users** → **Create user**. **User name:** `terrain-tool-ses`. Do **not** tick
   *Provide user access to the AWS Management Console*. Click **Next**.
3. **Permissions options:** **Attach policies directly**, select nothing, click **Next**, then
   **Create user**.
4. Click the new user **terrain-tool-ses** → **Permissions** tab → **Add permissions** →
   **Create inline policy**.
5. Click **JSON**, delete what is in the editor, and paste exactly this:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "SendToolEmailFromMalaysiaOnly",
         "Effect": "Allow",
         "Action": [
           "ses:SendEmail",
           "ses:SendRawEmail"
         ],
         "Resource": [
           "arn:aws:ses:ap-southeast-5:*:identity/*",
           "arn:aws:ses:ap-southeast-5:*:configuration-set/*"
         ],
         "Condition": {
           "StringLike": {
             "ses:FromAddress": [
               "no-reply@ecoconsultancy.services",
               "*<no-reply@ecoconsultancy.services>"
             ]
           }
         }
       }
     ]
   }
   ```

   Click **Next**, name it `ses-send-no-reply-malaysia`, and click **Create policy**.

   *Why this policy:* the tool calls the SES v2 `SendEmail` API with a ready-made (raw) message;
   AWS's own sending-only example allows `ses:SendEmail` and `ses:SendRawEmail` together, so
   both are allowed here, and nothing else (no reading, no settings). `ap-southeast-5` limits it
   to the Malaysia region; the identities of your own verified domain are the only ones it can
   use (the `*` stands for your account, which is the only one the user belongs to); and the
   condition allows only the From address `no-reply@ecoconsultancy.services` (with or without
   the display name "EcoEnergy Consultancy"). The second resource line only matters if you
   later add an SES configuration set.

### E5. Create the access key

1. Still on **terrain-tool-ses**, open the **Security credentials** tab.
2. Under **Access keys**, click **Create access key**.
3. **Use case:** **Application running outside AWS** (if it is not listed, choose **Other**).
   Click **Next**. **Description tag value:** `lightsail terrain-tool`. Click
   **Create access key**.
4. On **Retrieve access keys**, keep this page open (the secret is shown **only now**). Click
   **Download .csv file** as a backup and keep it somewhere safe; never email it.

### E6. Put the key on the server

In the Lightsail browser terminal (Part D1), run:

```bash
sudo terrain-tool set-aws-keys
```

Paste the **Access key** (starts with `AKIA`), press Enter, then paste the **Secret access key**
(nothing appears while you paste it — that is normal) and press Enter. The tool restarts and
says **Done**. You can now click **Done** on the AWS page.

### E7. Send yourself a test email (SES "sandbox")

New SES accounts start in the **sandbox**: they can send **only to addresses you have verified
in SES**, at most **200 emails a day** and **1 per second**. While in the sandbox, real visitors
cannot get their sign-in emails — that is why E8 matters.

1. In SES (**Malaysia**): **Configuration → Identities → Create identity → Email address**,
   type your own address (e.g. `contact@ecoconsultancy.services`), **Create identity**, then
   click the link in the email from AWS (subject *Amazon Web Services – Email Address
   Verification Request in region Asia Pacific (Malaysia)*).
2. In the terminal:

   ```bash
   sudo terrain-tool test-email contact@ecoconsultancy.services
   ```

   - **Sent. Check the inbox…** — look in the inbox (and the spam folder).
   - **FAILED: …** — the message says what is wrong in plain words, e.g. *SES is in the sandbox
     and this address is not verified*, *AWS does not recognise the access key ID*, or *the IAM
     user is not allowed to send this email*. Fix it and run the test again.

### E8. Ask AWS for production access (leave the sandbox)

1. In SES (**Malaysia**), click **Account dashboard** in the left menu. In the box *Your Amazon
   SES account is in the sandbox*, click **View Get set up page**, then **Request production
   access**.
2. Fill in:
   - **Mail type:** **Transactional**
   - **Website URL:** `https://tools.ecoconsultancy.services`
   - **Additional contacts:** `contact@ecoconsultancy.services`
   - **Preferred contact language:** English
   - Tick the **Acknowledgement** and click **Submit request**.
3. AWS answers within about 96 hours (4 days), usually by email, and often asks how you send
   email. You can reply with this text (adjust the volume if you expect more):

   > EcoEnergy Consultancy runs a free terrain screening tool for solar and land developers in
   > Malaysia at https://tools.ecoconsultancy.services. We send only transactional emails that
   > a visitor triggers themselves: (1) a sign-in link after they type their address into our
   > form, and (2) a notice that their report is ready. Nothing is sent to purchased or
   > imported lists. The sign-in link itself confirms the address (double opt-in); addresses
   > that are never confirmed are deleted after 7 days, and the form is rate-limited per
   > address and per IP. Newsletter consent is a separate, unticked box and is confirmed by
   > the emailed link; we do not send newsletters through this account, and every newsletter
   > we send elsewhere carries a one-click unsubscribe. Each email names the sender, links our
   > privacy notice and account page, and has Reply-To contact@ecoconsultancy.services, which
   > we read. We expect about 50–300 emails a month (well under 1,000), and we monitor bounces
   > and complaints in the SES account dashboard and remove addresses that bounce or complain.

4. When AWS approves, the dashboard no longer shows the sandbox box: anyone can now receive the
   tool's emails. Test with an address you have **not** verified (e.g. a Gmail address):
   `sudo terrain-tool test-email someone@gmail.com`.

---

## Part F — DMARC and Private Email DKIM

These two records tell Gmail and Outlook that mail claiming to be from your domain is genuine.
They also help your normal Namecheap Private Email.

### F1. DKIM for Namecheap Private Email

1. In Namecheap, open **Private Email** in your account menu (or **Dashboard → Private
   Email**), and click **Manage** next to the subscription for `ecoconsultancy.services`.
2. Under **DKIM**, click **Show DKIM** (or **Generate** if there is no key yet). It shows a TXT
   record. Its host is `default._domainkey` for subscriptions bought before 2 June 2026, or
   `privateemail._domainkey` for newer ones — use exactly what the page shows.
3. **Domain List → Manage → Advanced DNS → ADD NEW RECORD:** **Type:** `TXT Record`, **Host:**
   that host (e.g. `default._domainkey`), **Value:** the whole `v=DKIM1; k=rsa; p=…` text
   (without quotes), **TTL:** `Automatic`, then the green tick.

### F2. DMARC

Add one more record: **Type:** `TXT Record`, **Host:** `_dmarc`, **TTL:** `Automatic`,
**Value:**

```
v=DMARC1; p=none; rua=mailto:contact@ecoconsultancy.services; fo=1
```

`p=none` only reports, it blocks nothing: Google, Microsoft and others then email daily
summaries (XML attachments) to `contact@ecoconsultancy.services`. After 2–4 weeks in which those
reports show your own mail passing, change `p=none` to `p=quarantine` (failing mail goes to
spam). Check the whole setup with a free tester such as <https://www.mail-tester.com>: send
`sudo terrain-tool test-email <the address it gives you>` and read the score.

---

## Part G — Go live

1. `sudo terrain-tool status` shows **Tool: active, answering**, **DNS: OK**, **HTTPS: OK** and
   an **Email** line with your key.
2. Open **https://tools.ecoconsultancy.services**, sign up with your own address, open the
   email, press **Continue**, upload `hilly_site_pahang.kml` (from `terrain-tool/tests/fixtures/`
   in the repository) and check the result page, the PDF and the Word file.
3. Open **https://tools.ecoconsultancy.services/admin**, sign in as `admin` with the password
   (`sudo terrain-tool admin-password`) and find your own test screening under **Leads**.
4. **Merge the pull request** on GitHub (`claude/admiring-albattani-j1beqs` into `main`). This
   also publishes the links to the tool on the main website (GitHub Pages updates within a few
   minutes).
5. Switch the server to `main`, so later updates come from there:

   ```bash
   sudo terrain-tool update --ref main
   ```

   From now on `sudo terrain-tool update` (without `--ref`) keeps following `main`.
6. Before announcing the tool, work through the **Before going live** list in
   [`terrain-tool/README.md`](../../README.md#before-going-live) (privacy notice legal review,
   Cloudflare Turnstile keys, monitoring).

---

## Part H — Everyday running

All commands are typed in the Lightsail browser terminal (Part D1). `sudo terrain-tool help`
lists them.

| Command | What it does |
|---|---|
| `sudo terrain-tool status` | Is everything running? Version, disk, memory, last backup, DNS + HTTPS, email |
| `sudo terrain-tool logs` | The last 200 log lines (`logs -f` keeps following; Ctrl+C stops) |
| `sudo terrain-tool restart` | Restarts the tool and the web server |
| `sudo terrain-tool update` | Installs the newest version of the tool (`--ref NAME` switches branch or tag) |
| `sudo terrain-tool admin-password` | Shows the admin user name and password |
| `sudo terrain-tool set-aws-keys` | Enters (or replaces) the SES access key |
| `sudo terrain-tool test-email ADDRESS` | Sends a test email with the real settings |
| `sudo terrain-tool backup-now` | Backs up the database now |

### Updates

- **Ubuntu security updates install themselves** every day. When one needs a restart (for
  example a new Linux kernel), the server restarts by itself at **03:30 Malaysia time**; the
  tool is back within about a minute.
- **The tool** is updated when you run `sudo terrain-tool update` (for example after a change
  has been merged on GitHub). It keeps your settings, secrets, data and backups. It also
  updates Caddy and installs any new Python libraries the new version asks for.
- **Changing a setting** (for example `RETENTION_DAYS`, or Cloudflare Turnstile keys): run
  `sudo nano /etc/terrain-tool/terrain-tool.env`, change the line, save with Ctrl+O, Enter,
  Ctrl+X, then `sudo terrain-tool restart`. Every setting is explained in
  [`terrain-tool/README.md`](../../README.md#configuration).

### Backups

- **Database, every night at about 02:30 Malaysia time**: a consistent copy of the SQLite
  database in `/var/lib/terrain-tool/backups/app-YYYYMMDD.db`. The newest **14** are kept, so
  data deleted in the tool is gone from these backups after 14 days.
- **Whole server, every night (Lightsail automatic snapshots, B4)**: the newest **7** are kept.
  To go back to a snapshot: Lightsail → **Snapshots** tab → the snapshot's menu → **Create new
  instance**, then move the static IP to the new instance (**Networking → static IP → Attach**)
  and delete the old instance.
- **Restoring only the database** (rarely needed, e.g. after a mistaken deletion; ask for help
  if unsure):

  ```bash
  sudo systemctl stop terrain-tool
  sudo cp /var/lib/terrain-tool/backups/app-YYYYMMDD.db /var/lib/terrain-tool/app.db
  sudo rm -f /var/lib/terrain-tool/app.db-wal /var/lib/terrain-tool/app.db-shm
  sudo chown terrain:terrain /var/lib/terrain-tool/app.db
  sudo systemctl start terrain-tool
  ```

  (Site files and reports from that day are not in the database backup; the snapshot has them.)

### What it costs

| Item | Monthly (US$) |
|---|---|
| Lightsail instance, 2 GB plan (includes the static IP while attached, and 1.5 TB data transfer in Malaysia) | 12.00 |
| Automatic snapshots: US$0.05 per GB-month; the first holds the used disk (about 5–8 GB), later ones only what changed | about 0.30–1.00 |
| Amazon SES: US$0.10 per 1,000 emails (attachments US$0.12 per GB; the tool sends none) | under 0.10 |
| **Total** | **about 12.50–13.50** |

Prices are AWS's list prices in November 2026, before any Malaysian service tax AWS adds to the
bill. New AWS accounts may get Free Tier credits that cover the first months. See
**Billing and Cost Management** in the AWS console for the real figures; you can set a budget
alert there (**Budgets → Create budget**, e.g. US$20).

### If something breaks

1. Run `sudo terrain-tool status` and read the lines marked **NOT**, **WRONG** or **WARNING**.
2. Run `sudo terrain-tool restart`.
3. Run `sudo terrain-tool logs` and send the last lines to whoever maintains the tool.
4. If the server itself is stuck (the browser terminal does not open): Lightsail → instance
   menu → **Reboot**. Everything starts again by itself.
5. As a last resort, restore yesterday's snapshot (see Backups).

---

## Troubleshooting

| What you see | What to do |
|---|---|
| Part B does not offer **Asia Pacific (Malaysia)** | The region is not enabled yet (Part A). Check **Account → AWS Regions**; enabling can take hours. |
| `curl: (22) The requested URL returned error: 404` after pasting the command | You used the *after merge* command before the merge, or the line was cut. Paste the *before merge* command from D2, in one piece. |
| **SETUP STOPPED: … does not contain the server kit** | Same cause: use the *before merge* command (with `TOOL_REF=claude/admiring-albattani-j1beqs`). |
| **SETUP STOPPED: It needs administrator rights** | `sudo` is missing before `bash`. Paste the command exactly as shown. |
| **SETUP FAILED during "…"** | Run the same command again (it continues safely). If it fails again, send the messages and `/var/log/terrain-tool-setup.log` to whoever maintains the tool. |
| Status **DNS: NOT SET** or **WRONG** | Check the `tools` A record in Namecheap (Part C): Host `tools`, Value = the static IP. Wait 5–30 minutes. |
| Status **HTTPS: NOT YET** although DNS is OK | Check that **HTTPS (443)** and **HTTP (80)** are in the Lightsail **IPv4 Firewall** (B3), wait 5 minutes, then `sudo terrain-tool restart`. |
| Status says HTTPS works on the server but not through the public address | Port 443 is closed in the Lightsail firewall (B3). |
| Visitors see "We couldn't send the email right now" | Run `sudo terrain-tool test-email you@…`: it says why (no keys yet → E6; sandbox → E7/E8; wrong key → E5/E6). |
| Test email works, but visitors get nothing | SES is still in the sandbox: only verified addresses receive mail (E8). Also check spam folders and Part F. |
| Emails land in spam | Do Part F (DMARC), check that SES shows DKIM **Successful**, and test with mail-tester.com. |
| **Tool: … NOT answering**, or out-of-memory messages in the logs | `sudo terrain-tool restart`. The tool may use up to 1.5 GB; the 2 GB swap file absorbs short peaks. If it keeps happening, move to the US$24 (4 GB) plan: create a snapshot, **Create new instance** from it with the bigger plan, and move the static IP. |
| Admin page asks for a password again and again | User `admin`, password from `sudo terrain-tool admin-password` (copy it exactly). |

---

## What this server stores and where (for the privacy notice)

Everything below is in **AWS Asia Pacific (Malaysia), `ap-southeast-5`**, on the Lightsail
instance `terrain-tool` and in its automatic snapshots, unless stated otherwise.

| What | Where on the server | Kept for |
|---|---|---|
| Visitors' email addresses, consent records, newsletter status, hashed sign-in links and sessions, abuse counters (hashed IP addresses) | SQLite database `/var/lib/terrain-tool/app.db` | as set in the app (see `/privacy`: unconfirmed addresses 7 days, accounts until deleted or 730 days inactive, abuse counters about 2 days) |
| Uploaded site files (KML/KMZ), results, maps, PDF and Word reports | `/var/lib/terrain-tool/jobs/` | 30 days (`RETENTION_DAYS`), or until the visitor deletes them |
| Database backups | `/var/lib/terrain-tool/backups/` | 14 days |
| Whole-server snapshots (contain all of the above) | Lightsail automatic snapshots, same region | 7 days |
| System and app logs: requests reach the app from Caddy, so visitors' IP addresses are not logged (Caddy keeps no access log); an email error can quote the recipient's address | systemd journal on the server | at most 30 days and 500 MB |
| Secrets (signing key, admin password, SES access key) | `/etc/terrain-tool/terrain-tool.env` (readable only by root and the app) | until changed |
| Outgoing emails (address, subject, message) | **Amazon SES**, same region (AWS keeps sending records according to its own terms) | per AWS |

Outside Malaysia: the visitor's browser loads fonts from Google Fonts (and Cloudflare Turnstile,
if you enable it); the server reads public elevation tiles from the Copernicus DEM bucket in
AWS `eu-central-1` (Frankfurt) by tile name only — no personal data or site coordinates are
sent. The privacy notice at `/privacy` names AWS (Lightsail and SES, Malaysia region) as the
hosting and email providers; the AWS contracting entity and data processing terms are marked
there for legal review.

---

## For the maintainer: what is in this folder

| File | Installed as |
|---|---|
| `setup.sh` | run once per install or update (`sudo terrain-tool update` runs it) |
| `terrain-tool` | `/usr/local/sbin/terrain-tool` (admin helper) |
| `terrain-tool.service` | `/etc/systemd/system/terrain-tool.service` (user `terrain`, `EnvironmentFile`, hardening, `MemoryMax=1500M`) |
| `terrain-tool.env.template` | `/etc/terrain-tool/terrain-tool.env` (root:terrain 0640), created once with fresh secrets; later runs only add missing keys |
| `Caddyfile` | `/etc/caddy/Caddyfile` with `@TOOL_DOMAIN@` replaced |
| `backup-db.py`, `terrain-tool-backup.service`, `terrain-tool-backup.timer` | `/usr/local/lib/terrain-tool/backup-db.py` and the nightly backup timer |
| `journald-terrain-tool.conf` | `/etc/systemd/journald.conf.d/terrain-tool.conf` (500 MB, 30 days) |
| `unattended-upgrades.conf` | `/etc/apt/apt.conf.d/52terrain-tool-upgrades` |

Other paths: code `/opt/terrain-tool/src` (sparse, shallow checkout of `terrain-tool/` at the ref
in `/etc/terrain-tool/ref`), Python environment `/opt/terrain-tool/venv`, data
`/var/lib/terrain-tool` (owner `terrain`, 0750), swap `/swapfile` (2 GB, `vm.swappiness=10`),
setup log `/var/log/terrain-tool-setup.log`. The app listens on `127.0.0.1:8000` only; Caddy
(Caddy's official apt repository) terminates HTTPS, replaces any client-sent `X-Forwarded-For`
(so `TRUST_PROXY_HEADERS=true`, `TRUSTED_PROXY_HOPS=1`), limits request bodies to 6 MB and adds
HSTS only where the app has not set it. `setup.sh` first downloads the requested ref, then
re-runs the `setup.sh` from that download, so an update always runs the matching steps.
Settings for testing only: `TOOL_REPO` (another git URL or path) and `TT_OS_RELEASE`.
`tests/test_deploy_kit.py` checks these files.
