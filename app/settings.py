from __future__ import annotations

import json
from typing import List, Optional

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _csv_or_json_list(v) -> List[str]:
    """Coerce env input into a list.

    Accepts:
      - list already
      - JSON array string: '["a/b","c/d"]'
      - CSV string:        'a/b,c/d'
      - empty string/None  -> []
    """
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        if s.startswith("[") and s.endswith("]"):
            try:
                arr = json.loads(s)
                if isinstance(arr, list):
                    return [str(x).strip() for x in arr if str(x).strip()]
            except Exception:
                pass
        return [p.strip() for p in s.split(",") if p.strip()]
    return [str(v).strip()]


class Settings(BaseSettings):
    # pydantic v2 settings
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    BASE_URL: AnyHttpUrl = "http://127.0.0.1:8000"
    BRIDGE_SIGNING_SECRET: str = "dev-only"

    # Feature flags
    ENABLE_GITHUB: bool = True
    ENABLE_HF: bool = True
    ENABLE_MEDIUM: bool = True

    # --- GitHub ---
    GITHUB_TOKEN: Optional[str] = None

    # Read the original env var (string) here to avoid list parsing at source.
    # Keep alias exactly "GITHUB_REPOS" so you can set it in .env as before.
    GITHUB_REPOS_RAW: Optional[str] = Field(default=None, alias="GITHUB_REPOS")

    # The actual list field uses a DIFFERENT env var name so DotEnv won't hit it.
    # If you *really* want to provide a pre-parsed list, you can set GITHUB_REPOS_LIST in .env.
    GITHUB_REPOS: List[str] = Field(default_factory=list, alias="GITHUB_REPOS_LIST")

    # --- Hugging Face (limits) ---
    HF_MODELS_LIMIT: int = 30
    HF_DATASETS_LIMIT: int = 30

    # --- Medium ---
    MEDIUM_FEEDS_RAW: Optional[str] = Field(default=None, alias="MEDIUM_FEEDS")
    MEDIUM_FEEDS: List[str] = Field(default_factory=list, alias="MEDIUM_FEEDS_LIST")

    def model_post_init(self, __context) -> None:
        # Coerce the RAW env strings into lists
        if self.GITHUB_REPOS_RAW:
            self.GITHUB_REPOS = _csv_or_json_list(self.GITHUB_REPOS_RAW) or self.GITHUB_REPOS
        if self.MEDIUM_FEEDS_RAW:
            self.MEDIUM_FEEDS = _csv_or_json_list(self.MEDIUM_FEEDS_RAW) or self.MEDIUM_FEEDS


settings = Settings()
