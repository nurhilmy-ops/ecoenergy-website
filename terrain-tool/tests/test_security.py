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
from conftest import rows as rows_for
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
    token = make_unsubscribe_token(settings, 42, "a@example.com")
    assert verify_unsubscribe_token(settings, token, "a@example.com") == 42
    sid, sig = token.split(".")
    assert verify_unsubscribe_token(settings, f"43.{sig}", "a@example.com") is None
    assert verify_unsubscribe_token(settings, f"{sid}.{sig[:-1]}A", "a@example.com") is None
    assert verify_unsubscribe_token(settings, "garbage", "a@example.com") is None
    # Bound to the address: the same id signed for someone else does not verify.
    assert verify_unsubscribe_token(settings, token, "b@example.com") is None
    assert security.unsubscribe_token_id(token) == 42 and security.unsubscribe_token_id("x.y") is None
    headers = newsletter_headers(settings, 42, "a@example.com")
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
    two_hops = app_factory("ip3", trust_proxy_headers=True, trusted_proxy_hops=2).settings
    assert client_ip(Request(scope), untrusted) == "10.0.0.2"
    # One proxy of ours appended the address it saw (right-most); the left part is unverified.
    assert client_ip(Request(scope), trusted) == "10.0.0.1"
    # Two proxies of ours (e.g. Cloudflare in front of nginx): the client is two hops from the right.
    assert client_ip(Request(scope), two_hops) == "203.0.113.9"


def test_forged_x_forwarded_for_cannot_dodge_per_ip_limits(app_factory):
    """appsec-1: behind an appending proxy the left-most X-Forwarded-For hop is whatever the
    client sent. Rotating it must not reset the admin brute-force throttle (or any per-IP limit)."""
    from starlette.requests import Request

    flow = app_factory("xff", trust_proxy_headers=True)
    real = "198.51.100.7"
    statuses = []
    for i in range(25):
        forged = f"10.{i}.{i}.{i}"
        statuses.append(flow.client.get("/admin/leads", headers={
            **basic("admin", f"wrong-{i}"), "X-Forwarded-For": f"{forged}, {real}"}).status_code)
    assert statuses[:20] == [401] * 20 and set(statuses[20:]) == {429}
    # Garbage in the trusted position falls back to the peer address instead of becoming a key.
    scope = {"type": "http", "headers": [(b"x-forwarded-for", b"1.2.3.4, not-an-ip")],
             "client": ("10.0.0.2", 1234)}
    assert client_ip(Request(scope), flow.settings) == "10.0.0.2"
    short = {"type": "http", "headers": [(b"x-forwarded-for", b"1.2.3.4")], "client": ("10.0.0.2", 1)}
    two_hops = app_factory("xff2", trust_proxy_headers=True, trusted_proxy_hops=2).settings
    assert client_ip(Request(short), two_hops) == "10.0.0.2"


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
    token = make_unsubscribe_token(settings, sub_id, "news@example.com")

    mail_provider = make_flow()                  # no cookies, foreign Origin, no CSRF token
    page = mail_provider.client.get(f"/unsubscribe?u={token}")
    assert page.status_code == 200 and "Unsubscribe from EcoEnergy insights?" in page.text
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "subscribed"

    # A forged signature gets the same neutral answer as an unknown id, and changes nothing.
    tampered = mail_provider.client.post(f"/unsubscribe?u={sub_id}.AAAA", data={"List-Unsubscribe": "One-Click"})
    assert tampered.status_code == 200
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "subscribed"
    assert mail_provider.client.post("/unsubscribe?u=garbage", data={}).status_code == 400

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


def test_old_unsubscribe_link_of_erased_subscriber_never_touches_reused_id(make_flow, query, settings, client):
    """PDPA-3: SQLite reuses the highest id after a delete; an erased person's old link must not
    unsubscribe the next sign-up or write a withdrawal into their ledger."""
    first = make_flow()
    first.login("first@example.com", newsletter=True)
    sid = query("SELECT id FROM subscribers")[0]["id"]
    old_link = security.unsubscribe_url(settings, sid, "first@example.com")
    first.client.post("/account/delete", data={"csrf": first.csrf(), "confirm": "yes"})
    second = make_flow()
    second.login("second@example.com", newsletter=True)
    assert query("SELECT id FROM subscribers")[0]["id"] == sid           # the id was reused
    path = old_link.split("testserver", 1)[1]
    assert client.get(path).status_code == 200                            # same neutral page
    resp = client.post(path, data={"List-Unsubscribe": "One-Click"})
    assert resp.status_code == 200
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "subscribed"
    assert query("SELECT * FROM consents WHERE action = 'withdrawn'") == []
    # The second person's own link (as exported in newsletter.csv) still works.
    own = security.unsubscribe_url(settings, sid, "second@example.com").split("testserver", 1)[1]
    client.post(own, data={"List-Unsubscribe": "One-Click"})
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "unsubscribed"


def _newsletter_actions(query) -> list[str]:
    return [r["action"] for r in query("SELECT action FROM consents WHERE purpose = 'newsletter' ORDER BY id")]


def test_third_party_newsletter_tick_is_not_confirmed_by_the_victims_own_sign_in(make_flow, query, client):
    """appsec-5 / PDPA-1: an address typed in by someone else with the newsletter box ticked
    must not be subscribed by the owner's later, unticked sign-in, nor reach newsletter.csv."""
    victim, attacker = make_flow(), make_flow()
    victim.login("victim@example.com", newsletter=True)
    victim.client.post("/account/newsletter", data={"csrf": victim.csrf(), "action": "unsubscribe"})
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "unsubscribed"

    attacker.client.headers["user-agent"] = "EvilBot/1.0"
    attacker.request_link("victim@example.com", newsletter=True)
    # An unauthenticated request does not overwrite the recorded decision.
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "unsubscribed"

    victim.request_link("victim@example.com")                              # box unticked
    assert victim.confirm(victim.latest_token("victim@example.com")).status_code == 303
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "unsubscribed"
    assert _newsletter_actions(query) == ["granted", "confirmed", "withdrawn", "granted"]
    csv_text = client.get("/admin/export/newsletter.csv", headers=basic("admin", "correct horse battery")).text
    assert "victim@example.com" not in csv_text


def test_pending_newsletter_is_confirmed_only_by_the_link_sent_with_it(flow, make_flow, query, settings):
    """A pending tick is not confirmed by an unticked link or the report-ready link; the
    ticked link itself still confirms it (double opt-in), and says so."""
    other = make_flow()
    other.request_link("owner@example.com", newsletter=True)              # someone ticks for them
    ticked_token = other.latest_token("owner@example.com")
    ticked_mail = flow.mails("owner@example.com")[-1]
    assert "newsletter box ticked" in ticked_mail["text_body"]
    assert "confirms your subscription" in ticked_mail["html_body"]
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "pending"

    flow.login("owner@example.com")                                        # unticked link
    assert "newsletter box ticked" not in flow.mails("owner@example.com")[-1]["text_body"]
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "pending"
    flow.upload_job()
    jobs.run_once(settings)                                                # report-ready mail + link
    ready = [m for m in flow.mails("owner@example.com") if "ready" in m["subject"]][-1]
    flow.client.cookies.clear()
    assert flow.confirm(flow.token_from(ready)).status_code == 303
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "pending"
    assert _newsletter_actions(query) == ["granted"]

    # The account page offers to cancel the pending request.
    page = flow.client.get("/account").text
    assert "Cancel the pending subscription" in page

    start = flow.client.get(f"/start?t={ticked_token}").text
    assert "also confirms your subscription" in start
    assert flow.confirm(ticked_token).status_code == 303
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "subscribed"
    assert _newsletter_actions(query) == ["granted", "confirmed"]


def test_cancelled_pending_newsletter_cannot_be_confirmed_later(flow, make_flow, query):
    other = make_flow()
    other.request_link("cancel@example.com", newsletter=True)
    ticked_token = other.latest_token("cancel@example.com")
    flow.login("cancel@example.com")
    flow.client.post("/account/newsletter", data={"csrf": flow.csrf(), "action": "unsubscribe"})
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "unsubscribed"
    flow.client.cookies.clear()
    assert flow.confirm(ticked_token).status_code == 303
    assert query("SELECT newsletter_status FROM subscribers")[0]["newsletter_status"] == "unsubscribed"
    assert _newsletter_actions(query) == ["granted", "withdrawn"]


def test_privacy_notice_names_cloudflare_whenever_the_landing_page_loads_it(app_factory):
    """PDPA-8: with only the site key set the landing page loads Turnstile from Cloudflare,
    so the notice must disclose Cloudflare too."""
    flow = app_factory("ts", turnstile_site_key="site-key-only")
    landing = flow.client.get("/").text
    assert "challenges.cloudflare.com/turnstile" in landing
    assert "Cloudflare" in flow.client.get("/privacy").text
    plain = app_factory("ts-off")
    assert "challenges.cloudflare.com" not in plain.client.get("/").text
    assert "Cloudflare" not in plain.client.get("/privacy").text


@pytest.fixture
def secure_delete_off_by_default(monkeypatch):
    """Simulate an SQLite built without SQLITE_SECURE_DELETE (the compile-time default, e.g. the
    python.org Windows and macOS builds): every new connection starts with secure_delete OFF."""
    import sqlite3

    real = sqlite3.connect

    def connect(*args, **kwargs):
        conn = real(*args, **kwargs)
        conn.execute("PRAGMA secure_delete = OFF")
        return conn

    monkeypatch.setattr(sqlite3, "connect", connect)


def test_database_overwrites_deleted_content(settings, secure_delete_off_by_default):
    """PDPA-7: secure_delete is on for every connection, whatever SQLite's build default."""
    with db(settings.db_path) as conn:
        assert conn.execute("PRAGMA secure_delete").fetchone()[0] == 1


def test_erased_data_is_not_left_in_the_database_file(flow, settings, secure_delete_off_by_default):
    flow.login("remnant.person@example.com")
    flow.upload_job(site_label="SECRET-LANDOWNER-LABEL")
    jobs.run_once(settings)
    flow.client.post("/account/delete", data={"csrf": flow.csrf(), "confirm": "yes"})
    with db(settings.db_path) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    raw = settings.db_path.read_bytes()
    assert b"remnant.person@example.com" not in raw and b"SECRET-LANDOWNER-LABEL" not in raw


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

    # Data: one subscribed lead from LinkedIn with two screenings — one with staff follow-up
    # ticked and a formula-like note, one without — and one unverified visitor from Threads.
    flow.request_link("lead@example.com", newsletter=True, utm_source="linkedin", utm_medium="social")
    flow.confirm(flow.latest_token("lead@example.com"))
    flow.upload_job(scheme="cress", stage="exploring", notes="=HYPERLINK(\"http://x\")", site_label="Lot 7",
                    followup="yes")
    jobs.run_once(settings)
    flow.upload_job(scheme="lss", site_label="Quiet parcel")
    jobs.run_once(settings)
    make_flow().request_link("lurker@example.com", utm_source="threads")

    overview = flow.client.get("/admin/", headers=auth)
    assert overview.status_code == 200 and "Channel performance" in overview.text
    assert "linkedin" in overview.text and "threads" in overview.text
    assert "Follow-up allowed" in overview.text
    subs = flow.client.get("/admin/subscribers", headers=auth)
    assert subs.status_code == 200 and "lead@example.com" in subs.text and "lurker@example.com" in subs.text
    assert "Channel performance" in subs.text
    leads = flow.client.get("/admin/leads", headers=auth)
    assert leads.status_code == 200 and "lead@example.com" in leads.text and "lurker@example.com" not in leads.text
    assert "CRESS" in leads.text and "Selangor" in leads.text
    # One row per screening, each with a clear Follow-up yes/no; "Do not contact" on the no.
    body = leads.text[leads.text.index("<tbody>"):]
    assert body.count("<tr>") == 2
    assert body.count('<span class="yes">Yes</span>') == 1
    assert body.count('<span class="no">No</span>') == 1 and body.count("Do not contact") == 1
    assert "contains only screenings whose follow-up consent is currently granted" in leads.text

    news_csv = flow.client.get("/admin/export/newsletter.csv", headers=auth)
    assert news_csv.status_code == 200 and "attachment" in news_csv.headers["content-disposition"]
    news_rows = list(csv.DictReader(io.StringIO(news_csv.text.lstrip("\ufeff"))))
    assert [r["email"] for r in news_rows] == ["lead@example.com"]
    assert news_rows[0]["unsubscribe_url"].startswith("http://testserver/unsubscribe?u=")

    # The leads CSV carries only the screening with follow-up granted.
    leads_csv = flow.client.get("/admin/export/leads.csv", headers=auth)
    lead_rows = list(csv.DictReader(io.StringIO(leads_csv.text.lstrip("\ufeff"))))
    assert len(lead_rows) == 1
    row = lead_rows[0]
    assert row["email"] == "lead@example.com" and row["scheme"] == "cress" and row["state"] == "Selangor"
    assert row["site_label"] == "Lot 7" and row["followup_granted_at"]
    assert row["followup_notice_version"] == settings.notice_version
    assert row["total_area_ha"] == "123.4" and row["kpkt_class1_pct"] == "96.5"
    assert row["notes"].startswith("'=")                     # CSV formula injection neutralised

    # Withdrawing follow-up removes the screening from the CSV at once; the newsletter CSV is
    # unaffected (separate consent).
    job_id = rows_for(settings, "SELECT id FROM jobs WHERE followup_consent = 1")[0]["id"]
    flow.client.post(f"/reports/{job_id}/followup", data={"csrf": flow.csrf(), "action": "withdraw"})
    leads_csv = flow.client.get("/admin/export/leads.csv", headers=auth)
    assert list(csv.DictReader(io.StringIO(leads_csv.text.lstrip("\ufeff")))) == []
    news_csv = flow.client.get("/admin/export/newsletter.csv", headers=auth)
    assert len(list(csv.DictReader(io.StringIO(news_csv.text.lstrip("\ufeff"))))) == 1
    leads = flow.client.get("/admin/leads", headers=auth)
    assert leads.text.count("Do not contact") >= 2


def test_admin_leads_csv_skips_unverified_deleted_and_legacy_bundled_consent(flow, settings):
    """A screening whose report was deleted, or whose only follow-up record is the old bundled
    account-level grant (job_id NULL, before consent was unbundled), is not exported."""
    auth = basic(settings.admin_user, settings.admin_password)
    flow.login("legacy@example.com")
    kept = flow.upload_job(followup="yes")
    deleted = flow.upload_job(followup="yes")
    legacy = flow.upload_job()
    jobs.run_once(settings)
    flow.client.post(f"/reports/{deleted}/delete", data={"csrf": flow.csrf()})
    with db(settings.db_path) as conn:
        sub_id = conn.execute("SELECT id FROM subscribers").fetchone()["id"]
        conn.execute("INSERT INTO consents (subscriber_id, purpose, action, notice_version, wording, created_at) "
                     "VALUES (?, 'site_followup', 'granted', '2026-10-draft-1', 'old bundled wording', '2026-10-01')",
                     (sub_id,))
    leads_csv = flow.client.get("/admin/export/leads.csv", headers=auth)
    lead_rows = list(csv.DictReader(io.StringIO(leads_csv.text.lstrip("\ufeff"))))
    assert len(lead_rows) == 1
    assert rows_for(settings, "SELECT followup_consent FROM jobs WHERE id = ?", (kept,))[0]["followup_consent"] == 1
    assert rows_for(settings, "SELECT followup_consent FROM jobs WHERE id = ?", (legacy,))[0]["followup_consent"] == 0


def test_admin_brute_force_lockout(app_factory):
    flow = app_factory("lockout")
    for _ in range(20):
        assert flow.client.get("/admin/", headers=basic("admin", "nope")).status_code == 401
    good = basic(flow.settings.admin_user, flow.settings.admin_password)
    assert flow.client.get("/admin/", headers=good).status_code == 429
