"""Configuration from the environment (`CHESHIRE_*`). Never hardcode provider or models."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHESHIRE_", env_file=".env", extra="ignore")

    # API and workers connect as `cheshire_app` (no DDL); migrations as the owner.
    database_url: str = "postgresql://cheshire_app:cheshire_app@localhost:5432/cheshire"
    owner_database_url: str = "postgresql://cheshire:cheshire@localhost:5432/cheshire"
    app_db_password: SecretStr | None = None  # set on the `cheshire_app` role by migrate-db

    language: str = "en"
    llm_provider: str = "openai"
    llm_api_key: SecretStr | None = None
    # OpenAI-compatible endpoint; point it at a local server to use a local model.
    llm_base_url: str = "https://api.openai.com/v1"
    # Models are configuration, never code (open item: choose them per role).
    llm_interpreter_model: str = ""
    llm_writer_model: str = ""
    llm_interviewer_model: str = ""
    llm_mediator_model: str = ""
    llm_timeout_seconds: float = 60.0

    # Authentication (D26): local accounts, server-side sessions in HttpOnly cookies.
    cookie_secure: bool = True  # set false only for plain-http local development
    session_ttl_hours: int = 12
    invitation_ttl_days: int = 7
    login_max_failures: int = 5
    login_window_minutes: int = 15
    min_password_length: int = 12

    # Catalog maintenance (docs/features/catalog-maintenance.md)
    claim_ttl_days: int = 7  # a work-queue claim expires after this long unless renewed
    claim_warning_hours: int = 24  # "expiring soon" threshold shown to the claimer
    impact_recent_consultations: int = 20  # consultations replayed by the impact preview
    starter_pack_dir: str = ""  # defaults to the repository's `catalog/` directory

    # Discussions (docs/features/discussions.md)
    discussion_nudge_days: int = 7  # remind the decider after this long without activity
