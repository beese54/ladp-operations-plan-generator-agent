from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from anthropic import Anthropic
from openai import OpenAI


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # Together.ai
    together_api_key: str = ""
    together_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    together_base_url: str = "https://api.together.xyz/v1"

    # Neo4j
    neo4j_uri: str = ""
    neo4j_username: str = "neo4j"
    neo4j_password: str = ""

    # ChromaDB
    chroma_persist_dir: str = "./data/chroma_db"

    # SQLite
    sqlite_db_path: str = "./data/calendar.db"

    # FastAPI
    fastapi_host: str = "0.0.0.0"
    fastapi_port: int = 8000

    # Logging
    log_level: str = "INFO"

    # Per-agent LLM provider overrides (env: AGENT_PROVIDER_SOP_AGENT etc.)
    agent_provider_sop_agent: Literal["anthropic", "together"] = "together"
    agent_provider_historical_agent: Literal["anthropic", "together"] = "together"
    agent_provider_general_response: Literal["anthropic", "together"] = "together"

    @property
    def agent_providers(self) -> dict[str, str]:
        return {
            "intent_parser":       "anthropic",
            "neo4j_agent":         "anthropic",
            "ops_plan_generator":  "anthropic",
            "orchestrator_resp":   "anthropic",
            "sop_agent":           self.agent_provider_sop_agent,
            "historical_agent":    self.agent_provider_historical_agent,
            "general_response":    self.agent_provider_general_response,
            "calendar_agent":      "none",
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def get_anthropic_client() -> Anthropic:
    return Anthropic(api_key=get_settings().anthropic_api_key)


def get_together_client() -> OpenAI:
    s = get_settings()
    return OpenAI(api_key=s.together_api_key, base_url=s.together_base_url)


def get_llm_client(agent_name: str) -> Anthropic | OpenAI | None:
    """Return the correct LLM client for the given agent, or None for deterministic agents."""
    provider = get_settings().agent_providers.get(agent_name, "anthropic")
    if provider == "anthropic":
        return get_anthropic_client()
    if provider == "together":
        return get_together_client()
    return None
