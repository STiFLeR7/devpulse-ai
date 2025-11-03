from pydantic_settings import BaseSettings
from pydantic import Field


def parse_csv(val: str | None) -> list[str]:
    if not val:
        return []
    return [x.strip() for x in val.split(",") if x.strip()]


def parse_bool(val: str | None) -> bool:
    if not val:
        return False
    return val.lower() in {"1", "true", "yes", "y"}


class Settings(BaseSettings):
    # ---- General ----
    db_path: str = Field(default="./devpulse.sqlite", alias="DB_PATH")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    timezone: str = Field(default="Asia/Kolkata", alias="TIMEZONE")

    # Optional UI/labeling
    phase_label_raw: str = Field(default="", alias="PHASE_LABEL")  # e.g., "Phase 1", "Weekly Digest"
    brand_name: str = Field(default="devpulse-ai", alias="BRAND_NAME")
    brand_url: str = Field(default="http://127.0.0.1:8000", alias="BRAND_URL")

    # ---- API Keys ----
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")

    # ---- GitHub (raw envs) ----
    github_orgs_raw: str = Field(default="", alias="GITHUB_ORGS")
    github_users_raw: str = Field(default="", alias="GITHUB_USERS")
    github_repos_raw: str = Field(default="", alias="GITHUB_REPOS")

    github_discovery_limit_raw: str = Field(default="30", alias="GITHUB_DISCOVERY_LIMIT")
    github_per_repo_limit_raw: str = Field(default="20", alias="GITHUB_PER_REPO_LIMIT")

    github_use_watching_raw: str = Field(default="true", alias="GITHUB_USE_WATCHING")
    github_use_stars_raw: str = Field(default="true", alias="GITHUB_USE_STARS")
    github_use_following_raw: str = Field(default="true", alias="GITHUB_USE_FOLLOWING")
    github_fallback_to_tags_raw: str = Field(default="true", alias="GITHUB_FALLBACK_TO_TAGS")

    # ---- HuggingFace (raw envs) ----
    hf_authors_raw: str = Field(default="", alias="HF_AUTHORS")
    hf_model_tags_raw: str = Field(default="", alias="HF_MODEL_TAGS")
    hf_dataset_tags_raw: str = Field(default="", alias="HF_DATASET_TAGS")
    hf_limit_raw: str = Field(default="40", alias="HF_LIMIT")

    # ---- Medium (raw envs) ----
    medium_feeds_raw: str = Field(default="", alias="MEDIUM_FEEDS")

    # ---- Bridge / Public base ----
    bridge_public_base: str = Field(default="http://127.0.0.1:8000", alias="BRIDGE_PUBLIC_BASE")

    # ---- Digest controls ----
    digest_limit_raw: str = Field(default="50", alias="DIGEST_LIMIT")

    # ----------------- PARSED PROPERTIES -----------------

    # Labels / UI
    @property
    def phase_label(self) -> str:
        return self.phase_label_raw.strip()

    # GitHub
    @property
    def github_orgs(self) -> list[str]:
        return parse_csv(self.github_orgs_raw)

    @property
    def github_users(self) -> list[str]:
        return parse_csv(self.github_users_raw)

    @property
    def github_repos(self) -> list[str]:
        return parse_csv(self.github_repos_raw)

    @property
    def github_discovery_limit(self) -> int:
        try:
            return int(self.github_discovery_limit_raw)
        except Exception:
            return 30

    @property
    def github_per_repo_limit(self) -> int:
        try:
            return int(self.github_per_repo_limit_raw)
        except Exception:
            return 20

    @property
    def github_use_watching(self) -> bool:
        return parse_bool(self.github_use_watching_raw)

    @property
    def github_use_stars(self) -> bool:
        return parse_bool(self.github_use_stars_raw)

    @property
    def github_use_following(self) -> bool:
        return parse_bool(self.github_use_following_raw)

    @property
    def github_fallback_to_tags(self) -> bool:
        return parse_bool(self.github_fallback_to_tags_raw)

    # HF
    @property
    def hf_authors(self) -> list[str]:
        return parse_csv(self.hf_authors_raw)

    @property
    def hf_model_tags(self) -> list[str]:
        return parse_csv(self.hf_model_tags_raw)

    @property
    def hf_dataset_tags(self) -> list[str]:
        return parse_csv(self.hf_dataset_tags_raw)

    @property
    def hf_limit(self) -> int:
        try:
            return int(self.hf_limit_raw)
        except Exception:
            return 40

    # Medium
    @property
    def medium_feeds(self) -> list[str]:
        return parse_csv(self.medium_feeds_raw)

    # Digest
    @property
    def digest_limit(self) -> int:
        try:
            return int(self.digest_limit_raw)
        except Exception:
            return 50

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
