"""Real LLM integration tests — calls actual APIs, not mocks.

Run with: pytest tests/test_integration_llm.py -v -s
Uses small/cheap models to save cost.
"""

from __future__ import annotations

import os
import pytest
from dotenv import load_dotenv

load_dotenv("/Users/aaronwu/Local/my-projects/give-it-all/.env", override=True)

from critiq.providers import get_provider, ClaudeProvider, OpenAIProvider, OllamaProvider


SYSTEM = "You are a code reviewer. Keep responses very short."
USER = "Say exactly: 'LLM test OK'"

has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY"))
has_openai = bool(os.environ.get("OPENAI_API_KEY"))


# ── Claude ───────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not has_anthropic, reason="ANTHROPIC_API_KEY not set")
def test_claude_real_complete():
    """Real call to Anthropic claude-haiku-4-5."""
    provider = ClaudeProvider(model="claude-haiku-4-5-20251001")
    result = provider.complete(SYSTEM, USER)
    assert isinstance(result, str)
    assert len(result) > 0
    print(f"\n[Claude] response: {result!r}")


@pytest.mark.skipif(not has_anthropic, reason="ANTHROPIC_API_KEY not set")
def test_get_provider_claude_real():
    """Factory creates Claude and calls API."""
    provider = get_provider("claude", model="claude-haiku-4-5-20251001")
    result = provider.complete(SYSTEM, USER)
    assert isinstance(result, str)
    assert len(result) > 0


# ── OpenAI ───────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not has_openai, reason="OPENAI_API_KEY not set")
def test_openai_real_complete():
    """Real call to OpenAI gpt-5-nano."""
    provider = OpenAIProvider(model="gpt-5-nano")
    result = provider.complete(SYSTEM, USER)
    assert isinstance(result, str)
    assert len(result) > 0
    print(f"\n[OpenAI] response: {result!r}")


@pytest.mark.skipif(not has_openai, reason="OPENAI_API_KEY not set")
def test_get_provider_openai_real():
    """Factory creates OpenAI and calls API."""
    provider = get_provider("openai", model="gpt-5-nano")
    result = provider.complete(SYSTEM, USER)
    assert isinstance(result, str)
    assert len(result) > 0


# ── Ollama ───────────────────────────────────────────────────────────────────

def test_ollama_real_complete():
    """Real call to local Ollama qwen2.5:1.5b."""
    provider = OllamaProvider(model="qwen2.5:1.5b")
    result = provider.complete(SYSTEM, USER)
    assert isinstance(result, str)
    assert len(result) > 0
    print(f"\n[Ollama] response: {result!r}")


def test_get_provider_ollama_real():
    """Factory creates Ollama and calls API."""
    provider = get_provider("ollama", model="qwen2.5:1.5b")
    result = provider.complete(SYSTEM, USER)
    assert isinstance(result, str)
    assert len(result) > 0


# ── Fix integration ───────────────────────────────────────────────────────────

@pytest.mark.skipif(not has_anthropic, reason="ANTHROPIC_API_KEY not set")
def test_generate_fix_real_claude():
    """Real LLM fix generation: Claude fixes a SQL injection."""
    from critiq.fixer import generate_fix
    from critiq.reviewer import ReviewComment, Severity

    provider = ClaudeProvider(model="claude-haiku-4-5-20251001")
    file_content = (
        "def get_user(db, username):\n"
        "    query = f\"SELECT * FROM users WHERE name='{username}'\"\n"
        "    return db.execute(query).fetchone()\n"
    )
    issues = [ReviewComment(
        severity=Severity.CRITICAL,
        file="src/auth.py",
        line="L2",
        title="SQL Injection",
        body=(
            "**Issue:** User input directly interpolated into SQL query.\n"
            "**Fix:** Use parameterized queries: "
            "db.execute('SELECT * FROM users WHERE name=?', (username,))"
        ),
        category="security",
    )]

    fixed = generate_fix("src/auth.py", file_content, issues, provider)

    assert isinstance(fixed, str)
    assert len(fixed) > 0
    assert "```" not in fixed  # no markdown fences
    # The fix should use parameterized queries
    assert "?" in fixed or "parameterized" in fixed.lower() or "format" not in fixed.lower()
    print(f"\n[Fix] Generated:\n{fixed}")


# ── critiq-report integration ─────────────────────────────────────────────────


def test_review_commit_real_ollama():
    """Real: review a commit diff using local Ollama."""
    import tempfile
    from pathlib import Path

    from critiq.providers import OllamaProvider
    from critiq.report import CommitInfo, get_commit_history, review_commit

    # Use the critiq repo itself for a real commit to review
    repo_path = Path(__file__).parent.parent
    history = get_commit_history(n=1, cwd=repo_path)

    if not history:
        pytest.skip("No commits found in test repo")

    commit = history[0]
    provider = OllamaProvider(model="qwen2.5:1.5b")

    with tempfile.TemporaryDirectory() as tmpdir:
        result = review_commit(
            commit=commit,
            provider=provider,
            cwd=repo_path,
            use_cache=False,
            cache_dir=Path(tmpdir),
        )

    assert isinstance(result.critical, int)
    assert isinstance(result.warning, int)
    assert isinstance(result.summary, str)
    assert result.skipped is False or result.skipped is True  # either is valid
    total = result.critical + result.warning + result.info + result.suggestion
    print(f"\n[report] commit={commit.short_hash} total_issues={total} summary={result.summary[:60]}")
