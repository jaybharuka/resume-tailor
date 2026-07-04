from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./resume_tailor.db"
    storage_root: str = "./storage"
    prompts_root: str = "./prompts"
    gemini_api_key: str | None = None
    nvidia_api_key: str | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    hiring_agent_service_url: str = "http://localhost:8100"


def get_settings() -> Settings:
    return Settings()
