"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Support .env at project root or backend/
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_ENV_FILES = (
    _PROJECT_ROOT / ".env",
    _BACKEND_DIR / ".env",
)


class Settings(BaseSettings):
    """Central configuration for the GitHub AI Engineer backend."""

    model_config = SettingsConfigDict(
        env_file=[str(p) for p in _ENV_FILES if p.exists()] or ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "GitHub AI Engineer"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- LLM provider (OpenAI-compatible or Anthropic) ---
    llm_provider: Literal["openai", "anthropic"] = "openai"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-4o"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-20250514"

    # --- GitHub MCP ---
    github_token: str | None = Field(default=None, alias="GITHUB_PERSONAL_ACCESS_TOKEN")
    github_mcp_enabled: bool = True
    github_mcp_use_docker: bool = False

    # --- Filesystem MCP ---
    filesystem_mcp_enabled: bool = True
    filesystem_allowed_path: Path = Field(default=Path("."))

    # --- Git MCP ---
    git_mcp_enabled: bool = True
    git_repository_path: Path = Field(default=Path("."))

    # --- CORS (frontend origin) ---
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
