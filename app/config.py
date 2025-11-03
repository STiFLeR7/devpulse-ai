from pydantic_settings import BaseSettings
from pydantic import AnyHttpUrl, Field
from typing import List, Optional

class Settings(BaseSettings):
    BASE_URL: AnyHttpUrl = "http://127.0.0.1:8000"
    BRIDGE_SIGNING_SECRET: str = "dev-only"

    # toggles
    ENABLE_GITHUB: bool = True
    ENABLE_HF: bool = True
    ENABLE_MEDIUM: bool = True

    # GitHub
    GITHUB_TOKEN: Optional[str] = None  # optional, raises rate limits if missing
    GITHUB_REPOS: List[str] = Field(default_factory=list)
    # format: owner/name,owner2/name2

    # HF
    HF_MODELS_LIMIT: int = 40
    HF_DATASETS_LIMIT: int = 40

    # Medium
    MEDIUM_FEEDS: List[str] = Field(default_factory=list)
    # e.g. https://medium.com/feed/@<user>, https://medium.com/feed/tag/<tag>

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
