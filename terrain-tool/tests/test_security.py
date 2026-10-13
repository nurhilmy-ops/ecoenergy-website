"""Security and privacy properties of the web app."""
from __future__ import annotations

import base64
import csv
import io
from datetime import timedelta

import pytest

from app import jobs, security
from app.db import db, iso, utcnow
from app.mailer import newsletter_headers
from app.security import (
    InvalidEmail, client_ip, is_disposable, make_unsubscribe_token, normalise_email, origin_of,
    redact_query, safe_next_path, sha256_hex, verify_unsubscribe_token,
)


def basic(user: str, password: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


# ----------------------------------------------------------------------------
# Unit-level helpers
# ----------------------------------------------------------------------------


def test_email_normalisation_and_disposable_list():
    assert normalise_email("  Jane.Doe@Example.COM ") == "jane.doe@example.com"
    for bad in ("", "jane", "jane@localhost", "a@b..com", "x" * 250 + "@example.com"):
        with pytest.raises(InvalidEmail):
            normalise_email(bad)
    assert is_disposable("x@mailinator.com") and is_disposable("x@inbox.yopmail.com")
    assert is_disposable("x@MAILDROP.CC".lower())
    assert not is_disposable("x@gmail.com") and not is_disposable("x@notmailinator.com")


def test_safe_next_path_blocks_open_redirects():
    assert safe_next_path("/reports/abcDEF_123-xyz") == "/reports/abcDEF_123-xyz"
    for bad in (None, "", "//evil.example/reports/x", "https://evil.example/reports/x", "/reports/../admin",
                "/reports/x?next=//evil", "/upload", "/reports//evil.example", "\\\\evil.example",
                "/reports/x\\y", "javascript:alert(1)"):
        assert safe_next_path(bad) is None, bad


def test_origin_of():
    assert origin_of("https://Example.com:443/a?b") == "https://example.com"
    assert origin_of("http://localhost:8000/x") == "http://localhost:8000"
    assert origin_of("null") == "" and origin_of("ftp://x.example") == ""


def test_unsubscribe_token_signature(settings):
    token = make_unsubscribe_token(settings, 42)
    assert verify_unsubscribe_token(settings, token) == 42
    sid, sig = token.split(".")
    assert verify_unsubscribe_token(settings, f"43.{sig}") is None
    assert verify_unsubscribe_token(settings, f"{sid}.{sig[:-1]}A") is None
    assert verify_unsubscribe_token(settings, "garbage") is None
    headers = newsletter_headers(settings, 42)
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert f"<http://testserver/unsubscribe?u={token}>" in headers["List-Unsubscribe"]
    assert "mailto:" in headers["List-Unsubscribe"]


def test_redact_query_hides_tokens():
    assert redact_query("/start?t=SECRET123") == "/start?t=[redacted]"
    assert "SECRET" not in redact_query("/unsubscribe?u=1.SECRET&x=1")
    assert redact_query("/?utm_source=x") == "/?utm_source=x"


def test_client_ip_respects_trust_proxy_headers(app_factory):
    from starlette.requests import Request

    scope = {"type": "http", "headers": [(b"x-forwarded-for", b"203.0.113.9, 10.0.0.1")],
             "client": ("10.0.0.2", 1234)}
    untrusted = app_factory("ip1").settings
    trusted = app_factory("ip2", trust_proxy_headers=True).settings
    assert client_ip(Request(scope), untrusted) == "10.0.0.2"
    assert client_ip(Request(scope), trusted) == "203.0.113.9"


# ----------------------------------------------------------------------------
# Link requests
# ----------------------------------------------------------------------------


def _normalised(resp, email: str) -> tuple[int, str]:
    return resp.status_code, resp.text.replace(email, "EMAIL")


def test_request_link_is_enumeration_safe(flow, query, settings):
    new = _normalised(flow.request_link("new@example.com"), "new@example.com")

    flow.login("known@example.com")
    flow.client.cookies.clear()
    known = _normalised(flow.request_link("known@example.com"), "known@example.com")

    for _ in range(settings.rate_link_per_email_hour):
        flow.request_link("busy@example.com")
    sent_before = len(flow.mails("busy@example.com"))
    limited = _normalised(flow.request_link("busy@example.com"), "busy@example.com")
    assert len(flow.mails("busy@example.com")) == sent_before            # nothing sent when limited

    with db(settings.db_path) as conn:
        conn.execute("INSERT INTO suppression (email_sha256, created_at) VALUES (?, '2026-01-01T00:00:00+00:00')",
                     (sha256_hex("gone@example.com"),))
    suppressed = _normalised(flow.request_link("gone@example.com"), "gone@example.com")

    assert new == known == limited == suppressed
    assert new[0] == 200


def test_disposable_and_invalid_emails_rerender_form(flow, query):
    resp = flow.request_link("someone@mailinator.com", newsletter=True)
    assert resp.status_code == 400 and "permanent email address" in resp.text
    assert 'value="someone@mailinator.com"' in resp.text
    assert "checked" in resp.text[resp.text.index('id="newsletter"'):].split(">", 1)[0]
    resp = flow.request_link("not-an-email")
    assert resp.status_code == 400 and "check your email address" in resp.text
    assert query("SELECT * FROM subscribers") == [] and flow.mails() == []


def test_link_rate_limit_per_ip(app_factory):
    flow = app_factory("iplimit", rate_link_per_ip_hour=2)
    for i in range(4):
        assert flow.request_link(f"user{i}@example.com").status_code == 200
    assert len(flow.mails()) == 2


def test_resignup_after_erasure_lifts_suppression(flow, query):
    flow.request_link("back@example.com")
    with db(flow.settings.db_path) as conn:
        conn.execute("DELETE FROM subscribers")
        conn.execute("INSERT INTO suppression (email_sha256, created_at) VALUES (?, '2026-01-01T00:00:00+00:00')",
                     (sha256_hex("back@example.com"),))
    flow.request_link("back@example.com")
    assert query("SELECT * FROM suppression") == []
    assert len(query("SELECT * FROM subscribers")) == 1


def test_turnstile_enforced_when_configured(app_factory, monkeypatch):
    calls = []

    class FakeResp:
        def __init__(self, ok):
            self.ok = ok

        def json(self):
            return {"success": self.ok}

    def fake_post(url, data, timeout):
        calls.append((url, data))
        return FakeResp(data["response"] == "good-token")

    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    flow = app_factory("ts", turnstile_site_key="site-key", turnstile_secret_key="secret")
    page = flow.client.get("/")
    assert "challenges.cloudflare.com/turnstile/v0/api.js" in page.text and 'data-sitekey="site-key"' in page.text

    resp = flow.request_link("bot@example.com")
    assert resp.status_code == 400 and "human check" in resp.text and flow.mails() == []
    resp = flow.request_link("bot@example.com", **{"cf-turnstile-response": "bad"})
    assert resp.status_code == 400
    resp = flow.request_link("human@example.com", **{"cf-turnstile-response": "good-token"})
    assert resp.status_code == 200 and len(flow.mails()) == 1
    assert calls[-1][0] == security.TURNSTILE_VERIFY_URL and calls[-1][1]["secret"] == "secret"


# ----------------------------------------------------------------------------
# Tokens and sessions
# ----------------------------------------------------------------------------


def test_token_expiry(flow, query, settings):
    flow.request_link("late@example.com")
    token = flow.latest_token("late@example.com")
    page = flow.client.get(f"/start?t={token}")
    pre = flow.hidden(page.text, "pre")
    with db(settings.db_path) as conn:
        conn.execute("UPDATE tokens SET expires_at = ?", (iso(utcnow() - timedelta(minutes=1)),))
    expired = flow.client.get(f"/start?t={token}")
    assert expired.status_code == 400 and "expired or has already been used" in expired.text
    resp = flow.client.post("/start", data={"t": token, "pre": pre}, follow_redirects=False)
    assert resp.status_code == 400 and "tt_session" not in resp.headers.get("set-cookie", "")
    assert query("SELECT verified_at FROM subscribers")[0]["verified_at"] is None


def test_token_max_uses(app_factory):
    flow = app_factory("uses", token_max_uses=2)
    flow.request_link("twice@example.com")
    token = flow.latest_token("twice@example.com")
    assert flow.confirm(token).status_code == 303
    assert flow.confirm(token).status_code == 303
    page = flow.client.get(f"/start?t={token}")
    assert page.status_code == 400 and "Request a new link" in page.text
    assert flow.client.post("/start", data={"t": token, "pre": "x" * 32}).status_code == 400
    with db(flow.settings.db_path) as conn:
        assert conn.execute("SELECT uses_left FROM tokens").fetchone()[0] == 0


def test_start_requires_preauth_cookie(flow, query):
    """Login CSRF: a cross-site form cannot post someone else's token for the visitor."""
    flow.request_link("victim@example.com")
    token = flow.latest_token("victim@example.com")
    resp = flow.client.post("/start", data={"t": token, "pre": "forged-value-forged-value"},
                            follow_redirects=False)
    assert resp.status_code == 200 and "Please press Continue once more" in resp.text
    assert query("SELECT uses_left FROM tokens")[0]["uses_left"] == 5
    assert query("SELECT * FROM sessions") == []


def test_next_path_open_redirect_protection(flow, settings, query):
    flow.request_link("redir@example.com")
    with db(settings.db_path) as conn:
        conn.execute("UPDATE tokens SET next_path = '//evil.example/reports/x'")
    resp = flow.confirm(flow.latest_token("redir@example.com"))
    assert resp.status_code == 303 and resp.headers["location"] == "/upload"
    sub_id = query("SELECT id FROM subscribers")[0]["id"]
    raw = security.create_magic_token(settings, sub_id, next_path="https://evil.example/")
    with db(settings.db_path) as conn:
        assert conn.execute("SELECT next_path FROM tokens WHERE token_hash = ?",
                            (sha256_hex(raw),)).fetchone()[0] is None


def test_sessions_and_tokens_stored_hashed(flow, query):
    flow.login("hash@example.com")
    cookie = flow.client.cookies.get("tt_session")
    assert cookie and query("SELECT * FROM sessions WHERE id = ?", (cookie,)) == []
    assert len(query("SELECT * FROM sessions WHERE id = ?", (sha256_hex(cookie),))) == 1


def test_secure_cookie_flags_on_https(app_factory):
    from fastapi.testclient import TestClient

    flow = app_factory("https", base_url="https://tool.example")
    flow.client = TestClient(flow.client.app, base_url="https://tool.example")
    flow.request_link("tls@example.com")
    token = flow.latest_token("tls@example.com")
    page = flow.client.get(f"/start?t={token}")
    assert "__Host-tt_pre=" in page.headers["set-cookie"] and "Secure" in page.headers["set-cookie"]
    resp = flow.client.post("/start", data={"t": token, "pre": flow.hidden(page.text, "pre")},
                            follow_redirects=False)
    set_cookie = resp.headers.get_list("set-cookie")
    session_cookie = next(c for c in set_cookie if c.startswith("__Host-tt_session="))
    assert "Secure" in session_cookie and "HttpOnly" in session_cookie and "Path=/" in session_cookie
    assert "Max-Age=86400" in session_cookie
    assert "strict-transport-security" in resp.headers
    flow.client.close()


# ----------------------------------------------------------------------------
# Access control
# ----------------------------------------------------------------------------


def test_reports_are_private_to_their_owner(flow, make_flow, settings):
    flow.login("owner@example.com")
    job_id = flow.upload_job()
    jobs.run_once(settings)
    assert flow.client.get(f"/reports/{job_id}").status_code == 200

    other = make_flow()
    other.login("other@example.com")
    for path in (f"/reports/{job_id}", f"/reports/{job_id}/files/1_site_layout.png",
                 f"/reports/{job_id}/download.pdf", f"/reports/{job_id}/download.docx",
                 f"/api/reports/{job_id}/status", "/reports/doesNotExist123/download.pdf"):
        assert other.client.get(path).status_code == 404, path
    resp = other.client.post(f"/reports/{job_id}/delete", data={"csrf": other.csrf()})
    assert resp.status_code == 404
    assert (settings.jobs_dir / job_id / "report.pdf").exists()
    assert job_id not in other.client.get("/reports").text

    anon = make_flow()
    assert anon.client.get(f"/reports/{job_id}", follow_redirects=False).status_code == 303
    assert anon.client.get(f"/api/reports/{job_id}/status").status_code == 404
    assert anon.client.get(f"/reports/{job_id}/download.pdf").status_code == 404

    # Only whitelisted figure names are served, even to the owner.
    for name in ("result.json", "input.kml", "summary.md", "..%2Fapp.db"):
        assert flow.client.get(f"/reports/{job_id}/files/{name}").status_code == 404, name


def test_csrf_required_on_state_changing_posts(flow, settings, query):
    flow.login("csrf@example.com")
    job_id = flow.upload_job()
    resp = flow.upload(csrf="wrong")
    assert resp.status_code == 403
    assert flow.client.post(f"/reports/{job_id}/delete", data={}).status_code == 403
    assert (settings.jobs_dir / job_id).exists()
    assert flow.client.post("/account/newsletter", data={"action": "subscribe"}).status_code == 403
    assert flow.client.post("/account/delete", data={"confirm": "yes"}).status_code == 403
    assert flow.client.post("/logout", data={"csrf": "nope"}).status_code == 403
    assert len(query("SELECT * FROM subscribers")) == 1
    assert flow.client.get("/upload").status_code == 200          # still logged in


def test_origin_check(flow, query):
    resp = flow.client.post("/request-link", data={"email": "x@example.com"},
                            headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    assert "content-security-policy" in resp.headers
    assert query("SELECT * FROM subscribers") == []
    ok = flow.client.post("/request-link", data={"email": "x@example.com"}, headers={"Origin": "http://testserver"})
    assert ok.status_code == 200
    # Browsers send "Origin: null" for our own forms because of Referrer-Policy: no-referrer.
    null = flow.client.post("/request-link", data={"email": "y@example.com"}, headers={"Origin": "null"})
    assert null.status_code == 200

    flow.login("z@example.com")
    resp = flow.client.post("/logout", data={"csrf": flow.csrf()}, headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403


def test_request_body_cap(flow):
    resp = flow.client.post("/request-link", data={"email": "a@example.com", "pad": "x" * 100_000})
    assert resp.status_code == 413

    def chunks():                       # no Content-Length: the cap is enforced while streaming
        yield b"email=a%40example.com&pad="
        for _ in range(20):
            yield b"x" * 8192

    resp = flow.client.post("/request-link", content=chunks(),
                            headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert resp.status_code == 413 and "content-security-policy" in resp.headers
    assert flow.mails() == []


# ----------------------------------------------------------------------------
# Unsubscribe, export and erasure
# ----------------------------------------------------------------------------


def test_one_click_unsubscribe(flow, make_flow, query, settings):
    flow.login("news@example.com", newsletter=True)
    sub_id = query("SELECT id FROM subscribers")[0]["id"]
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "subscribed"
    token = make_unsubscribe_token(settings, sub_id)

    mail_provider = make_flow()                  # no cookies, foreign Origin, no CSRF token
    page = mail_provider.client.get(f"/unsubscribe?u={token}")
    assert page.status_code == 200 and "Unsubscribe from EcoEnergy insights?" in page.text
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "subscribed"

    tampered = mail_provider.client.post(f"/unsubscribe?u={sub_id}.AAAA", data={"List-Unsubscribe": "One-Click"})
    assert tampered.status_code == 400
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "subscribed"

    resp = mail_provider.client.post(f"/unsubscribe?u={token}", data={"List-Unsubscribe": "One-Click"},
                                     headers={"Origin": "https://mail.google.com"})
    assert resp.status_code == 200 and "unsubscribed" in resp.text.lower()
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "unsubscribed"
    withdrawn = query("SELECT * FROM consents WHERE purpose='newsletter' AND action='withdrawn'")
    assert len(withdrawn) == 1 and withdrawn[0]["notice_version"] == settings.notice_version


def test_account_delete_erases_everything_and_suppresses(flow, query, settings):
    flow.login("erase@example.com", newsletter=True)
    job_id = flow.upload_job()
    jobs.run_once(settings)
    assert (settings.jobs_dir / job_id).exists()

    page = flow.client.get("/account")
    csrf = flow.hidden(page.text, "csrf")
    resp = flow.client.post("/account/delete", data={"csrf": csrf})          # box not ticked
    assert resp.status_code == 400 and "tick the box" in resp.text
    assert len(query("SELECT * FROM subscribers")) == 1

    resp = flow.client.post("/account/delete", data={"csrf": csrf, "confirm": "yes"})
    assert resp.status_code == 200 and "Your data has been deleted" in resp.text
    assert 'tt_session=""' in resp.headers["set-cookie"] or "Max-Age=0" in resp.headers["set-cookie"]
    for table in ("subscribers", "consents", "tokens", "sessions", "jobs", "outbox"):
        assert query(f"SELECT * FROM {table}") == [], table
    assert not (settings.jobs_dir / job_id).exists()
    assert query("SELECT email_sha256 FROM suppression")[0]["email_sha256"] == sha256_hex("erase@example.com")
    assert flow.client.get("/account", follow_redirects=False).status_code == 303


# ----------------------------------------------------------------------------
# Headers
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/privacy", "/static/css/app.css", "/no-such-page", "/start?t=x",
                                  "/api/reports/abcdefgh/status", "/upload"])
def test_security_headers_everywhere(client, path):
    resp = client.get(path, follow_redirects=False)
    csp = resp.headers["content-security-policy"]
    for directive in ("default-src 'self'", "img-src 'self' data:", "frame-ancestors 'none'", "base-uri 'none'",
                      "form-action 'self'", "script-src 'self' https://challenges.cloudflare.com",
                      "font-src https://fonts.gstatic.com",
                      "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'"):
        assert directive in csp
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert "camera=()" in resp.headers["permissions-policy"]
    if not path.startswith("/static/"):
        assert resp.headers["cache-control"] == "no-store"


def test_personal_pages_not_cacheable(flow):
    flow.login("cache@example.com")
    for path in ("/upload", "/reports", "/account", "/account/export.json"):
        assert flow.client.get(path).headers["cache-control"] == "no-store", path


# ----------------------------------------------------------------------------
# Admin
# ----------------------------------------------------------------------------


def test_admin_disabled_without_password(app_factory):
    flow = app_factory("noadmin", admin_password="")
    assert flow.client.get("/admin/").status_code == 404
    assert flow.client.get("/admin/export/leads.csv", headers={"Authorization": "Basic !!!"}).status_code == 404


def test_admin_auth_and_pages(flow, make_flow, settings):
    assert flow.client.get("/admin/").status_code == 401
    assert "Basic" in flow.client.get("/admin/").headers["www-authenticate"]
    assert flow.client.get("/admin/", headers=basic("admin", "wrong")).status_code == 401
    assert flow.client.get("/admin/", headers=basic("root", settings.admin_password)).status_code == 401
    auth = basic(settings.admin_user, settings.admin_password)

    # Data: one subscribed lead from LinkedIn with a done job and a formula-like note,
    # one unverified visitor from Threads.
    flow.request_link("lead@example.com", newsletter=True, utm_source="linkedin", utm_medium="social")
    flow.confirm(flow.latest_token("lead@example.com"))
    flow.upload_job(scheme="cress", stage="exploring", notes="=HYPERLINK(\"http://x\")", site_label="Lot 7")
    jobs.run_once(settings)
    make_flow().request_link("lurker@example.com", utm_source="threads")

    overview = flow.client.get("/admin/", headers=auth)
    assert overview.status_code == 200 and "Channel performance" in overview.text
    assert "linkedin" in overview.text and "threads" in overview.text
    subs = flow.client.get("/admin/subscribers", headers=auth)
    assert subs.status_code == 200 and "lead@example.com" in subs.text and "lurker@example.com" in subs.text
    assert "Channel performance" in subs.text
    leads = flow.client.get("/admin/leads", headers=auth)
    assert leads.status_code == 200 and "lead@example.com" in leads.text and "lurker@example.com" not in leads.text
    assert "CRESS" in leads.text and "Selangor" in leads.text

    news_csv = flow.client.get("/admin/export/newsletter.csv", headers=auth)
    assert news_csv.status_code == 200 and "attachment" in news_csv.headers["content-disposition"]
    news_rows = list(csv.DictReader(io.StringIO(news_csv.text.lstrip("﻿"))))
    assert [r["email"] for r in news_rows] == ["lead@example.com"]
    assert news_rows[0]["unsubscribe_url"].startswith("http://testserver/unsubscribe?u=")

    leads_csv = flow.client.get("/admin/export/leads.csv", headers=auth)
    lead_rows = list(csv.DictReader(io.StringIO(leads_csv.text.lstrip("﻿"))))
    assert len(lead_rows) == 1
    row = lead_rows[0]
    assert row["email"] == "lead@example.com" and row["scheme"] == "cress" and row["state"] == "Selangor"
    assert row["total_area_ha"] == "123.4" and row["kpkt_class1_pct"] == "96.5"
    assert row["notes"].startswith("'=")                     # CSV formula injection neutralised


def test_admin_brute_force_lockout(app_factory):
    flow = app_factory("lockout")
    for _ in range(20):
        assert flow.client.get("/admin/", headers=basic("admin", "nope")).status_code == 401
    good = basic(flow.settings.admin_user, flow.settings.admin_password)
    assert flow.client.get("/admin/", headers=good).status_code == 429
