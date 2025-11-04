from __future__ import annotations
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


def _split_csv(s: Optional[str]) -> list[str]:
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


class Settings(BaseSettings):
    # ----- runtime -----
    ENV: str = Field(default="dev")
    # ----- AgentLightning (optional) -----
    AGENTLIGHTNING_URL: str | None = Field(default=None, alias="AGENTLIGHTNING_URL")
    AGENTLIGHTNING_KEY: str | None = Field(default=None, alias="AGENTLIGHTNING_KEY")


    # ----- Supabase (REST) -----
    SUPABASE_URL: str = Field(..., alias="SUPABASE_URL")
    SUPABASE_SERVICE_ROLE: Optional[str] = Field(default=None, alias="SUPABASE_SERVICE_ROLE")
    SUPABASE_KEY: Optional[str] = Field(default=None, alias="SUPABASE_KEY")   # fallback var
    SUPABASE_DB_URL: Optional[str] = Field(default=None, alias="SUPABASE_DB_URL")
    FORCE_SUPABASE_REST: bool = Field(default=True, alias="FORCE_SUPABASE_REST")

    # ----- Integrations -----
    GEMINI_API_KEY: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    GITHUB_TOKEN: Optional[str] = Field(default=None, alias="GITHUB_TOKEN")
    HF_TOKEN: Optional[str] = Field(default=None, alias="HF_TOKEN")
    N8N_WEBHOOK_URL: str = Field(default="http://localhost:5678/webhook/devpulse/new-signal", alias="N8N_WEBHOOK_URL")

    # ----- Scoring / alerts -----
    ALERT_SCORE_THRESHOLD: float = Field(default=0.80, alias="ALERT_SCORE_THRESHOLD")

    # ----- Embeddings (placeholder) -----
    HF_EMBED_MODEL: str = Field(default="sentence-transformers/all-MiniLM-L6-v2", alias="HF_EMBED_MODEL")

    # ----- Source lists from env as CSV STRINGS (avoid JSON decoding) -----
    GITHUB_REPOS_CSV: Optional[str] = Field(default=None, alias="GITHUB_REPOS")
    HF_MODELS_CSV: Optional[str] = Field(default=None, alias="HF_MODELS")
    HF_DATASETS_CSV: Optional[str] = Field(default=None, alias="HF_DATASETS")
    MEDIUM_FEEDS_CSV: Optional[str] = Field(default=None, alias="MEDIUM_FEEDS")

    model_config = {"env_file": ".env", "extra": "ignore"}

    # ----- Helpers -----
    @property
    def SUPABASE_JWT(self) -> str:
        # single source of truth for REST auth header
        return (self.SUPABASE_SERVICE_ROLE or self.SUPABASE_KEY or "").strip()

    # Computed lists (stable across pydantic v1/v2)
    @property
    def GITHUB_REPOS(self) -> list[str]:
        return _split_csv(self.GITHUB_REPOS_CSV)

    @property
    def HF_MODELS(self) -> list[str]:
        return _split_csv(self.HF_MODELS_CSV)

    @property
    def HF_DATASETS(self) -> list[str]:
        return _split_csv(self.HF_DATASETS_CSV)

    @property
    def MEDIUM_FEEDS(self) -> list[str]:
        return _split_csv(self.MEDIUM_FEEDS_CSV)


settings = Settings()
