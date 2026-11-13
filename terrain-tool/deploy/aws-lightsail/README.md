# Put the terrain screening tool online — Amazon Lightsail in Malaysia

This guide takes you from nothing to the tool running at **https://tools.ecoconsultancy.services**
on a small Amazon Web Services (AWS) server in the **Asia Pacific (Malaysia)** region, with
sign-in emails sent by **Amazon SES** in the same region. No programming is needed: you click
through the AWS and Namecheap websites, and paste **one command** into a browser window.

| | |
|---|---|
| **Time** | about 1 hour of clicking, plus waiting (region: minutes to hours; DNS: usually under 30 minutes; SES production access: up to about 4 days) |
| **Cost** | about **US$13.50–14.60 a month** including 8% service tax (details in [Part H](#what-it-costs)) |
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

1. Create the account on AWS's full sign-up page:
   **<https://signin.aws.amazon.com/signup?request_type=register>** (AWS calls it *Sign up for AWS
   (advanced)*). Do **not** use the **Create account** or **Sign up** buttons on aws.amazon.com,
   and do not sign up with Google, GitHub or Apple: those create a simplified account that AWS
   ties to one region chosen for you, and it **cannot use the Malaysia region**.
   - **Root user email address:** `contact@ecoconsultancy.services` (a company mailbox you will
     keep). **AWS account name:** `EcoEnergy Consultancy`. Use a company phone number.
   - **Choose your account plan:** **Paid account plan**. New accounts still get AWS's sign-up
     credits. A *Free plan* account is suspended when its free period ends (at most 6 months),
     and the tool would go offline.
   - **Support plan:** **Basic support – Free**.
   - The first time you sign in, AWS asks you to add multi-factor authentication (MFA) for the
     root user: add a passkey or an authenticator app.

   If you already have an AWS account that you manage in **AWS Settings** (settings.aws.com) or
   sign in to with Google, GitHub or Apple, it cannot use Malaysia as it is: follow
   [A2](#a2-if-your-account-uses-aws-settings-the-new-simplified-experience) first.
2. Sign in to the **AWS Management Console** (<https://console.aws.amazon.com>) as **Root user**,
   with the email and password from step 1.
3. Click your **account name** at the top right, then **Account**.
4. Scroll down to the section **AWS Regions**. Find **Asia Pacific (Malaysia)**
   (code `ap-southeast-5`). If its status is **Enabled**, go to step 7.
5. Select it, click **Enable**, read the message and click **Enable region**.
6. Wait until the status is **Enabled**. This usually takes a few minutes but can take several
   hours. You cannot use the region before then (Part B will not offer it).
7. Check that Lightsail sees it too: open <https://lightsail.aws.amazon.com>, click your account
   name at the top right → **Account** → **Profile** tab → **Supported opt-in Regions**. The
   Malaysia region must show **Opt-in status: Enabled** (if it shows **Start opt-in**, click it
   and follow the steps; it leads to the same **Enable** button as step 5).

### A2. If your account uses AWS Settings (the new simplified experience)

You can tell: the console's settings page is **AWS Settings** with only **Projects, Team,
Billing and Support**, the home page shows your Free plan days and credits, **Account → AWS
Regions** says *Page Not Found*, and Lightsail has no **Change AWS Region** link.

Accounts made with AWS's new sign-up (launched September 2026) are tied to one region chosen
from the contact-address country — **Malaysia addresses get Asia Pacific (Sydney)** — and
"cannot modify" it or use opt-in regions such as Malaysia
([AWS: Sign up for AWS](https://docs.aws.amazon.com/accounts/latest/reference/sign-up-for-aws.html),
[AWS: project Regions](https://docs.aws.amazon.com/accounts/latest/reference/project-regions.html)).
To reach Malaysia on such an account, all of the following are needed, in this order. **Steps 1
and 2 cannot be undone.**

1. **Upgrade to the Paid plan:** AWS Settings → **Billing** → **Upgrade** → **Get started**, add
   the company card, **Upgrade account**
   ([AWS](https://docs.aws.amazon.com/accounts/latest/reference/upgrade-account.html)). Credits you
   already have keep paying your bills until they expire; you pay only what the credits do not
   cover; the account no longer closes when the free period ends. (A commercial tool needs the
   Paid plan anyway: a Free plan account is suspended after 6 months and its data deleted 90 days
   later — [AWS Free Tier FAQ](https://aws.amazon.com/free/free-tier-faqs/).)
2. **Activate advanced features:** AWS Settings → **Projects** → **Actions** → **Explore advanced
   features** (or the **Activate advanced features** button) → enter a team name, choose and
   verify the management-account email (`contact@ecoconsultancy.services`) → **Review and
   complete activation** → **Activate**
   ([AWS](https://docs.aws.amazon.com/accounts/latest/reference/activate-advanced-features.html)).
   It is free and changes nothing that is already running, but: spend limits are removed and
   cannot be set again (use a Budget alert instead, Part H), and you can no longer earn the extra
   activity credits.
3. **Allow the Malaysia region in the organization policy:** AWS Settings → **Projects** →
   **Manage this organization** → **Manage policies** (opens AWS Organizations) → **Service control
   policies** → the AWS-managed project policy → **Edit policy**. In the statement with
   `"Sid": "RegionFloor"`, add `"ap-southeast-5"` to the list of allowed regions next to the
   existing ones, then **Save changes**
   ([AWS](https://docs.aws.amazon.com/accounts/latest/reference/scps-and-rcps-for-projects.html)).
   If unsure, take a screenshot of the policy before changing it.
4. **Enable the Malaysia region:** in the console's account menu → **Account** → **AWS Regions** →
   **Asia Pacific (Malaysia)** → **Enable** (steps 3–7 of Part A), or in AWS Organizations →
   **AWS accounts** → your project account → **Regions** → **Enable**.

A Lightsail server already created in Sydney while the account was simplified is not moved by
this: create the new one in Malaysia (Part B), then delete the Sydney instance **and** its static
IP (both keep costing money until deleted).

---

## Part B — Create the server in Lightsail

### B1. The server

1. Open the Lightsail console: <https://lightsail.aws.amazon.com>.
2. Click **Create instance**.
3. Under **Instance location**, click **Change AWS Region and Availability Zone** and choose the
   Malaysia region. Lightsail may label it **Malaysia** or **Kuala Lumpur**; the code is always
   `ap-southeast-5`. Leave the Availability Zone as it is.
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
4. Leave the **IPv6 Firewall** section as it is: do **not** add HTTPS there. The address
   `tools.ecoconsultancy.services` has only an IPv4 (A) record, so visitors never use IPv6, and
   an open IPv6 HTTPS port would only help someone get round the tool's per-address limits.

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
   click the orange **Paste into terminal** button at the bottom right of the terminal window (if
   the browser asks whether the page may see your clipboard, allow it). The command appears;
   press **Enter**. To copy text *out of* the terminal, select it with the mouse and click
   **Copy from terminal**.

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
the Caddy web server (HTTPS), starting the tool. **It takes about 3–8 minutes.** Leave the
window open while it runs. If the window closes anyway or the connection drops, the setup keeps
running on the server: open a new window (D1), watch it finish with
`sudo tail -f /var/log/terrain-tool-setup.log` (Ctrl+C stops watching; the setup carries on), then
run `sudo terrain-tool status`.

At the end you get a **summary**:

- what was set up;
- a **status** block: whether the tool answers, whether `tools.ecoconsultancy.services` points
  to this server (**DNS: OK**) and whether HTTPS works (**HTTPS: OK**);
- **ADMIN PAGES**: the address of the admin pages. Their user name (`admin`) and random
  password are not printed there, because everything on the screen is also saved in the setup
  log, which you may send to someone for help. Run
  `sudo terrain-tool admin-password` to show them and **copy the password into your password
  manager now**: select it with the mouse and click **Copy from terminal** at the bottom right of
  the terminal window. You can show it again at any time with the same command.

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
   RSA_2048_BIT**, and make sure **DKIM signatures** is **Enabled**. If **Publish DNS records to
   Route53** is shown, untick **Enabled**: your DNS is at Namecheap, and you add the records
   yourself in E2.
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
- **Value / Target:** the **Value** from SES, copied exactly, e.g.
  `abcd1234efgh.dkim.ap-southeast-5.amazonses.com` (in the Malaysia region every value ends in
  `.dkim.ap-southeast-5.amazonses.com`)
- **TTL:** `Automatic`, then the **green tick** (✓).

Do not change the existing MX or SPF (`v=spf1 include:spf.privateemail.com ~all`) records: SES
does not need SPF changes, because DKIM signs its mail for `ecoconsultancy.services`.

### E3. Wait for "Verified"

Back in SES (**Configuration → Identities**), refresh after 10–30 minutes. The domain should
show **Identity status: Verified** and **DKIM configuration: Successful**. (It can take up to
72 hours. If it does not verify, check that the Host fields have no extra
`.ecoconsultancy.services` and that each Value ends in `.dkim.ap-southeast-5.amazonses.com`.)

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

It asks two questions. **Nothing appears on the screen while you paste either answer** — that is
normal: it keeps the secret off the screen and out of screenshots.

1. In AWS, click the copy icon next to the **Access key** (it starts with `AKIA`). In the
   terminal, click **Paste into terminal** and press **Enter**. The tool shows the start and the
   end of the key with **OK**.
2. In AWS, click the copy icon next to the **Secret access key**. Copy again even if you think
   you already did: the clipboard holds one value at a time. Paste it the same way and press
   **Enter**.

If the wrong one arrives (the secret in the first question, or the access key again in the
second), the tool says so without showing it and asks again, up to three times; nothing is saved
until both are right. It then restarts the tool and says **Done**. You can now click **Done** on
the AWS page.

> **If a secret access key is ever shown on a screen, in a screenshot or in a chat, treat it as
> exposed.** In IAM, open **terrain-tool-ses → Security credentials**, create a new access key
> (E5) and put it on the server (E6); then select the old key and choose **Actions → Deactivate**,
> then **Actions → Delete**. The test email (E7) confirms the new key works.

### E7. Send yourself a test email (SES "sandbox")

New SES accounts start in the **sandbox**: they can send **only to addresses and domains you
have verified in SES**, at most **200 emails a day** and **1 per second**. While in the sandbox,
real visitors cannot get their sign-in emails — that is why E9 matters.

1. Addresses ending in `@ecoconsultancy.services` can receive the test as soon as E3 shows
   **Verified**, so go straight to step 2. To test an outside address (e.g. Gmail) while still in
   the sandbox, verify it first: in SES (**Malaysia**) choose **Configuration → Identities →
   Create identity → Email address**, type the address, choose **Create identity**, then click
   the link in the email from AWS.
2. In the terminal:

   ```bash
   sudo terrain-tool test-email contact@ecoconsultancy.services
   ```

   - **Sent. Check the inbox…** — look in the inbox (and the spam folder).
   - **FAILED: …** — the message says what is wrong in plain words, e.g. *SES is in the sandbox
     and this address is not verified*, *AWS does not recognise the access key ID*, or *the IAM
     user is not allowed to send this email*. Fix it and run the test again.

### E8. Turn on the human check (Cloudflare Turnstile)

Do this **before** E9. Once AWS lets the account send to anyone, the sign-up form could be used by
a program to send sign-in emails to many strangers; the bounces and complaints that follow can
get the SES account paused, and with it all of the tool's email. Cloudflare Turnstile (free) adds
a quick check, usually invisible, that a person is filling in the form.

1. Sign up or sign in at <https://dash.cloudflare.com> (a free account is enough; your domain
   does **not** move to Cloudflare).
2. Open **Turnstile** in the left menu and click **Add widget**.
3. **Widget name:** `terrain-tool`. Under hostnames, add `tools.ecoconsultancy.services`.
   **Widget mode:** **Managed**. Leave the other options as they are and click **Create**.
4. The page shows a **Site Key** and a **Secret Key**. In the Lightsail terminal run:

   ```bash
   sudo terrain-tool set-turnstile-keys
   ```

   copy the **Site Key**, click **Paste into terminal** and press Enter; then copy the **Secret
   Key** (copy again: the clipboard holds one value at a time), paste it and press Enter. Nothing
   appears while you paste either key. The tool restarts and says **Done**.
5. Open `https://tools.ecoconsultancy.services` in a private browser window: the form now shows
   the Cloudflare check. Ask for a sign-in link with an `@ecoconsultancy.services` address to be
   sure it still works.

With the check on, the visitor's browser contacts Cloudflare (outside Malaysia). The privacy
notice then names Cloudflare by itself; the legal review covers this transfer
([`terrain-tool/README.md`](../../README.md#privacy-pdpa-design)).

### E9. Ask AWS for production access (leave the sandbox)

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
   > that are never confirmed are deleted after 7 days, and the form is protected by a
   > Cloudflare Turnstile human check and rate-limited per address and per IP. Newsletter
   > consent is a separate, unticked box and is confirmed by the emailed link; we do not send
   > newsletters through this account, and every newsletter we send elsewhere carries a
   > one-click unsubscribe. Each email names the sender, links our privacy notice and account
   > page, and has Reply-To contact@ecoconsultancy.services, which we read. We expect about
   > 50–300 emails a month (well under 1,000). SES's account-level suppression list, which is
   > on for our account, stops sending to any address that hard-bounces or complains, and we
   > check the bounce and complaint rates on the SES account dashboard every week.

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
3. **First check whether it is already there** (on BasicDNS, Namecheap often adds it by
   itself): **Domain List → Manage → Advanced DNS**. Look under **HOST RECORDS** (and **MAIL
   SETTINGS**) for a **TXT Record** whose host is `default._domainkey` or
   `privateemail._domainkey`. If it is there and its value matches what **Show DKIM** displays,
   do nothing and go to F2 (two records for the same host can make DKIM checks fail). Only if it
   is missing: **ADD NEW RECORD**, **Type:** `TXT Record`, **Host:** the host that Show DKIM gives
   (e.g. `privateemail._domainkey`), **Value:** the whole `v=DKIM1; k=rsa; p=…` text (without
   quotes), **TTL:** `Automatic`, then the green tick.

### F2. DMARC

Add one more record: **Type:** `TXT Record`, **Host:** `_dmarc`, **TTL:** `Automatic`,
**Value:**

```
v=DMARC1; p=none; rua=mailto:contact@ecoconsultancy.services; fo=1
```

`p=none` only reports, it blocks nothing: Google, Microsoft and others then email daily
summaries (XML attachments) to `contact@ecoconsultancy.services`. After 2–4 weeks in which those
reports show your own mail passing, change `p=none` to `p=quarantine` (failing mail goes to
spam). After AWS has approved production access (E9), check the whole setup with a free tester
such as <https://www.mail-tester.com>: run `sudo terrain-tool test-email <the address it gives
you>` and read the score. (While SES is still in the sandbox this test fails, because that
address is not verified.)

---

## Part G — Go live

1. `sudo terrain-tool status` shows **Tool: active, answering**, **DNS: OK**, **HTTPS: OK**, an
   **Email** line with your key and **Human check: on**.
2. Open **https://tools.ecoconsultancy.services**, sign up with an `@ecoconsultancy.services`
   address, open the email, press **Continue**, and upload the sample file
   `hilly_site_pahang.kml`. Download it first: right-click
   <https://raw.githubusercontent.com/nurhilmy-ops/ecoenergy-website/claude/admiring-albattani-j1beqs/terrain-tool/tests/fixtures/hilly_site_pahang.kml>
   → **Save link as…** (after the merge, replace `claude/admiring-albattani-j1beqs` with
   `main`). Then check the result page, the PDF and the Word file.
3. Open **https://tools.ecoconsultancy.services/admin**, sign in as `admin` with the password
   (`sudo terrain-tool admin-password`) and find your own test screening under **Leads**.
4. **Wait for SES production access (E9).** Run `sudo terrain-tool test-email someone@gmail.com`
   with an address you have **not** verified in SES. It must say **Sent** and the email must
   arrive. Until then every real visitor sees "We couldn't send the email right now", so do not
   merge or announce yet.
5. **Merge the pull request** on GitHub: open
   <https://github.com/nurhilmy-ops/ecoenergy-website/pull/11>, click **Ready for review** (it is
   still a draft), then **Merge pull request** and **Confirm merge**. This also publishes the
   links to the tool on the main website (GitHub Pages updates within a few minutes).
6. Straight away, switch the server to `main`, so later updates come from there:

   ```bash
   sudo terrain-tool update --ref main
   ```

   From now on `sudo terrain-tool update` (without `--ref`) keeps following `main`. (Until you
   do this, `sudo terrain-tool status` shows a **WARNING** that the server follows a working
   branch.)
7. **Protect what the server installs.** `sudo terrain-tool update` installs whatever is on
   `main` on GitHub and runs its setup as administrator, so anyone who can push to `main` can
   change what runs on this server. Keep two-factor authentication on for every GitHub account
   with write access to the repository (GitHub → **Settings** → **Password and
   authentication**), give write access only to people you trust, and ask your maintainer to
   turn on branch protection for `main` (changes only through reviewed pull requests).
8. Before announcing the tool, work through the **Before going live** list in
   [`terrain-tool/README.md`](../../README.md#before-going-live) (privacy notice legal review,
   monitoring).

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
| `sudo terrain-tool set-turnstile-keys` | Enters (or replaces) the Cloudflare Turnstile keys (E8) |
| `sudo terrain-tool test-email ADDRESS` | Sends a test email with the real settings |
| `sudo terrain-tool withdraw EMAIL --followup --newsletter --note "Email of 12 Oct 2026"` | Records a withdrawal of consent or an objection to marketing that arrived in writing (PDPA s.38 / s.43): staff follow-up ends for all of that person's reports (`--followup`) and/or the newsletter is unsubscribed (`--newsletter`); the note goes into the consent records |
| `sudo terrain-tool backup-now` | Backs up the database now |

### Updates

- **Ubuntu security updates and Caddy updates install themselves** every day. When one needs a
  restart (for example a new Linux kernel), the server restarts by itself at **04:00 Malaysia
  time**; the tool is back within about a minute.
- **The tool and its Python libraries** are updated **only** when you run
  `sudo terrain-tool update` (for example after a change has been merged on GitHub). The
  libraries are fixed to the versions tested with each release (the kit's `constraints.txt`),
  so they get security fixes only when a maintainer updates that file and you then run the
  update: ask your maintainer to do this about once a month. The update keeps your settings,
  secrets, data and backups. The tool is offline for the few minutes it takes; if something
  goes wrong, the previous version is put back and started again by itself, and the message
  says so.
- **Changing a setting** (for example `RETENTION_DAYS`, or Cloudflare Turnstile keys): run
  `sudo nano /etc/terrain-tool/terrain-tool.env`, change the line, save with Ctrl+O, Enter,
  Ctrl+X, then `sudo terrain-tool restart`. Every setting is explained in
  [`terrain-tool/README.md`](../../README.md#configuration).

### Backups

- **Database, every night at about 02:30 Malaysia time**: a consistent copy of the SQLite
  database in `/var/lib/terrain-tool/backups/app-YYYYMMDD.db`. The newest **14** are kept.
- **Whole server, every night (Lightsail automatic snapshots, B4)**: the newest **7** are kept.
  Each snapshot also holds that night's database copies, so data deleted in the tool stays in
  the backups for up to about **3 weeks** (database records: 14 days of copies plus 7 days of
  snapshots) and site files and reports for up to **7 days**. The privacy notice says so.
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
| Malaysian service tax (SST), 8% | about 1.00–1.10 |
| **Total** | **about 13.50–14.60** |

Prices are AWS's list prices in November 2026; AWS Malaysia adds 8% service tax (SST) to the
bill. New AWS accounts get sign-up credits that cover the first months. See
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
| Part B does not offer the Malaysia region (`ap-southeast-5`) | The region is not enabled yet (Part A), or the account was made with the simplified sign-up (Part A step 1). In Lightsail open your account menu → **Account** → **Profile** → **Supported opt-in Regions**: Malaysia must show **Enabled**. Enabling can take hours. |
| `curl: (22) The requested URL returned error: 404` after pasting the command | You used the *after merge* command before the merge, or the line was cut. Paste the *before merge* command from D2, in one piece. |
| **SETUP STOPPED: … does not contain the server kit** | Same cause: use the *before merge* command (with `TOOL_REF=claude/admiring-albattani-j1beqs`). |
| **SETUP STOPPED: It needs administrator rights** | `sudo` is missing before `bash`. Paste the command exactly as shown. |
| **SETUP FAILED during "…"** | Run the same command again (it continues safely). If it fails again, send the messages and `/var/log/terrain-tool-setup.log` to whoever maintains the tool. |
| An update failed and says **Putting back the previous version** | Nothing to do: the version that worked before runs again (check with `sudo terrain-tool status`). Send the messages to whoever maintains the tool. |
| The browser window closed while the setup was running | It keeps running. Open a new window (D1) and run `sudo tail -f /var/log/terrain-tool-setup.log` to watch it finish (Ctrl+C stops watching), then `sudo terrain-tool status`. If it had stopped, run the setup command again. |
| Status **DNS: NOT SET** or **WRONG** | Check the `tools` A record in Namecheap (Part C): Host `tools`, Value = the static IP. Wait 5–30 minutes. |
| Status **HTTPS: NOT YET** although DNS is OK | Check that **HTTPS (443)** and **HTTP (80)** are in the Lightsail **IPv4 Firewall** (B3), wait 5 minutes, then `sudo terrain-tool restart`. |
| Status says HTTPS works on the server but not through the public address | Port 443 is closed in the Lightsail firewall (B3). |
| Visitors see "We couldn't send the email right now" | Run `sudo terrain-tool test-email you@…`: it says why (no keys yet → E6; sandbox → E7/E9; wrong key → E5/E6). |
| Test email works, but visitors get nothing | SES is still in the sandbox: only verified addresses and domains receive mail (E9). Also check spam folders and Part F. |
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
| Database backups | `/var/lib/terrain-tool/backups/` | 14 days (and inside the snapshots below for 7 more days: deleted database records up to about 3 weeks in all) |
| Whole-server snapshots (contain all of the above) | Lightsail automatic snapshots, same region | 7 days (deleted site files and reports up to 7 days) |
| System and app logs: requests reach the app from Caddy, so visitors' IP addresses are not logged (Caddy keeps no access log); an email error can quote the recipient's address | systemd journal on the server (not passed on to `/var/log/syslog`) | at most about 30 days and 500 MB |
| Secrets (signing key, admin password, SES access key) | `/etc/terrain-tool/terrain-tool.env` (readable only by root and the app) | until changed |
| Outgoing emails (address, subject, message) | **Amazon SES**, same region (AWS keeps sending records according to its own terms) | per AWS |

Outside Malaysia: the visitor's browser loads fonts from Google Fonts and, once it is turned on
(E8), the Cloudflare Turnstile check; the server reads public elevation tiles from the Copernicus
DEM bucket in AWS `eu-central-1` (Frankfurt). It requests the tile by name and only the parts of
that tile file that cover the site's general area (a block of roughly 30 km). No personal data,
file contents or exact site coordinates are sent. The privacy notice at `/privacy` names AWS
(Lightsail and SES, Malaysia region) as the hosting and email providers; the AWS contracting
entity and data processing terms are marked there for legal review.

---

## For the maintainer: what is in this folder

| File | Installed as |
|---|---|
| `setup.sh` | run once per install or update (`sudo terrain-tool update` runs it) |
| `constraints.txt` | not installed: pins every Python library (and its dependencies) that `setup.sh` installs into `/opt/terrain-tool/venv` |
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
setup log `/var/log/terrain-tool-setup.log` (0600: everything the setup printed, plus apt's
output; never the admin password). The app listens on `127.0.0.1:8000` only; Caddy (Caddy's
official apt repository, updated by unattended-upgrades) terminates HTTPS, replaces any
client-sent `X-Forwarded-For` (so `TRUST_PROXY_HEADERS=true`, `TRUSTED_PROXY_HOPS=1`), limits
request bodies to 6 MB, adds HSTS only where the app has not set it, and has its admin API on
the socket `/var/lib/caddy/admin.sock` (not `localhost:2019`, which the app's user could reach).
`setup.sh` first downloads the requested ref, then re-runs the `setup.sh` from that download, so
an update always runs the matching steps. When the commit changes it stops the tool first and
records the running commit in `/etc/terrain-tool/previous-version` (and the git ref
`refs/terrain-tool/previous`); if the update then fails, it checks that commit out again,
reinstalls its pinned libraries and service file, and starts it. It ignores SIGHUP, so a closed
browser terminal does not stop it.

**Refreshing `constraints.txt`** (about monthly, and whenever `requirements.txt` changes): on a
fresh Ubuntu 24.04 machine or container, in the `terrain-tool` folder, run
`python3 -m venv /tmp/v && /tmp/v/bin/pip install --upgrade -r requirements.txt boto3 &&
/tmp/v/bin/pip freeze`, replace the version lines of `deploy/aws-lightsail/constraints.txt` with
that output (keep its comment lines and update their date), run the test suite (and ideally one
screening on a test server), commit, and then run `sudo terrain-tool update` on the server.
Settings for testing only: `TOOL_REPO` (another git URL or path) and `TT_OS_RELEASE`.
`tests/test_deploy_kit.py` checks these files.
