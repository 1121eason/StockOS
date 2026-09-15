import re
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    qve_database_url: str = "sqlite:///data/qve.db"
    qve_label_database_url: str = "sqlite:///data/labels.db"
    qve_raw_dir: Path = Path("data/raw")
    sec_user_agent: str | None = None

    qve_ai_provider: str | None = None
    qve_ai_model: str | None = None
    qve_ai_model_version: str | None = None
    openai_api_key: str | None = None
    qve_ai_reasoning: str | None = None
    qve_ai_temperature: float | None = None
    qve_claude_model: str = "sonnet"
    qve_claude_executable: str = "claude"
    qve_antigravity_model: str | None = None
    qve_antigravity_executable: str = "agy"
    qve_antigravity_effort: str = "high"
    qve_gemini_model: str = "gemini-2.5-pro"
    qve_gemini_executable: str = "gemini"
    qve_cli_timeout: int = 240

    def require_sec_identity(self) -> str:
        if (
            not self.sec_user_agent
            or "\n" in self.sec_user_agent
            or "\r" in self.sec_user_agent
            or not re.fullmatch(r"[^\r\n]+ [^\s@]+@[^\s@]+\.[^\s@]+", self.sec_user_agent.strip())
        ):
            raise ValueError(
                "SEC_USER_AGENT is required: set a project name and contact email in .env or your environment; no credentials/API key required."
            )
        return self.sec_user_agent.strip()
