"""Application configuration via environment variables and pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScadsConfig(BaseSettings):
    """Configuration for the scads.ai LLM endpoint (OpenAI-compatible)."""

    model_config = SettingsConfigDict(env_prefix="SCADS_")

    api_key: str = Field(default="", description="API key for scads.ai")
    base_url: str = Field(
        default="https://llm.scads.ai/v1",
        description="Base URL of the OpenAI-compatible API",
    )
    model: str = Field(
        default="gpt-4o-mini",
        description="Model identifier to use for LLM classification fallback",
    )
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, gt=0)


class MiningConfig(BaseSettings):
    """Configuration for the vocabulary mining pipeline."""

    model_config = SettingsConfigDict(env_prefix="MINING_")

    max_sources: int = Field(default=50, gt=0)
    max_pages_per_source: int = Field(default=10, gt=0)
    request_timeout: float = Field(default=30.0, gt=0)
    rate_limit_delay: float = Field(
        default=1.0, ge=0, description="Seconds between API requests"
    )


class PDFConfig(BaseSettings):
    """Configuration for PDF worksheet rendering."""

    model_config = SettingsConfigDict(env_prefix="PDF_")

    output_dir: Path = Field(default=Path("./output"))
    page_width: float = Field(default=595.28, description="A4 width in points")
    page_height: float = Field(default=841.89, description="A4 height in points")
    margin: float = Field(default=48.0, description="Page margin in points")
    brand_name: str = "langwich"


class AppConfig(BaseSettings):
    """Root application configuration aggregating all sub-configs."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    spacy_model: str = Field(default="en_core_web_sm")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    scads: ScadsConfig = Field(default_factory=ScadsConfig)
    mining: MiningConfig = Field(default_factory=MiningConfig)
    pdf: PDFConfig = Field(default_factory=PDFConfig)


# Module-level singleton — import and use directly.
settings = AppConfig()
