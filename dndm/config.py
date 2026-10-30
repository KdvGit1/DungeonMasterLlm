"""Persistent app configuration (userdata/config.json)."""

from __future__ import annotations

import json

from pydantic import BaseModel

from dndm.paths import user_dir

DEFAULT_MODEL = "huihui_ai/gemma-4-abliterated:12b"


class AppConfig(BaseModel):
    model: str = DEFAULT_MODEL
    ollama_url: str = "http://127.0.0.1:11434"
    num_ctx: int = 8192
    port: int = 8765
    host: str = "0.0.0.0"


def load_config() -> AppConfig:
    p = user_dir() / "config.json"
    if p.exists():
        try:
            return AppConfig.model_validate(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return AppConfig()


def save_config(cfg: AppConfig) -> None:
    p = user_dir() / "config.json"
    p.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
