"""End-to-end visitor flow: landing → link → confirm → upload → job → report → delete."""
from __future__ import annotations

import json

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
    # Bilingual notice line linking to /privacy.
    assert 'href="/privacy"' in html and "E-mel anda diperlukan" in html
    assert "EcoEnergy may follow up with you about the site you submit." in html
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
    consents = query("SELECT purpose, action, notice_version FROM consents ORDER BY id")
    assert {c["purpose"] for c in consents} == {"service", "site_followup"}
    assert {(c["purpose"], c["action"]) for c in consents} == {
        ("service", "granted"), ("site_followup", "granted"),
        ("service", "confirmed"), ("site_followup", "confirmed")}
    assert all(c["notice_version"] == settings.notice_version for c in consents)


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
    assert ("service", "confirmed") in actions and ("site_followup", "confirmed") in actions
    confirmed = query("SELECT * FROM consents WHERE purpose='newsletter' AND action='confirmed'")[0]
    assert confirmed["wording"] == granted[0]["wording"]


def test_consent_wording_matches_what_was_shown(client, flow, query):
    page = client.get("/").text
    flow.request_link("words@example.com", newsletter=True)
    for c in query("SELECT wording FROM consents"):
        en, bm = c["wording"].split(" / ")
        assert en.replace("'", "&#39;") in page and bm in page


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
    assert settings.notice_version in html
    assert "contact@ecoconsultancy.services" in html
    assert 'lang="ms"' in html and "Notis privasi" in html
    for phrase in ("obligatory", "Data portability", "outside Malaysia", "Withdraw consent",
                   "Hosting and infrastructure", "Email delivery", f"{settings.retention_days} days"):
        assert phrase in html, phrase


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
