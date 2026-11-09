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


# ----------------------------------------------------------------------------
# python -m app.manage test-email (run on the server by `sudo terrain-tool test-email`)
# ----------------------------------------------------------------------------

AWS_KEYS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")


def production_env_file(tmp_path):
    env = tmp_path / "terrain-tool.env"
    env.write_text(
        "APP_ENV=production\n"
        "BASE_URL=https://tools.example.com\n"
        f"SECRET_KEY={'s' * 64}\n"
        f"DATA_DIR={tmp_path / 'data'}\n"
        "MAIL_BACKEND=ses\n"
        "SES_REGION=ap-southeast-5\n"
        "MAIL_FROM=EcoEnergy Consultancy <no-reply@ecoconsultancy.services>\n"
        "# AWS keys written by `terrain-tool set-aws-keys`\n"
        "AWS_ACCESS_KEY_ID=AKIAEXAMPLEEXAMPLE12\n"
        "AWS_SECRET_ACCESS_KEY=secret/example+key\n",
        encoding="utf-8")
    return env


def fake_boto3(monkeypatch, send):
    calls = {}

    class FakeClient:
        def send_email(self, **kwargs):
            import os
            calls["keys"] = tuple(os.environ.get(k) for k in AWS_KEYS)   # what boto3 would read
            calls["send"] = kwargs
            return send(**kwargs)

    def client(service, region_name=None):
        calls["client"] = (service, region_name)
        return FakeClient()

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=client))
    for key in AWS_KEYS:                       # restored at teardown, even if set by the command
        monkeypatch.setenv(key, "placeholder")
        monkeypatch.delenv(key)
    return calls


def test_manage_test_email_uses_the_server_env_file(tmp_path, monkeypatch, capsys):
    from app import manage

    calls = fake_boto3(monkeypatch, lambda **kw: {"MessageId": "m-1"})
    rc = manage.main(["test-email", "me@example.com", "--env-file", str(production_env_file(tmp_path))])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert calls["client"] == ("sesv2", "ap-southeast-5")
    assert calls["keys"] == ("AKIAEXAMPLEEXAMPLE12", "secret/example+key")
    assert calls["send"]["Destination"] == {"ToAddresses": ["me@example.com"]}
    assert calls["send"]["FromEmailAddress"] == "EcoEnergy Consultancy <no-reply@ecoconsultancy.services>"
    assert message_from_bytes(calls["send"]["Content"]["Raw"]["Data"])["Subject"] == manage.TEST_EMAIL_SUBJECT
    assert "Amazon SES (ap-southeast-5)" in out and "Sent." in out


def test_manage_test_email_explains_ses_errors(tmp_path, monkeypatch, capsys):
    from app import manage

    class ClientError(Exception):            # shape of botocore.exceptions.ClientError
        def __init__(self, code, message):
            super().__init__(f"An error occurred ({code}) when calling the SendEmail operation: {message}")
            self.response = {"Error": {"Code": code, "Message": message}}

    class NoCredentialsError(Exception):
        pass

    env = str(production_env_file(tmp_path))
    cases = [
        (ClientError("MessageRejected", "Email address is not verified. The following identities failed "
                                        "the check in region AP-SOUTHEAST-5: me@example.com"), "sandbox"),
        (ClientError("InvalidClientTokenId", "The security token included in the request is invalid."),
         "does not recognise the access key ID"),
        (ClientError("SignatureDoesNotMatch", "..."), "secret access key does not match"),
        (ClientError("AccessDeniedException", "not authorized to perform ses:SendRawEmail"), "terrain-tool-ses"),
        (NoCredentialsError("Unable to locate credentials"), "sudo terrain-tool set-aws-keys"),
    ]
    for exc, expected in cases:
        def fail(_exc=exc, **kw):
            raise _exc
        fake_boto3(monkeypatch, fail)
        rc = manage.main(["test-email", "me@example.com", "--env-file", env])
        err = capsys.readouterr().err
        assert rc == 1 and err.startswith("FAILED: ") and expected in err, err
        assert "Traceback" not in err
