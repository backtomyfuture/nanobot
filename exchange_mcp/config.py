"""Configuration for Exchange MCP server — reads from ~/.nanobot/exchange.json."""

import json
from pathlib import Path

from pydantic import BaseModel, Field


class QdrantConfig(BaseModel):
    url: str = "http://localhost:6333"
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = ""
    collection_name: str = "emails"


class FeishuCardConfig(BaseModel):
    app_id: str = ""
    app_secret: str = ""
    chat_id: str = ""


class ExchangeConfig(BaseModel):
    enabled: bool = False
    api_url: str = ""
    api_key: str = ""
    account_id: int = 0
    account_email: str = ""
    ssl_verify: bool = False
    webhook_secret: str = ""
    folders_full: list[str] = Field(default_factory=lambda: ["Inbox"])
    folders_archive: list[str] = Field(default_factory=list)
    folder_sent_items: str = "Sent Items"
    folder_drafts: str = "Drafts"
    polling_interval: int = 300
    notify_channel: str = "feishu"
    notify_chat_id: str = ""
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    feishu: FeishuCardConfig = Field(default_factory=FeishuCardConfig)


_CONFIG_PATH = Path.home() / ".nanobot" / "exchange.json"
_cached: ExchangeConfig | None = None


def load_config(path: Path | None = None) -> ExchangeConfig:
    """Load exchange config from JSON file. Returns defaults if file missing."""
    global _cached
    if _cached is not None:
        return _cached
    p = path or _CONFIG_PATH
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        _cached = ExchangeConfig(**data)
    else:
        _cached = ExchangeConfig()
    return _cached


def get_config() -> ExchangeConfig:
    return load_config()
