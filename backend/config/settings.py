"""Application settings loaded from environment variables via pydantic-settings."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env at project root or backend directory (whichever exists)
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_ENV_FILES = [str(p) for p in (_PROJECT_ROOT / ".env", _BACKEND_DIR / ".env") if p.exists()]


class Settings(BaseSettings):
    """Central configuration for the GitHub AI Engineer backend."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES or [".env"],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------ App
    app_name: str = "GitHub AI Engineer"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # ------------------------------------------------------------------ LLM
    llm_provider: Literal["ollama"] = "ollama"

    # Ollama Configuration
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:0.5b"

    # Agent loop limits
    llm_max_tool_iterations: Annotated[int, Field(ge=1, le=30)] = 8
    llm_request_delay_seconds: Annotated[float, Field(ge=0.0)] = 1.0
    llm_max_retries: Annotated[int, Field(ge=0, le=5)] = 1

    # ------------------------------------------------------------------ GitHub MCP
    github_token: str | None = Field(
        default=None, alias="GITHUB_PERSONAL_ACCESS_TOKEN"
    )
    github_mcp_enabled: bool = True
    github_mcp_use_docker: bool = False

    # ------------------------------------------------------------------ Filesystem MCP
    filesystem_mcp_enabled: bool = True
    filesystem_allowed_path: Path = Field(default=Path("."))

    # ------------------------------------------------------------------ Git MCP
    git_mcp_enabled: bool = True
    git_repository_path: Path = Field(default=Path("."))

    # ------------------------------------------------------------------ Session
    # Max conversations kept in memory per server restart
    max_sessions: Annotated[int, Field(ge=1)] = 100
    session_ttl_minutes: Annotated[int, Field(ge=1)] = 120

    # ------------------------------------------------------------------ CORS
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # ------------------------------------------------------------------ Properties

    @property
    def project_root(self) -> Path:
        """Repository root used for resolving relative MCP paths."""
        return _PROJECT_ROOT

    def resolve_project_path(self, path: Path) -> Path:
        """Resolve relative paths from the repository root, not the shell cwd."""
        if path.is_absolute():
            return path.resolve()
        return (_PROJECT_ROOT / path).resolve()

    # ------------------------------------------------------------------ Validators

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: object) -> object:
        if isinstance(value, str):
            norm = value.strip().lower()
            if norm in {"release", "prod", "production", "false", "0"}:
                return False
            if norm in {"debug", "dev", "development", "true", "1"}:
                return True
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        """Allow CORS_ORIGINS as a JSON array string or comma-separated list."""
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                import json
                try:
                    return json.loads(value)
                except Exception:
                    pass
            return [o.strip() for o in value.split(",") if o.strip()]
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings singleton (constructed once at first call)."""
    return Settings()
