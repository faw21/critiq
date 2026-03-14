# critiq

**AI-powered local code reviewer — catch issues before you push.**

critiq reads your git diff and runs an AI review *before* you push. It flags security vulnerabilities, bugs, and performance issues with severity ratings so you can fix what matters most.

```
$ critiq
Reviewing staged changes · +28/-6 lines · src/auth.py, src/db.py

┌─────────────────── Summary ────────────────────────────────┐
│ 🚨 Needs work                                              │
│                                                            │
│ The change introduces direct SQL string interpolation,     │
│ a critical security vulnerability.                         │
└────────────────────────────────────────────────────────────┘

┌── 🚨 [CRITICAL] SQL Injection vulnerability ──────────────┐
│ src/auth.py  L42  security                                 │
│                                                            │
│ **Issue:** User input interpolated into SQL string         │
│ **Fix:** Use parameterized queries:                        │
│   db.execute("SELECT * FROM users WHERE name=?", (user,)) │
└───────────────────────────────────────────────────────────┘

┌── ⚠️ [WARNING] Missing input validation ──────────────────┐
│ src/db.py  L15  correctness                                │
│                                                            │
│ **Issue:** `user_id` can be None; no null check before use │
│ **Fix:** Add `if user_id is None: raise ValueError(...)` │
└───────────────────────────────────────────────────────────┘
```

## Install

```bash
pip install critiq
```

Set your API key (or use Ollama for zero-cost local review):

```bash
export ANTHROPIC_API_KEY=your-key   # Claude (default)
export OPENAI_API_KEY=your-key      # or OpenAI
# or use --provider ollama           # local, no API key needed
```

## Usage

```bash
# Review staged changes (most common — run before git push)
critiq

# Review all changes vs main branch
critiq --diff main

# Review a specific file
critiq --file src/auth.py

# Focus on a specific concern
critiq --focus security
critiq --focus performance
critiq --focus readability
critiq --focus correctness

# Only show critical issues
critiq --severity critical

# Compact output (good for scripts/CI)
critiq --compact

# Add context for the AI reviewer
critiq --context "This module handles payments — be strict about error handling"

# Use local Ollama (no API key)
critiq --provider ollama --model llama3.2

# Use OpenAI
critiq --provider openai --model gpt-4o
```

## Focus Areas

| Flag | Reviews |
|------|---------|
| `--focus all` | Everything (default) |
| `--focus security` | SQL injection, auth, XSS, SSRF, secrets exposure |
| `--focus performance` | N+1 queries, blocking I/O, inefficient algorithms |
| `--focus correctness` | Logic bugs, null handling, edge cases, race conditions |
| `--focus readability` | Naming, complexity, dead code, missing docs |
| `--focus style` | Formatting, conventions, unused imports |

## Severity Levels

| Level | Meaning |
|-------|---------|
| 🚨 **CRITICAL** | Must fix before merging (critiq exits with code 1) |
| ⚠️ **WARNING** | Should fix |
| ℹ️ **INFO** | Consider fixing |
| 💡 **SUGGESTION** | Nice to have |

`critiq` exits with code **1** if any CRITICAL issues are found, making it easy to use in pre-push hooks or CI.

## Pre-push Hook

Add to `.git/hooks/pre-push` to automatically review before every push:

```bash
#!/bin/sh
critiq --diff origin/main --severity critical --compact
```

```bash
chmod +x .git/hooks/pre-push
```

Now every `git push` automatically runs a security review. The push is blocked only if CRITICAL issues are found.

## Providers

| Provider | Command | Notes |
|----------|---------|-------|
| Claude (default) | `--provider claude` | Best results; requires `ANTHROPIC_API_KEY` |
| OpenAI | `--provider openai` | Requires `OPENAI_API_KEY` |
| Ollama | `--provider ollama` | Free, runs locally; no API key needed |

```bash
# Default model per provider
critiq --provider claude    # claude-opus-4-6
critiq --provider openai    # gpt-4o
critiq --provider ollama    # llama3.2

# Custom model
critiq --provider claude --model claude-haiku-4-5-20251001  # faster + cheaper
critiq --provider ollama --model codellama
```

## Developer Workflow Integration

critiq fits into the AI-powered git workflow:

```bash
# 1. Morning: generate standup from yesterday's commits
standup-ai ~/projects/myapp

# 2. Write code, then review before committing
critiq                          # AI review of staged changes
git add -p                      # stage what looks good

# 3. Generate conventional commit message
gpr --commit-run

# 4. Pack codebase context for LLM-assisted PR review
gitbrief . --budget 8000 --clipboard

# 5. Generate PR description
gpr

# 6. At release: generate CHANGELOG
changelog-ai --from v0.1.0 --prepend CHANGELOG.md
```

## Related Tools

- [gitbrief](https://github.com/faw21/gitbrief) — git-history-aware context packer for LLMs
- [gpr](https://github.com/faw21/gpr) — AI commit messages + PR descriptions
- [standup-ai](https://github.com/faw21/standup-ai) — daily standup from git commits
- [changelog-ai](https://github.com/faw21/changelog-ai) — AI-generated CHANGELOG
- [git-chronicle](https://github.com/faw21/chronicle) — AI git history narrator (understand WHY code changed)

## License

MIT
