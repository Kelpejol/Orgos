# =============================================================================
# config.py — OrgOS Application Settings
# Loads all environment variables from .env via pydantic-settings.
# All other modules import `settings` from here — never import os.environ directly.
# Depends on: .env file, pydantic-settings
# =============================================================================

import logging
from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from the .env file.
    All fields map 1:1 to environment variable names.
    pydantic-settings raises a clear error on startup if a required field is missing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore unknown env vars — don't crash
    )

    # ── Microsoft Entra ID ─────────────────────────────────────────────────
    tenant_id: str = Field(..., description="Azure AD tenant ID")
    client_id: str = Field(..., description="OrgOS app registration client ID")
    client_secret: str = Field(..., description="OrgOS app registration client secret")

    # ── SharePoint ─────────────────────────────────────────────────────────
    sharepoint_site_id: str = Field(..., description="SharePoint site ID")
    sharepoint_site_url: str = Field(
        default="https://dragnetnigeria.sharepoint.com/sites/orgos"
    )

    compliance_site_url: str = Field(
    default="https://dragnetnigeria.sharepoint.com/sites/compliance"
)
    compliance_library_name: str = Field(default="Documents")
    compliance_starting_folder: str = Field(default="GRC MASTERY")

    # ── SharePoint List IDs — Tier 1 ──────────────────────────────────────
    document_register_list_id: str = Field(default="placeholder")
    role_register_list_id: str = Field(default="placeholder")
    compliance_calendar_list_id: str = Field(default="placeholder")
    contract_register_list_id: str = Field(default="placeholder")
    ai_review_queue_list_id: str = Field(default="placeholder")
    document_lifecycle_list_id: str = Field(default="placeholder")
    control_register_list_id: str = Field(default="placeholder")
    evidence_tracker_list_id: str = Field(default="placeholder")
    audit_log_list_id: str = Field(default="placeholder")
    strategic_risk_register_list_id: str = Field(default="placeholder")
    gap_analysis_list_id: str = Field(default="placeholder")
    # ── Application ────────────────────────────────────────────────────────
    environment: str = Field(default="development")
    allowed_origins: str = Field(default="http://localhost:5173")
    app_port: int = Field(default=8000)
    log_level: str = Field(default="DEBUG")
    skip_auth: bool = Field(default=False)

    # ── LLM provider ──────────────────────────────────────────────────────
    # Set LLM_PROVIDER=runpod to route all inference to RunPod serverless.
    # Leave as "ollama" (default) to use the local Ollama instance.
    llm_provider: str = Field(default="ollama")   # "ollama" | "runpod"

    # ── Ollama — local inference (used when LLM_PROVIDER=ollama) ──────────
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="llama3")
    ollama_timeout: int = Field(default=120)

    # ── RunPod — serverless inference (used when LLM_PROVIDER=runpod) ─────
    runpod_api_key: str = Field(default="")
    runpod_light_endpoint_id: str = Field(default="")
    runpod_heavy_endpoint_id: str = Field(default="")
    runpod_embed_endpoint_id: str = Field(default="")   # BGE-M3 embedding endpoint
    runpod_timeout: int = Field(default=120)

    # ── Embedding model ───────────────────────────────────────────────────
    # RunPod: BGE-M3 via runpod_embed_endpoint_id (when LLM_PROVIDER=runpod)
    # Ollama: nomic-embed-text (when LLM_PROVIDER=ollama)
    ollama_embed_model: str = Field(default="nomic-embed-text")

    # ── NL Search ─────────────────────────────────────────────────────────
    procedural_steps_list_id: str = Field(default="placeholder")
    chroma_persist_dir: str = Field(default="./chroma_db")

    # ── Azure Document Intelligence — OCR fallback for scanned documents ──
    azure_document_intelligence_endpoint: str = Field(default="")
    azure_document_intelligence_key: str = Field(default="")

    # ── Computed properties ────────────────────────────────────────────────

    @property
    def allowed_origins_list(self) -> List[str]:
        """Parse comma-separated origins into a list."""
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"

    @property
    def graph_token_url(self) -> str:
        """OAuth2 token endpoint for client credentials flow."""
        return (
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        )

    @property
    def graph_base_url(self) -> str:
        return "https://graph.microsoft.com/v1.0"

    @property
    def jwks_uri(self) -> str:
        """Microsoft's public key endpoint for token signature validation."""
        return (
            f"https://login.microsoftonline.com/{self.tenant_id}"
            "/discovery/v2.0/keys"
        )

    @property
    def token_issuer(self) -> str:
        """Expected issuer claim in Entra ID access tokens."""
        return f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"

    @property
    def sharepoint_lists_base(self) -> str:
        """Base URL for SharePoint List operations via Graph API."""
        return (
            f"{self.graph_base_url}/sites/{self.sharepoint_site_id}/lists"
        )

    def is_list_configured(self, list_id: str) -> bool:
        """Return True if a List ID has been replaced from the placeholder default."""
        return list_id != "placeholder" and list_id != ""


@lru_cache()
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.
    lru_cache means .env is only read once per process — safe for production.
    In tests, call get_settings.cache_clear() to reload after patching .env.
    """
    return Settings()


# Module-level singleton — import this everywhere
settings: Settings = get_settings()


def configure_logging() -> None:
    """Configure root logger based on settings. Called once in main.py."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
