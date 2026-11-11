"""LLM settings, from environment variables or a .env file at the repo root."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    provider: str          # gemini | ollama | offline
    model: str | None      # first model of the chain
    models: tuple          # fallback chain (free-tier quotas are per model per day)
    base_url: str | None
    api_key: str | None

    @property
    def ready(self) -> bool:
        return self.provider == "ollama" or (self.provider == "gemini" and bool(self.api_key))


def settings() -> Settings:
    _load_dotenv()
    provider = os.environ.get("LLM_PROVIDER", "offline").strip().lower()
    if provider == "gemini":
        chain = [m.strip() for m in os.environ.get(
            "GEMINI_MODELS", "gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite").split(",") if m.strip()]
        if os.environ.get("GEMINI_MODEL"):
            chain = [os.environ["GEMINI_MODEL"]] + [m for m in chain if m != os.environ["GEMINI_MODEL"]]
        return Settings("gemini", chain[0], tuple(chain), "https://generativelanguage.googleapis.com/v1beta/openai",
                        os.environ.get("GEMINI_API_KEY") or None)
    if provider == "ollama":
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
        return Settings("ollama", model, (model,), f"{host}/v1", "ollama")
    return Settings("offline", None, (), None, None)
