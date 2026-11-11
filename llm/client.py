"""Minimal OpenAI-compatible chat client with a model fallback chain.

Gemini (generativelanguage.googleapis.com/v1beta/openai) and Ollama (/v1)
both speak the OpenAI chat-completions format with tool calling, so one
client serves both. Assistant messages are kept exactly as returned: Gemini
attaches a `thought_signature` to tool calls that must be sent back unchanged.

Free-tier quotas are per model per day, so the client takes a list of models:
when one model's daily quota is used up it is skipped (no retries; waiting
won't help) and the next model is tried. Short rate limits (per minute) and
transient upstream errors are retried with a capped back-off.
"""
from __future__ import annotations

import re
import time

import httpx


class LLMError(RuntimeError):
    pass


class ChatClient:
    def __init__(self, base_url: str, models: str | list[str], api_key: str | None, timeout: float = 90.0):
        self.base_url = base_url.rstrip("/")
        self.models = [models] if isinstance(models, str) else list(models)
        self.exhausted: set[str] = set()
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        self.timeout = timeout
        self.last_model: str | None = None

    @property
    def model(self) -> str:
        return next((m for m in self.models if m not in self.exhausted), self.models[0])

    def chat(self, messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.1) -> dict:
        errors = []
        for model in [m for m in self.models if m not in self.exhausted]:
            try:
                msg = self._chat_one(model, messages, tools, temperature)
                self.last_model = model
                return msg
            except _DailyQuota as e:
                self.exhausted.add(model)
                errors.append(f"{model}: daily quota used up")
            except LLMError as e:
                errors.append(f"{model}: {e}")
                break  # a real error (bad request, auth): another model won't fix it
        raise LLMError("; ".join(errors) or "all models exhausted")

    def _chat_one(self, model, messages, tools, temperature, retries: int = 3) -> dict:
        body = {"model": model, "messages": messages, "temperature": temperature}
        if tools:
            body["tools"] = tools
        delay, last = 3.0, None
        for attempt in range(retries + 1):
            try:
                r = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=self.headers, timeout=self.timeout)
            except httpx.HTTPError as e:
                last = f"network error: {e}"
            else:
                if r.status_code == 200:
                    data = r.json()
                    data = data[0] if isinstance(data, list) else data
                    try:
                        return data["choices"][0]["message"]
                    except (KeyError, IndexError):
                        raise LLMError(f"unexpected response: {str(data)[:200]}") from None
                text = r.text
                last = f"HTTP {r.status_code}: {text[:200]}"
                if r.status_code == 429 and ("PerDay" in text or "per day" in text.lower()):
                    raise _DailyQuota(model)
                if r.status_code == 404:
                    raise _DailyQuota(model)  # model retired or unavailable to this key: skip it
                if r.status_code not in (429, 500, 502, 503, 504):
                    raise LLMError(last)
                m = re.search(r'"retryDelay":\s*"(\d+)s"', text)
                if m:
                    delay = min(float(m.group(1)) + 1, 30.0)
            if attempt < retries:
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
        raise LLMError(last or "request failed")


class _DailyQuota(LLMError):
    pass
