from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict
from openai import AzureOpenAI, OpenAI


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Azure OpenAI
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-12-01-preview"
    azure_openai_chat_deployment_name: str = "gpt-5.4-mini-pub"

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
    agent_provider_sop_agent: Literal["azure", "together"] = "together"
    agent_provider_historical_agent: Literal["azure", "together"] = "together"
    agent_provider_general_response: Literal["azure", "together"] = "azure"

    @property
    def agent_providers(self) -> dict[str, str]:
        return {
            "intent_parser":       "azure",
            "neo4j_agent":         "azure",
            "ops_plan_generator":  "azure",
            "orchestrator_resp":   "azure",
            "sop_agent":           self.agent_provider_sop_agent,
            "historical_agent":    self.agent_provider_historical_agent,
            "general_response":    self.agent_provider_general_response,
            "calendar_agent":      "none",
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def get_azure_openai_client() -> AzureOpenAI:
    s = get_settings()
    return AzureOpenAI(
        api_key=s.azure_openai_api_key,
        azure_endpoint=s.azure_openai_endpoint,
        api_version=s.azure_openai_api_version,
    )


def get_together_client() -> OpenAI:
    s = get_settings()
    return OpenAI(api_key=s.together_api_key, base_url=s.together_base_url)


def get_llm_client(agent_name: str) -> AzureOpenAI | OpenAI | None:
    """Return the correct LLM client for the given agent, or None for deterministic agents."""
    provider = get_settings().agent_providers.get(agent_name, "azure")
    if provider == "azure":
        return get_azure_openai_client()
    if provider == "together":
        return get_together_client()
    return None
