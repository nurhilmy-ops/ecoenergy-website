"""Mail transports that do not need a live server."""
from __future__ import annotations

import sys
import types
from dataclasses import replace
from email import message_from_bytes

from app import mailer


def test_ses_backend_sends_raw_mime_via_sesv2(settings, monkeypatch):
    calls = {}

    class FakeClient:
        def send_email(self, **kwargs):
            calls["send"] = kwargs
            return {"MessageId": "m-1"}

    def fake_client(service, region_name=None):
        calls["client"] = (service, region_name)
        return FakeClient()

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=fake_client))
    ses_settings = replace(settings, mail_backend="ses", ses_region="ap-southeast-5")

    mailer.send_mail(ses_settings, "visitor@example.com", "Subject line", "plain body", "<p>html body</p>")

    assert calls["client"] == ("sesv2", "ap-southeast-5")
    sent = calls["send"]
    assert sent["Destination"] == {"ToAddresses": ["visitor@example.com"]}
    assert sent["FromEmailAddress"] == ses_settings.mail_from
    parsed = message_from_bytes(sent["Content"]["Raw"]["Data"])
    assert parsed["Subject"] == "Subject line"
    assert parsed["Reply-To"] == ses_settings.mail_reply_to
    assert parsed.is_multipart()


def test_unknown_backend_is_rejected(settings):
    import pytest

    with pytest.raises(ValueError, match="outbox, smtp or ses"):
        mailer.send_mail(replace(settings, mail_backend="carrier-pigeon"), "a@example.com", "s", "t")
