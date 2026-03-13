"""Tests for providers module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from critiq.providers import (
    ClaudeProvider,
    OllamaProvider,
    OpenAIProvider,
    get_provider,
)


class TestClaudeProvider:
    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            ClaudeProvider()

    def test_uses_env_api_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        provider = ClaudeProvider()
        assert provider.api_key == "test-key"

    def test_explicit_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        provider = ClaudeProvider(api_key="explicit-key")
        assert provider.api_key == "explicit-key"

    def test_default_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        provider = ClaudeProvider()
        assert "claude" in provider.model.lower()

    def test_custom_model(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        provider = ClaudeProvider(model="claude-haiku-4-5-20251001")
        assert provider.model == "claude-haiku-4-5-20251001"

    def test_complete_calls_api(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        provider = ClaudeProvider()

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="Review result")]
        mock_client.messages.create.return_value = mock_message

        with patch("anthropic.Anthropic", return_value=mock_client):
            result = provider.complete("system prompt", "user prompt")

        assert result == "Review result"
        mock_client.messages.create.assert_called_once()


class TestOpenAIProvider:
    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            OpenAIProvider()

    def test_uses_env_api_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        provider = OpenAIProvider()
        assert provider.api_key == "test-key"

    def test_default_model(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        provider = OpenAIProvider()
        assert "gpt" in provider.model.lower()

    def test_complete_calls_api(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        provider = OpenAIProvider()

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Review result"))]
        mock_client.chat.completions.create.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            result = provider.complete("system prompt", "user prompt")

        assert result == "Review result"


class TestOllamaProvider:
    def test_default_model(self):
        provider = OllamaProvider()
        assert provider.model == "llama3.2"

    def test_custom_model(self):
        provider = OllamaProvider(model="codellama")
        assert provider.model == "codellama"

    def test_custom_base_url(self):
        provider = OllamaProvider(base_url="http://remote:11434")
        assert provider.base_url == "http://remote:11434"

    def test_complete_success(self):
        provider = OllamaProvider()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Review result"}
        }

        with patch("httpx.post", return_value=mock_response):
            result = provider.complete("system", "user")

        assert result == "Review result"

    def test_complete_connection_error(self):
        import httpx

        provider = OllamaProvider()

        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(RuntimeError, match="Cannot connect to Ollama"):
                provider.complete("system", "user")


class TestGetProvider:
    def test_returns_claude(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        provider = get_provider("claude")
        assert isinstance(provider, ClaudeProvider)

    def test_returns_openai(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "key")
        provider = get_provider("openai")
        assert isinstance(provider, OpenAIProvider)

    def test_returns_ollama(self):
        provider = get_provider("ollama")
        assert isinstance(provider, OllamaProvider)

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
        provider = get_provider("CLAUDE")
        assert isinstance(provider, ClaudeProvider)

    def test_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider("gemini")
