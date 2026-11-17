import io

import pytest

from app import cli


def test_mfa_enrollment_refuses_captured_stdout_before_updating_database(monkeypatch):
    class Connection:
        called = False

        def execute(self, *_args, **_kwargs):
            self.called = True

    conn = Connection()
    monkeypatch.setattr(cli.sys, "stdout", io.StringIO())
    monkeypatch.setattr(
        cli.security,
        "new_totp_secret",
        lambda: pytest.fail("must reject captured output before generating a secret"),
    )

    with pytest.raises(RuntimeError, match="interactive terminal"):
        cli._enrol_mfa(conn, "user-id", "ops@example.org")

    assert not conn.called
