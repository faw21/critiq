"""LLM provider implementations for critiq."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Send a prompt and return the response text."""
        ...


class ClaudeProvider(LLMProvider):
    """Anthropic Claude provider."""

    DEFAULT_MODEL = "claude-opus-4-6"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or self.DEFAULT_MODEL
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not set. "
                "Run: export ANTHROPIC_API_KEY=your-key\n"
                "Or use --provider openai / --provider ollama"
            )

    def complete(self, system: str, user: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        message = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return message.content[0].text


class OpenAIProvider(LLMProvider):
    """OpenAI provider."""

    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or self.DEFAULT_MODEL
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "OPENAI_API_KEY not set. "
                "Run: export OPENAI_API_KEY=your-key"
            )

    def complete(self, system: str, user: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_completion_tokens=4096,
        )
        return response.choices[0].message.content or ""


class OllamaProvider(LLMProvider):
    """Local Ollama provider (no API key required)."""

    DEFAULT_MODEL = "llama3.2"
    DEFAULT_URL = "http://localhost:11434"

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = model or self.DEFAULT_MODEL
        self.base_url = base_url or os.environ.get("OLLAMA_HOST", self.DEFAULT_URL)

    def complete(self, system: str, user: str) -> str:
        import httpx

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"]
        except httpx.ConnectError:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self.base_url}. "
                "Is Ollama running? Try: ollama serve"
            )


def get_provider(
    provider: str,
    model: str | None = None,
    api_key: str | None = None,
) -> LLMProvider:
    """Factory: return the appropriate LLM provider."""
    p = provider.lower()
    if p == "claude":
        return ClaudeProvider(model=model, api_key=api_key)
    elif p == "openai":
        return OpenAIProvider(model=model, api_key=api_key)
    elif p == "ollama":
        return OllamaProvider(model=model)
    else:
        raise ValueError(
            f"Unknown provider '{provider}'. Choose: claude, openai, ollama"
        )
