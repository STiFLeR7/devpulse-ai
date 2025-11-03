from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    ENV: str = Field(default="dev")

    SUPABASE_URL: str = Field(..., alias="SUPABASE_URL")
    SUPABASE_SERVICE_ROLE: str = Field(..., alias="SUPABASE_SERVICE_ROLE")

    # optional: if you ever get sockets working again
    SUPABASE_DB_URL: str | None = Field(default=None, alias="SUPABASE_DB_URL")

    FORCE_SUPABASE_REST: bool = Field(default=True, alias="FORCE_SUPABASE_REST")

    # enrichment / alerts
    GEMINI_API_KEY: str = Field(default="", alias="GEMINI_API_KEY")
    GITHUB_TOKEN: str = Field(default="", alias="GITHUB_TOKEN")
    HF_EMBED_MODEL: str = Field(default="sentence-transformers/all-MiniLM-L6-v2")
    ALERT_SCORE_THRESHOLD: float = Field(default=0.80, alias="ALERT_SCORE_THRESHOLD")
    N8N_WEBHOOK_URL: str = Field(default="http://localhost:5678/webhook/devpulse/new-signal")

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
