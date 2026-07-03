from app.core.config import Settings


def test_settings_defaults_when_no_env_vars():
    settings = Settings(_env_file=None)
    assert settings.database_url == "sqlite:///./resume_tailor.db"
    assert settings.storage_root == "./storage"
    assert settings.hiring_agent_service_url == "http://localhost:8100"
    assert settings.gemini_api_key is None


def test_settings_reads_env_vars(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql://user:pass@localhost/db"
    assert settings.gemini_api_key == "test-gemini-key"
