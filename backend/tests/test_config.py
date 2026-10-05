import pytest

from app.core.config import ConfigError, load_settings


def test_missing_vars_listed(monkeypatch):
    for n in ("DATABASE_URL", "SUPABASE_JWKS_URL", "CREDENTIAL_ENCRYPTION_KEY"):
        monkeypatch.delenv(n, raising=False)
    with pytest.raises(ConfigError) as e:
        load_settings()
    assert "DATABASE_URL" in str(e.value) and "SUPABASE_JWKS_URL" in str(e.value)


def test_admin_emails_lowercased(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "A@x.com, b@y.com")
    s = load_settings([])
    assert s.admin_emails == ["a@x.com", "b@y.com"]
