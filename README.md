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

# Review and interactively fix issues
critiq --fix

# Review and automatically apply all fixes (no prompts)
critiq --fix-all

# Watch mode: auto-review when staged files change
critiq --watch

# Review all changes vs main branch
critiq --diff main

# Review vs main, then fix what's found
critiq --diff main --fix

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

## Auto-Fix (v1.0)

`critiq --fix` closes the review loop: find issues **and** fix them in one command.

```
$ critiq --fix

🚨 [CRITICAL] SQL Injection in login()      src/auth.py  line 6
🚨 [CRITICAL] Plaintext Password Storage    src/auth.py  line 22
⚠️  [WARNING]  Weak Token Generation         src/auth.py  line 10

Fix 3 issue(s) in src/auth.py? (a=fix all / s=select / n=skip)  > a

Generating fix... ✓

╭─── Changes to src/auth.py ─────────────────────────────────────────╮
│ - query = f"SELECT * FROM users WHERE name='{username}'"           │
│ + query = "SELECT * FROM users WHERE name=? AND password=?"        │
│ + db.execute(query, (username, password))                           │
│                                                                     │
│ - return {"token": hashlib.md5(username.encode()).hexdigest()}      │
│ + return {"token": secrets.token_urlsafe(32)}                      │
╰─────────────────────────────────────────────────────────────────────╯

Apply this fix? [Y/n]  y
✅ Applied  (backup: src/auth.py.critiq.bak)
```

**How it works:**
1. critiq reviews your diff and finds issues
2. For each file with CRITICAL/WARNING issues, it asks: fix all / select / skip
3. The AI reads the full file + all issues and generates a fixed version
4. You see a colorized diff before applying
5. Original files are backed up as `.critiq.bak`
6. Run `git diff` to review all changes before committing

**Flags:**
- `--fix` — interactive mode (prompts for each file)
- `--fix-all` — auto-apply all fixes without prompting
- `--fix-severity warning` — also fix WARNING issues (default: CRITICAL + WARNING)

## Watch Mode (v1.1)

`critiq --watch` monitors your working directory and automatically re-runs a review every time your staged files change.

```bash
# Start watch mode: reviews run automatically when you git add
critiq --watch

# Watch with a specific focus
critiq --watch --focus security

# Adjust re-run delay (default: 2s after last change)
critiq --watch --debounce 5

# For faster file detection (optional):
pip install 'critiq[watch]'   # adds watchfiles for inotify/FSEvents support
```

This is useful when you're iterating on a feature: stage your changes and immediately get feedback, without leaving the terminal.

## Project Preferences (`critiq-learn`)

Teach critiq your project's conventions so it stops flagging things you don't care about — and always checks the things you do.

```bash
# Don't flag these (project uses JS, type hints not required)
critiq-learn ignore "Missing type annotations"
critiq-learn ignore "No docstrings on private methods"

# Always check these extra rules
critiq-learn rule "Never use raw SQL strings — always use parameterized queries"
critiq-learn rule "All API endpoints must have rate limiting"

# Set project defaults
critiq-learn set focus security         # always focus on security
critiq-learn set provider ollama        # use local LLM by default

# Show current config
critiq-learn show

# Remove an ignore rule
critiq-learn unignore "Missing type annotations"

# Reset everything
critiq-learn reset
```

Preferences are saved to `.critiq.yaml` in your project root. critiq automatically picks it up on every run:

```yaml
# .critiq.yaml (example)
ignore_patterns:
  - Missing type annotations
  - No docstrings on private methods
custom_rules:
  - Never use raw SQL strings — always use parameterized queries
default_focus: security
```

Add `.critiq.yaml` to git to share project preferences with your team.

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

## GitHub Actions (CI)

Add AI code review to every pull request with [critiq-action](https://github.com/faw21/critiq-action):

```yaml
# .github/workflows/critiq.yml
name: critiq Code Review
on:
  pull_request:
    branches: [main, master]
permissions:
  pull-requests: write
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: faw21/critiq-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
```

See [critiq-action](https://github.com/faw21/critiq-action) for full configuration options.

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

# 6. Review a teammate's PR
prcat 42                        # AI review of their changes

# 7. At release: generate CHANGELOG
changelog-ai --from v0.1.0 --prepend CHANGELOG.md
```

## Related Tools

- [critiq-action](https://github.com/faw21/critiq-action) — GitHub Action: run critiq in CI on every PR
- [gitbrief](https://github.com/faw21/gitbrief) — git-history-aware context packer for LLMs
- [gpr](https://github.com/faw21/gpr) — AI commit messages + PR descriptions
- [standup-ai](https://github.com/faw21/standup-ai) — daily standup from git commits
- [changelog-ai](https://github.com/faw21/changelog-ai) — AI-generated CHANGELOG
- [prcat](https://github.com/faw21/prcat) — AI reviewer for teammates' pull requests
- [git-chronicle](https://github.com/faw21/chronicle) — AI git history narrator (understand WHY code changed)

## License

MIT
