"""End-to-end visitor flow: landing → link → confirm → upload → job → report → delete."""
from __future__ import annotations

import json
import re

from app import jobs
from app.db import db


def test_landing_defaults_and_attribution(client, settings):
    resp = client.get("/?utm_source=linkedin&utm_medium=social&utm_campaign=lss6<script>",
                      headers={"Referer": "https://www.linkedin.com/feed/update/urn:li:activity:123?x=y"})
    assert resp.status_code == 200
    html = resp.text
    # Newsletter box present, optional, and NOT pre-ticked.
    assert 'name="newsletter"' in html
    newsletter_input = html[html.index('id="newsletter"'):].split(">", 1)[0]
    assert "checked" not in newsletter_input
    assert "Also send me EcoEnergy&#39;s solar policy and scheme insights by email (optional). Unsubscribe any time." in html
    # Bilingual notice line linking to /privacy. Staff follow-up is NOT asked for here: the
    # notice says it is a separate choice on the upload page, and there is no box for it.
    assert 'href="/privacy"' in html and "E-mel anda diperlukan" in html
    assert "Whether EcoEnergy may contact you about your site is your choice, on the upload page." in html
    assert "adalah pilihan anda, di halaman muat naik" in html
    assert 'name="followup"' not in html and "may follow up" not in html
    # Age: business users aged 18 and above (PDP Regulations 2013 reg 3(3)).
    assert "For business users aged 18 and above." in html
    assert "Untuk pengguna perniagaan berumur 18 tahun ke atas." in html
    # UTM hidden fields (sanitised) and referrer origin only.
    assert 'name="utm_source" value="linkedin"' in html
    assert 'name="utm_campaign" value="lss6script"' in html
    assert 'name="ref" value="https://www.linkedin.com"' in html
    assert "urn:li" not in html
    # What you get / what it is not.
    assert "KPKT slope classification map" in html and "not a topographic or land survey" in html
    # No Turnstile unless configured.
    assert "challenges.cloudflare.com" not in html


def test_happy_path_end_to_end(flow, settings, query, fake_engine):
    email = "Developer@Example.COM"
    resp = flow.request_link(email, utm_source="linkedin", utm_medium="social", utm_campaign="lss6",
                             ref="https://www.linkedin.com")
    assert resp.status_code == 200
    assert "Check your inbox" in resp.text
    assert "/dev/outbox" in resp.text                     # dev-only shortcut

    sub = query("SELECT * FROM subscribers")[0]
    assert sub["email"] == "developer@example.com"
    assert (sub["utm_source"], sub["utm_medium"], sub["utm_campaign"]) == ("linkedin", "social", "lss6")
    assert sub["referrer"] == "https://www.linkedin.com"
    assert sub["verified_at"] is None and sub["newsletter_status"] == "none"

    mail = flow.mails("developer@example.com")[-1]
    assert mail["subject"] == "Your terrain screening link"
    assert "valid for 72 hours, up to 5 uses" in mail["text_body"]
    assert "If you didn't request this, ignore this email" in mail["text_body"]
    assert "http://testserver/privacy" in mail["text_body"] and "http://testserver/account" in mail["text_body"]
    assert "List-Unsubscribe" not in mail["headers_json"]          # transactional
    assert mail["html_body"] and "Open my screening link" in mail["html_body"]
    token = flow.token_from(mail)
    # Raw tokens are never stored.
    assert not query("SELECT * FROM tokens WHERE token_hash = ?", (token,))

    # GET /start is safe for link scanners: it never consumes a use.
    for _ in range(3):
        page = flow.client.get(f"/start?t={token}")
        assert page.status_code == 200 and "Continue to upload your site" in page.text
    assert query("SELECT uses_left FROM tokens")[0]["uses_left"] == settings.token_max_uses

    resp = flow.confirm(token)
    assert resp.status_code == 303 and resp.headers["location"] == "/upload"
    cookie = resp.headers["set-cookie"]
    assert "tt_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie.replace("Lax", "lax")
    assert query("SELECT uses_left FROM tokens")[0]["uses_left"] == settings.token_max_uses - 1
    assert query("SELECT verified_at FROM subscribers")[0]["verified_at"] is not None

    page = flow.client.get("/upload")
    assert page.status_code == 200
    assert 'accept=".kml,.kmz' in page.text
    # Staff follow-up: its own optional box on the upload page, unticked by default.
    followup_input = page.text[page.text.index('id="followup"'):].split(">", 1)[0]
    assert 'name="followup"' in followup_input and "checked" not in followup_input
    assert "EcoEnergy staff may email me about this site (optional)." in page.text
    assert "Kakitangan EcoEnergy boleh menghubungi saya melalui e-mel berkenaan tapak ini (pilihan)." in page.text
    assert "You have <strong>3</strong> screening runs left today" in page.text
    assert "deleted automatically after 30 days, or immediately when you press Delete" in page.text
    for scheme in ("Large Scale Solar (LSS)", "CRESS", "Floating solar (FPV)", "Rooftop / self-consumption"):
        assert scheme in page.text
    for stage in ("Exploring options", "Land secured / under negotiation", "Preparing a bid or submission"):
        assert stage in page.text

    job_id = flow.upload_job(site_label="Kuala Langat parcel B", scheme="lss", stage="bidding",
                             notes="Bidding in LSS6")
    job = query("SELECT * FROM jobs WHERE id = ?", (job_id,))[0]
    assert job["status"] == "queued" and job["scheme"] == "lss" and job["stage"] == "bidding"
    assert job["followup_consent"] == 0                      # box left unticked
    assert query("SELECT * FROM consents WHERE purpose = 'site_followup'") == []
    assert job["input_filename"] == "site.kml" and len(job["input_sha256"]) == 64
    assert (settings.jobs_dir / job_id / "input.kml").read_bytes() == flow.sample_kml

    status_page = flow.client.get(f"/reports/{job_id}")
    assert status_page.status_code == 200
    assert 'aria-live="polite"' in status_page.text and "/static/js/status.js" in status_page.text
    assert flow.client.get(f"/api/reports/{job_id}/status").json() == {"status": "queued", "error": None}

    assert jobs.run_once(settings) is True
    assert jobs.run_once(settings) is False
    assert flow.client.get(f"/api/reports/{job_id}/status").json()["status"] == "done"
    assert fake_engine.run_calls[0]["report_id"] == job_id
    assert fake_engine.run_calls[0]["site_label"] == "Kuala Langat parcel B"

    job = query("SELECT * FROM jobs WHERE id = ?", (job_id,))[0]
    assert job["total_area_ha"] == 123.4 and job["state"] == "Selangor" and job["district"] == "Kuala Langat"
    assert job["kpkt_class1_pct"] == 96.5 and job["centroid_lat"] == 2.905

    # Report-ready email carries a fresh magic link that lands on the report.
    ready = flow.mails("developer@example.com")[-1]
    assert ready["subject"] == "Your terrain screening report is ready"
    ready_token = flow.token_from(ready)
    assert query("SELECT next_path FROM tokens WHERE next_path IS NOT NULL")[0]["next_path"] == f"/reports/{job_id}"
    resp = flow.confirm(ready_token)
    assert resp.status_code == 303 and resp.headers["location"] == f"/reports/{job_id}"

    page = flow.client.get(f"/reports/{job_id}")
    assert page.status_code == 200
    html = page.text
    assert "Kuala Langat parcel B" in html and "Selangor" in html and "Copernicus DEM GLO-30" in html
    assert "At a glance" in html and "123.4" in html and "96" in html and "17.6" in html
    for fig in ("1_site_layout.png", "2_elevation.png", "3_slope_classes.png", "4_profiles.png"):
        assert f"/reports/{job_id}/files/{fig}" in html
    assert "Caption for 3_slope_classes.png" in html
    assert "flag-warning" in html and "flag-caution" in html
    assert "Cable route" in html and "Topographic survey" in html and "Desktop screening only" in html
    assert "Fake DEM attribution" in html and "Fake boundaries" in html
    assert "utm_source=terrain_tool&amp;utm_medium=report" in html
    assert "Delete this report now" in html
    assert 'id="followup"' in html and "Not allowed." in html
    assert "Allow EcoEnergy staff to email me about this site." in html

    img = flow.client.get(f"/reports/{job_id}/files/2_elevation.png")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert img.content.startswith(b"\x89PNG") and "private" in img.headers["cache-control"]

    pdf = flow.client.get(f"/reports/{job_id}/download.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-disposition"].startswith("attachment")
    assert f"terrain-screening-{job_id[:8]}.pdf" in pdf.headers["content-disposition"]
    docx = flow.client.get(f"/reports/{job_id}/download.docx")
    assert docx.status_code == 200 and f"terrain-screening-{job_id[:8]}.docx" in docx.headers["content-disposition"]

    listing = flow.client.get("/reports")
    assert listing.status_code == 200 and job_id in listing.text and "123.4 ha" in listing.text

    # Delete now: files gone, derived fields cleared, report no longer reachable.
    csrf = flow.hidden(page.text, "csrf")
    resp = flow.client.post(f"/reports/{job_id}/delete", data={"csrf": csrf}, follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/reports?m=deleted"
    assert not (settings.jobs_dir / job_id).exists()
    job = query("SELECT * FROM jobs WHERE id = ?", (job_id,))[0]
    assert job["status"] == "deleted"
    for field in ("site_label", "notes", "input_filename", "input_sha256", "total_area_ha", "state",
                  "district", "centroid_lat", "centroid_lon", "kpkt_class1_pct"):
        assert job[field] is None, field
    assert flow.client.get(f"/reports/{job_id}").status_code == 404
    assert flow.client.get(f"/reports/{job_id}/download.pdf").status_code == 404
    assert "have been deleted" in flow.client.get("/reports?m=deleted").text


def test_newsletter_unticked_records_no_newsletter_consent(flow, query, settings):
    flow.login("plain@example.com")
    sub = query("SELECT * FROM subscribers")[0]
    assert sub["newsletter_status"] == "none"
    consents = query("SELECT purpose, action, notice_version, job_id FROM consents ORDER BY id")
    # Only the service itself: no bundled follow-up grant from the email form any more.
    assert [(c["purpose"], c["action"]) for c in consents] == [("service", "granted"), ("service", "confirmed")]
    assert all(c["notice_version"] == settings.notice_version for c in consents)
    assert all(c["job_id"] is None for c in consents)


def test_newsletter_double_opt_in(flow, query, settings):
    flow.request_link("keen@example.com", newsletter=True)
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "pending"
    granted = query("SELECT * FROM consents WHERE purpose = 'newsletter'")
    assert len(granted) == 1 and granted[0]["action"] == "granted"
    assert granted[0]["wording"].startswith("Also send me EcoEnergy's solar policy and scheme insights")
    assert granted[0]["notice_version"] == settings.notice_version
    assert granted[0]["ip"] and granted[0]["user_agent"]

    # Opening the link page alone does not subscribe anyone.
    flow.client.get(f"/start?t={flow.latest_token('keen@example.com')}")
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "pending"

    flow.confirm(flow.latest_token("keen@example.com"))
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "subscribed"
    actions = [(c["purpose"], c["action"]) for c in query("SELECT * FROM consents ORDER BY id")]
    assert actions.count(("newsletter", "confirmed")) == 1
    assert ("service", "confirmed") in actions
    assert not [a for a in actions if a[0] == "site_followup"]
    confirmed = query("SELECT * FROM consents WHERE purpose='newsletter' AND action='confirmed'")[0]
    assert confirmed["wording"] == granted[0]["wording"]


def test_consent_wording_matches_what_was_shown(client, flow, query):
    page = client.get("/").text
    flow.request_link("words@example.com", newsletter=True)
    for c in query("SELECT wording FROM consents"):
        en, bm = c["wording"].split(" / ")
        assert en.replace("'", "&#39;") in page and bm in page

    # The follow-up box on the upload page, and the change buttons on the result page.
    flow.confirm(flow.latest_token("words@example.com"))
    upload_page = flow.client.get("/upload").text
    job_id = flow.upload_job(followup="yes")
    granted = query("SELECT wording FROM consents WHERE purpose = 'site_followup'")
    assert len(granted) == 1
    en, bm = granted[0]["wording"].split(" / ")
    assert en in upload_page and bm in upload_page
    assert jobs.run_once(flow.settings) is True
    result_page = flow.client.get(f"/reports/{job_id}").text
    flow.client.post(f"/reports/{job_id}/followup",
                     data={"csrf": flow.hidden(result_page, "csrf"), "action": "withdraw"})
    withdrawn = query("SELECT wording FROM consents WHERE purpose = 'site_followup' AND action = 'withdrawn'")
    en, bm = withdrawn[0]["wording"].split(" / ")
    assert en in result_page and bm in result_page



def test_returning_user_keeps_first_touch_utm(flow, query):
    flow.request_link("again@example.com", utm_source="linkedin")
    flow.request_link("again@example.com", utm_source="threads")
    subs = query("SELECT * FROM subscribers")
    assert len(subs) == 1 and subs[0]["utm_source"] == "linkedin"
    assert len(query("SELECT * FROM tokens")) == 2


def test_upload_requires_session(client):
    resp = client.get("/upload", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/?m=login"
    assert "request a fresh link" in client.get("/?m=login").text
    assert client.get("/reports", follow_redirects=False).status_code == 303
    assert client.get("/account", follow_redirects=False).status_code == 303


def test_upload_validation_error_rerenders_form(flow, query, settings):
    flow.login("v@example.com")
    resp = flow.upload(content=b"not a kml at all", filename="site.kml", site_label="Keep me", notes="hello")
    assert resp.status_code == 400
    assert "couldn&#39;t find any site boundaries" in resp.text
    assert 'value="Keep me"' in resp.text and ">hello</textarea>" in resp.text
    assert query("SELECT * FROM jobs") == []
    assert list(settings.jobs_dir.iterdir()) == []
    # An invalid file does not use up a run.
    assert "<strong>3</strong> screening runs left" in flow.client.get("/upload").text


def test_upload_rejects_wrong_extension_and_long_notes(flow, query):
    flow.login("ext@example.com")
    resp = flow.upload(content=flow.sample_kml, filename="site.geojson")
    assert resp.status_code == 400 and ".kml or .kmz" in resp.text
    resp = flow.upload(notes="x" * 501)
    assert resp.status_code == 400 and "500 characters" in resp.text
    resp = flow.client.post("/upload", data={"csrf": flow.csrf()}, follow_redirects=False)
    assert resp.status_code == 400 and "choose a .kml or .kmz" in resp.text
    assert query("SELECT * FROM jobs") == []


def test_upload_too_large(app_factory):
    flow = app_factory("small", max_upload_mb=0.01)            # ~10 KB cap
    flow.login("big@example.com")
    big = flow.sample_kml + b"<!--" + b"x" * 20_000 + b"-->"
    resp = flow.upload(content=big)
    assert resp.status_code == 413 and "larger than" in resp.text
    huge = b"<kml>" + b"y" * 200_000                           # beyond the request cap: refused while streaming
    resp = flow.upload(content=huge)
    assert resp.status_code == 413 and "larger than" in resp.text
    assert list(flow.settings.jobs_dir.iterdir()) == []


def test_failed_job_shows_message(flow, settings, fake_engine, query):
    flow.login("fail@example.com")
    job_id = flow.upload_job()
    fake_engine.run_behaviour = "screening_error"
    jobs.run_once(settings)
    page = flow.client.get(f"/reports/{job_id}")
    assert page.status_code == 200
    assert "elevation data service could not be reached" in page.text and "Try again" in page.text
    assert flow.client.get(f"/api/reports/{job_id}/status").json()["status"] == "failed"
    assert flow.client.get(f"/reports/{job_id}/download.pdf").status_code == 404


def test_crashed_job_shows_generic_message(flow, settings, fake_engine, query, caplog):
    flow.login("crash@example.com")
    job_id = flow.upload_job()
    fake_engine.run_behaviour = "crash"
    jobs.run_once(settings)
    job = query("SELECT * FROM jobs WHERE id = ?", (job_id,))[0]
    assert job["status"] == "failed" and job["error"] == jobs.GENERIC_FAILURE
    assert "simulated engine crash" not in flow.client.get(f"/reports/{job_id}").text
    assert "simulated engine crash" in caplog.text            # traceback logged for the team


def test_account_page_newsletter_toggle_and_export(flow, query, settings):
    flow.login("acct@example.com")
    job_id = flow.upload_job(site_label="Export me")
    jobs.run_once(settings)

    page = flow.client.get("/account")
    assert page.status_code == 200
    assert "acct@example.com" in page.text and "Consent history" in page.text and "Export me" in page.text
    csrf = flow.hidden(page.text, "csrf")

    resp = flow.client.post("/account/newsletter", data={"csrf": csrf, "action": "subscribe"},
                            follow_redirects=False)
    assert resp.status_code == 303
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "subscribed"
    news = [c["action"] for c in query("SELECT action FROM consents WHERE purpose='newsletter' ORDER BY id")]
    assert news == ["granted", "confirmed"]

    flow.client.post("/account/newsletter", data={"csrf": csrf, "action": "unsubscribe"})
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "unsubscribed"
    news = [c["action"] for c in query("SELECT action FROM consents WHERE purpose='newsletter' ORDER BY id")]
    assert news == ["granted", "confirmed", "withdrawn"]

    export = flow.client.get("/account/export.json")
    assert export.status_code == 200 and "attachment" in export.headers["content-disposition"]
    data = json.loads(export.content)
    assert data["subscriber"]["email"] == "acct@example.com"
    assert len(data["consents"]) >= 4
    assert data["jobs"][0]["id"] == job_id
    assert data["jobs"][0]["result"]["totals"]["total_area_ha"] == 123.4


def test_logout(flow):
    flow.login("bye@example.com")
    csrf = flow.csrf()
    resp = flow.client.post("/logout", data={"csrf": csrf}, follow_redirects=False)
    assert resp.status_code == 303
    assert flow.client.get("/upload", follow_redirects=False).status_code == 303


def test_privacy_page(client, settings):
    resp = client.get("/privacy")
    assert resp.status_code == 200
    html = resp.text
    assert "Draft for legal review" in html
    assert settings.notice_version == "2026-10-draft-2" and settings.notice_version in html
    # Data controller identity and contact (PDP Regulations 2013 reg 4: designation + phone).
    for phrase in ("EcoEnergy Consultancy Sdn. Bhd.", "Level 22, Menara Merdeka 118", "50118 Kuala Lumpur",
                   "+60 3 8744 6478", "contact@ecoconsultancy.services", "[Designation of contact person"):
        assert phrase in html, phrase
    # Both languages, with a jump link.
    assert 'lang="ms"' in html and 'id="bm"' in html and 'href="#bm"' in html and 'href="#en"' in html
    assert "Notis privasi" in html
    for phrase in (
        "obligatory", "Data portability", "outside Malaysia", "section 129", "[to be confirmed]",
        "Hosting", "email-delivery", "data processors",
        # Staff follow-up is a separate opt-in per report, withdrawable per report.
        "separate, optional box on the upload page", "kotak pilihan yang berasingan di halaman muat naik",
        # Elevation data: tile names only, never the coordinates (default Copernicus provider).
        "only the 1° map tile names are requested, not your site's coordinates",
        # Retention.
        f"{settings.retention_days} days", f"after {settings.unverified_purge_days} days", "one-way hash",
        "reg 3(5)",
        # Rights.
        "21 days", "14 days", "sections 31 and 35", "section 38", "section 43)", "section 43A",
        # Age.
        "aged 18 and above", "berumur 18 tahun ke atas",
    ):
        assert phrase in html, phrase
    # No deadline for portability: none has been prescribed under s.43A(3).
    for marker in ('id="portability"', 'id="portability-bm"'):
        item = html[html.index(marker):]
        item = item[:item.index("</li>")]
        assert "day" not in item and "hari" not in item, item
    # With the default Copernicus provider nothing is sent to OpenTopoData.
    assert "OpenTopoData" not in html


def test_privacy_and_forms_mention_opentopodata_only_when_it_is_used(app_factory):
    otd = app_factory("otd", dem_provider="opentopodata")
    html = otd.client.get("/privacy").text
    assert "your site's coordinates are sent to OpenTopoData" in html
    assert "koordinat tapak anda dihantar kepada OpenTopoData" in html
    assert "coordinates are sent to the OpenTopoData service" in otd.client.get("/").text
    otd.login("otd@example.com")
    assert "coordinates are sent to the OpenTopoData service" in otd.client.get("/upload").text

    default = app_factory("cop")
    assert "OpenTopoData" not in default.client.get("/").text


def test_dev_outbox_only_in_dev(flow, app_factory):
    flow.request_link("dev@example.com")
    listing = flow.client.get("/dev/outbox")
    assert listing.status_code == 200 and "dev@example.com" in listing.text
    msg_id = flow.mails()[-1]["id"]
    msg = flow.client.get(f"/dev/outbox/{msg_id}")
    assert msg.status_code == 200 and '<a href="http://testserver/start?t=' in msg.text
    assert flow.client.get(f"/dev/outbox/{msg_id}/html").status_code == 200

    smtp = app_factory("smtp", mail_backend="smtp")
    assert smtp.client.get("/dev/outbox").status_code == 404
    assert smtp.client.get("/dev/outbox/1").status_code == 404


def test_smtp_backend_builds_multipart_message(monkeypatch, app_factory):
    import smtplib

    from app.mailer import render_email, send_mail

    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.calls = [("connect", host, port)]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            sent.append(self.calls)

        def ehlo(self):
            self.calls.append(("ehlo",))

        def starttls(self, context):
            self.calls.append(("starttls",))

        def login(self, user, password):
            self.calls.append(("login", user, password))

        def send_message(self, msg):
            self.calls.append(("send", msg))

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    settings = app_factory("smtpmail", mail_backend="smtp", smtp_host="mail.example", smtp_port=587,
                           smtp_starttls=True, smtp_user="u", smtp_password="p").settings
    text, html = render_email(settings, "magic_link", link="http://testserver/start?t=abc")
    send_mail(settings, "to@example.com", "Your terrain screening link", text, html)

    calls = sent[0]
    names = [c[0] for c in calls]
    assert names[:3] == ["connect", "ehlo", "starttls"] and ("login", "u", "p") in calls
    msg = calls[-1][1]
    assert msg["To"] == "to@example.com" and msg["From"] == settings.mail_from
    assert msg["Reply-To"] == settings.mail_reply_to and msg["Message-ID"] and msg["Date"]
    assert "List-Unsubscribe" not in msg                    # transactional mail
    assert msg.get_body(("plain",)).get_content().startswith("Your terrain screening link")
    assert "Open my screening link" in msg.get_body(("html",)).get_content()
    with db(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0


# ----------------------------------------------------------------------------
# Staff follow-up: a separate, optional consent per report
# ----------------------------------------------------------------------------


def checkbox(html: str, element_id: str) -> str:
    return html[html.index(f'id="{element_id}"'):].split(">", 1)[0]


def test_followup_opt_in_on_upload_is_recorded_per_job(flow, query, settings):
    flow.login("opt@example.com")
    yes_job = flow.upload_job(followup="yes", site_label="Site yes")
    no_job = flow.upload_job(site_label="Site no")
    states = {r["id"]: r["followup_consent"] for r in query("SELECT id, followup_consent FROM jobs")}
    assert states == {yes_job: 1, no_job: 0}
    ledger = query("SELECT * FROM consents WHERE purpose = 'site_followup'")
    assert len(ledger) == 1
    row = ledger[0]
    assert row["job_id"] == yes_job and row["action"] == "granted"
    assert row["notice_version"] == settings.notice_version and row["ip"] and row["user_agent"]
    assert row["wording"] == ("EcoEnergy staff may email me about this site (optional). / Kakitangan EcoEnergy "
                              "boleh menghubungi saya melalui e-mel berkenaan tapak ini (pilihan).")
    # Signing in again never confirms, extends or copies per-report consents.
    flow.login("opt@example.com")
    assert len(query("SELECT * FROM consents WHERE purpose = 'site_followup'")) == 1
    assert query("SELECT followup_consent FROM jobs WHERE id = ?", (no_job,))[0]["followup_consent"] == 0


def test_followup_box_keeps_the_visitors_choice_on_rerender(flow):
    flow.login("keep@example.com")
    resp = flow.upload(content=b"not a kml", followup="yes")
    assert resp.status_code == 400 and "checked" in checkbox(resp.text, "followup")
    resp = flow.upload(content=b"not a kml")
    assert resp.status_code == 400 and "checked" not in checkbox(resp.text, "followup")


def test_followup_change_from_result_page(flow, query, settings):
    flow.login("change@example.com")
    job_id = flow.upload_job()
    jobs.run_once(settings)
    page = flow.client.get(f"/reports/{job_id}")
    assert "Not allowed." in page.text
    csrf = flow.hidden(page.text, "csrf")

    resp = flow.client.post(f"/reports/{job_id}/followup", data={"csrf": csrf, "action": "grant"},
                            follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == f"/reports/{job_id}?m=followup_on#followup"
    assert query("SELECT followup_consent FROM jobs")[0]["followup_consent"] == 1
    page = flow.client.get(resp.headers["location"])
    assert "Allowed." in page.text and "Stop EcoEnergy staff from emailing me about this site." in page.text
    assert "EcoEnergy staff may now email you about this site" in page.text

    # Repeating the current choice adds nothing to the ledger.
    flow.client.post(f"/reports/{job_id}/followup", data={"csrf": csrf, "action": "grant"})
    resp = flow.client.post(f"/reports/{job_id}/followup", data={"csrf": csrf, "action": "withdraw"},
                            follow_redirects=False)
    assert resp.headers["location"] == f"/reports/{job_id}?m=followup_off#followup"
    assert query("SELECT followup_consent FROM jobs")[0]["followup_consent"] == 0
    ledger = query("SELECT * FROM consents WHERE purpose = 'site_followup' ORDER BY id")
    assert [r["action"] for r in ledger] == ["granted", "withdrawn"]
    assert all(r["job_id"] == job_id and r["notice_version"] == settings.notice_version for r in ledger)
    assert ledger[0]["wording"].startswith("Allow EcoEnergy staff to email me about this site. / Benarkan")
    assert ledger[1]["wording"].startswith("Stop EcoEnergy staff from emailing me about this site. / Hentikan")
    assert "Not allowed." in flow.client.get(f"/reports/{job_id}").text


def test_followup_change_from_account_page(flow, query):
    flow.login("acctfu@example.com")
    first = flow.upload_job(site_label="First site", followup="yes")
    second = flow.upload_job(site_label="Second site")
    html = flow.client.get("/account").text
    assert "Staff follow-up" in html
    for job_id in (first, second):
        assert f'action="/reports/{job_id}/followup"' in html
    csrf = flow.hidden(html, "csrf")

    resp = flow.client.post(f"/reports/{first}/followup", data={"csrf": csrf, "action": "withdraw", "back": "account"},
                            follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/account?m=followup_off#reports-title"
    flow.client.post(f"/reports/{second}/followup", data={"csrf": csrf, "action": "grant", "back": "account"})
    states = {r["id"]: r["followup_consent"] for r in query("SELECT id, followup_consent FROM jobs")}
    assert states == {first: 0, second: 1}
    ledger = [(r["job_id"], r["action"]) for r in
              query("SELECT job_id, action FROM consents WHERE purpose = 'site_followup' ORDER BY id")]
    assert ledger == [(first, "granted"), (first, "withdrawn"), (second, "granted")]

    page = flow.client.get("/account?m=followup_on").text
    assert "EcoEnergy staff may now email you about this site" in page
    history = page[page.index("Consent history"):]
    assert "First site" in history and "Second site" in history

    export = json.loads(flow.client.get("/account/export.json").content)
    assert {j["id"]: j["followup_consent"] for j in export["jobs"]} == {first: 0, second: 1}
    assert [c["job_id"] for c in export["consents"] if c["purpose"] == "site_followup"] == [first, first, second]


def test_followup_change_needs_csrf_ownership_and_a_valid_action(flow, make_flow, query):
    flow.login("owner@example.com")
    job_id = flow.upload_job()
    csrf = flow.csrf()
    assert flow.client.post(f"/reports/{job_id}/followup", data={"action": "grant"}).status_code == 403
    assert flow.client.post(f"/reports/{job_id}/followup", data={"csrf": "x" * 43, "action": "grant"}).status_code == 403
    assert flow.client.post(f"/reports/{job_id}/followup", data={"csrf": csrf, "action": "maybe"}).status_code == 400
    assert flow.client.post("/reports/not-a-real-job-id/followup",
                            data={"csrf": csrf, "action": "grant"}).status_code == 404

    other = make_flow()
    other.login("other@example.com")
    resp = other.client.post(f"/reports/{job_id}/followup", data={"csrf": other.csrf(), "action": "grant"})
    assert resp.status_code == 404
    anonymous = make_flow()
    resp = anonymous.client.post(f"/reports/{job_id}/followup", data={"action": "grant"}, follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/?m=login"

    assert query("SELECT followup_consent FROM jobs")[0]["followup_consent"] == 0
    assert query("SELECT * FROM consents WHERE purpose = 'site_followup'") == []


def test_deleting_a_report_ends_followup(flow, query, settings):
    flow.login("del@example.com")
    job_id = flow.upload_job(followup="yes")
    jobs.run_once(settings)
    flow.client.post(f"/reports/{job_id}/delete", data={"csrf": flow.csrf()})
    job = query("SELECT * FROM jobs WHERE id = ?", (job_id,))[0]
    assert job["status"] == "deleted" and job["followup_consent"] == 0
    resp = flow.client.post(f"/reports/{job_id}/followup", data={"csrf": flow.csrf(), "action": "grant"})
    assert resp.status_code == 404
    assert f'action="/reports/{job_id}/followup"' not in flow.client.get("/account").text
    # The ledger keeps what was agreed and when (reg 3(5): we must be able to prove consent).
    assert [r["action"] for r in query("SELECT action FROM consents WHERE purpose = 'site_followup'")] == ["granted"]


# ----------------------------------------------------------------------------
# Result page: DEM notices (fields added to result.json after schema_version 1 shipped)
# ----------------------------------------------------------------------------


def test_result_page_shows_dem_disclaimer_and_third_party_note(flow, settings):
    flow.login("dem@example.com")
    job_id = flow.upload_job()
    jobs.run_once(settings)
    path = settings.jobs_dir / job_id / "result.json"

    html = flow.client.get(f"/reports/{job_id}").text
    assert "DEM notice" in html and "do not incur any liability" in html
    assert "coordinates were sent" not in html

    result = json.loads(path.read_text(encoding="utf-8"))
    result["dem"].update(provider="opentopodata", name="SRTM 1 arc-second (via OpenTopoData)",
                         sends_coordinates_to_third_party=True, disclaimer=None)
    path.write_text(json.dumps(result), encoding="utf-8")
    html = flow.client.get(f"/reports/{job_id}").text
    assert "coordinates were sent to an external" in html and "SRTM 1 arc-second (via OpenTopoData)" in html
    assert "DEM notice" not in html                       # null disclaimer: no empty row


def test_older_result_json_without_new_dem_fields_still_renders(flow, settings):
    flow.login("old@example.com")
    job_id = flow.upload_job()
    jobs.run_once(settings)
    path = settings.jobs_dir / job_id / "result.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    for key in ("disclaimer", "sends_coordinates_to_third_party"):
        result["dem"].pop(key, None)
    path.write_text(json.dumps(result), encoding="utf-8")
    page = flow.client.get(f"/reports/{job_id}")
    assert page.status_code == 200 and "Copernicus DEM GLO-30" in page.text
    assert "DEM notice" not in page.text and "coordinates were sent" not in page.text


# ----------------------------------------------------------------------------
# Owner documentation stays in step with Settings
# ----------------------------------------------------------------------------


def test_env_example_and_readme_document_every_setting():
    from dataclasses import MISSING, fields
    from pathlib import Path

    from app.config import PROJECT_ROOT, Settings

    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    lines = {}
    for raw in env_example.splitlines():
        m = re.match(r"^#? ?([A-Z][A-Z0-9_]*)=(.*)$", raw)
        if m:
            lines[m.group(1)] = m.group(2)
    for f in fields(Settings):
        if f.name == "extra":
            continue
        key = f.name.upper()
        assert key in lines, f".env.example is missing {key}"
        assert f"`{key}`" in readme, f"README configuration table is missing {key}"
        value, default = lines[key], f.default
        assert default is not MISSING
        if isinstance(default, bool):
            assert value == str(default).lower(), key
        elif isinstance(default, (int, float)):
            assert float(value) == float(default), key
        elif isinstance(default, Path):
            assert value == "./data", key
        else:
            assert value == default, key
        # Comments live on their own lines: the .env reader would keep an inline "# ..." in the value.
        assert "#" not in value, key
    assert re.search(r"^ADMIN_PASSWORD=$", env_example, re.MULTILINE), "ADMIN_PASSWORD must ship empty"
