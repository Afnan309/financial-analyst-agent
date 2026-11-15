"""Chat model clients. Each one turns (system, messages) into reply text.
SDKs are imported lazily, so offline mode needs none of them."""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Any

PROVIDERS = ("offline", "claude", "openai", "ollama")


class LLMClient:
    name = "base"
    model = ""

    def complete(self, system: str, messages: list[dict[str, str]]) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class ClaudeClient(LLMClient):
    name = "claude"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("pip install anthropic  (or use --provider offline)") from e
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))

    def complete(self, system, messages):
        msg = self.client.messages.create(model=self.model, max_tokens=1500, temperature=0, system=system,
                                          messages=messages)
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


class OpenAIClient(LLMClient):
    name = "openai"

    def __init__(self, model: str | None = None, api_key: str | None = None, base_url: str | None = None):
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("pip install openai  (or use --provider offline)") from e
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"), base_url=base_url or os.getenv("OPENAI_BASE_URL"))

    def complete(self, system, messages):
        resp = self.client.chat.completions.create(
            model=self.model, temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, *messages])
        return resp.choices[0].message.content or ""


class OllamaClient(LLMClient):
    """Local open-weight models: filings never leave the machine."""

    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None):
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
        self.host = (host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")

    def complete(self, system, messages):
        body = json.dumps({"model": self.model, "stream": False, "format": "json", "options": {"temperature": 0},
                           "messages": [{"role": "system", "content": system}, *messages]}).encode()
        req = urllib.request.Request(f"{self.host}/api/chat", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())["message"]["content"]


def get_client(name: str, model: str | None = None) -> LLMClient:
    name = name.lower()
    if name in ("claude", "anthropic"):
        return ClaudeClient(model)
    if name == "openai":
        return OpenAIClient(model)
    if name == "ollama":
        return OllamaClient(model)
    raise ValueError(f"Unknown provider '{name}'. Choose from {PROVIDERS}")


def extract_json(raw: str) -> dict[str, Any]:
    """Parse one JSON object from a reply, tolerating code fences and surrounding text."""
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(raw[start:end + 1])
