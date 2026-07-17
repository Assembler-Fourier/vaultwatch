"""Runtime configuration, read once from the environment.

MODE controls whether the LLM tiers make real Anthropic API calls or use
deterministic, zero-cost replay transcripts:

- "live":   always call Anthropic. Fails fast if ANTHROPIC_API_KEY is unset.
- "replay": always use canned transcripts, even if a key is present.
- "auto" (default): live if ANTHROPIC_API_KEY is set, replay otherwise.
  This is what lets the public showcase deployment run for free while a
  developer's local `docker compose up` with a key gets the real thing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mode: str
    anthropic_api_key: str | None
    engine_rust_url: str
    redis_url: str
    database_url: str | None
    port: int
    haiku_model: str
    sonnet_model: str

    @property
    def use_live_models(self) -> bool:
        if self.mode == "live":
            return True
        if self.mode == "replay":
            return False
        return bool(self.anthropic_api_key)


def load_settings() -> Settings:
    return Settings(
        mode=os.getenv("MODE", "auto"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        engine_rust_url=os.getenv("ENGINE_RUST_URL", "http://localhost:8081"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        database_url=os.getenv("DATABASE_URL") or None,
        port=int(os.getenv("PORT", "8000")),
        haiku_model=os.getenv("HAIKU_MODEL", "claude-haiku-4-5-20251001"),
        sonnet_model=os.getenv("SONNET_MODEL", "claude-sonnet-5"),
    )


settings = load_settings()
