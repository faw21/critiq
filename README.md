# critiq

[![PyPI version](https://img.shields.io/pypi/v/critiq.svg)](https://pypi.org/project/critiq/)
[![Python](https://img.shields.io/pypi/pyversions/critiq.svg)](https://pypi.org/project/critiq/)
[![License: BSL-1.0](https://img.shields.io/badge/License-BSL--1.0-blue.svg)](https://github.com/faw21/critiq/blob/main/LICENSE)
[![VS Code Extension](https://img.shields.io/badge/VS%20Code-Extension-blue?logo=visual-studio-code)](https://github.com/faw21/critiq-vscode)

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

**VS Code extension:** install [critiq for VS Code](https://github.com/faw21/critiq-vscode) — inline ghost-text hints, gutter icons, tree view, and `Cmd+Shift+R` shortcut.

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

## Language-Aware Reviews (v1.3)

critiq automatically detects the language of your changed files and injects **language-specific antipattern checks** into every review — no flags needed.

| Language | Examples of what critiq checks |
|---|---|
| **Python** | Mutable default args, bare `except:`, `== None` vs `is None`, shadowed builtins, `print()` debug statements |
| **JavaScript** | `var` vs `let/const`, loose `==`, unhandled Promise rejections, missing `await`, callback hell |
| **TypeScript** | `any` type, non-null assertion `!` overuse, `@ts-ignore` without justification, type assertions |
| **Go** | Ignored error returns, `defer` in loops, goroutine leaks, `panic()` in library code |
| **Rust** | `.unwrap()` without justification, `panic!()` in library code, `unsafe` without `// SAFETY:` comment |

This is on top of the general review — critiq catches both universal issues and language-specific footguns.

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

## Trend Report (`critiq-report`)

`critiq-report` analyzes your commit history and shows how code quality has changed over time.

```
$ critiq-report --commits 10

╭─────────────────────────────── 🔍 critiq report ───────────────────────────────╮
│ Analyzed 10 commits  Total issues: 87  Trend: 📈 Improving                     │
╰─────────────────────────────────────────────────────────────────────────────────╯

                              Issues per Commit
 Commit   Message                                    Author    🔴C  🟡W  🔵I  💡S
 a1b2c3…  fix: resolve race condition in worker      Alice Dev   ·    1    2    ·
 d4e5f6…  feat: add payment processing module        Bob Dev     2    3    5    1
 ...

  Issue trend (oldest → newest): █▇▆▅▃▂▂▁▁▁

 🔥 Hotspot Files (repeatedly flagged)
 File                    Times flagged
 src/payments/handler.py   4  ████████
 src/auth/session.py        3  ██████
```

```bash
# Analyze last 10 commits (default, uses free local Ollama)
critiq-report

# Analyze more commits
critiq-report --commits 30

# Since a release tag
critiq-report --since v1.0.0

# Higher-quality reviews with Claude
critiq-report --provider claude

# Force re-review (skip cache)
critiq-report --no-cache

# Save as Markdown
critiq-report --output quality-report.md
```

Results are cached in `.critiq-report/` (add to `.gitignore`). Re-runs are instant.

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

## Git Hook Integration (v1.5)

Install critiq as a git hook with one command:

```bash
# Block commits with CRITICAL issues
critiq-install

# Or block pushes instead (less disruptive)
critiq-install --pre-push
```

That's it. Every `git commit` (or `git push`) will now run an AI review. CRITICAL issues block the operation; everything else is just a warning.

```
$ git commit -m "add payment handler"
critiq: Reviewing staged changes...

🚨 [CRITICAL] SQL Injection in process_payment()  src/payments.py  L47
  User input is directly interpolated into SQL query string.

critiq: ⛔ Commit blocked — CRITICAL issues found above.
  Fix the issues or bypass with: git commit --no-verify
```

**Remove the hook anytime:**

```bash
critiq-uninstall           # remove pre-commit hook
critiq-uninstall --pre-push  # remove pre-push hook
```

**Works alongside existing hooks** — if you already have a pre-commit hook, critiq appends to it rather than overwriting.

**Manual hook setup (alternative):**

```bash
# .git/hooks/pre-commit
#!/bin/sh
critiq --staged --severity critical --compact
```

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
testfix pytest                  # 3. Auto-fix failing tests

# 4. Generate conventional commit message
gpr --commit-run

# 5. Pack codebase context for LLM-assisted PR review
gitbrief . --budget 8000 --clipboard

# 6. Generate PR description
gpr

# 7. Review a teammate's PR
prcat 42                        # AI review of their changes

# 8. At release: generate CHANGELOG
changelog-ai --from v0.1.0 --prepend CHANGELOG.md

# 9. Periodically: check code quality trend over time
critiq-report --commits 20
```

## Full-File Scanning (`critiq-scan`) (v2.0)

While `critiq` reviews *git diffs*, `critiq-scan` audits **complete files and directories** — perfect for security audits, onboarding new codebases, or reviewing legacy code.

```bash
# Scan current directory (auto-discovers source files)
critiq-scan

# Security audit of a specific directory
critiq-scan src/ --focus security

# Scan specific files
critiq-scan auth.py utils.py

# Only show critical issues
critiq-scan . --include "*.py" --severity critical

# Summary table (no detailed findings)
critiq-scan . --summary

# Machine-readable JSON (for CI/scripts)
critiq-scan . --json

# Limit scope
critiq-scan . --max-files 10 --exclude "tests/*"
```

**How it differs from `critiq`:**

| | `critiq` | `critiq-scan` |
|---|---|---|
| Input | Git diff / staged changes | Full file contents |
| Use case | Pre-commit review | Security audits, new codebases |
| Output | Per-diff findings | Per-file findings |
| File discovery | git-tracked files | Recursive directory walk |

**Supported file types:** `.py`, `.js`, `.ts`, `.tsx`, `.go`, `.rs`, `.rb`, `.java`, `.kt`, `.c`, `.cpp`, `.cs`, `.php`, `.swift`, `.sh`, `.yaml`, `.toml`, `.tf`, and more.

**Exit code:** 0 if no critical issues, 1 if any critical issues found (CI-friendly).

## VS Code Extension

[critiq-vscode](https://github.com/faw21/critiq-vscode) brings critiq directly into your editor:

```
src/auth.py
  cursor.execute(query % params)   ⚡ SQL Injection vulnerability    ← ghost text inline
  ↑                                                                   ← red gutter circle
```

**Features (v1.3.0):**
- 🔴 **Gutter icons** — colored circles on flagged lines (red/yellow/blue by severity)
- 📝 **Inline ghost text** — issue title shown at end of each flagged line (like GitHub Copilot hints)
- 🌡️ **Overview ruler** — colored marks in the scrollbar for bird's-eye view of all issues
- 🌳 **Findings tree** — sidebar panel grouping all issues by file with click-to-navigate
- 🔧 **Code actions** — lightbulb on flagged lines → "Fix with critiq" (runs `--fix-all` instantly)
- 📊 **Status bar** — shows live issue count; click to re-run review
- ⌨️ **Keyboard shortcut** — `Cmd+Shift+R` (Mac) / `Ctrl+Shift+R` (Windows/Linux)
- 🔄 **Auto-review** — optional trigger on file save

**Install:**
```bash
# Option 1: Download the .vsix from the latest release
curl -L https://github.com/faw21/critiq-vscode/releases/latest/download/critiq-1.3.0.vsix -o critiq.vsix
code --install-extension critiq.vsix

# Option 2: Marketplace (coming soon)
```

## Related Tools

- [critiq-vscode](https://github.com/faw21/critiq-vscode) — VS Code extension: gutter icons + inline hints + tree view + auto-fix
- [critiq-action](https://github.com/faw21/critiq-action) — GitHub Action: run critiq in CI on every PR
- [mergefix](https://github.com/faw21/mergefix) — AI-powered merge conflict resolver (runs after `git merge`)
- [gitbrief](https://github.com/faw21/gitbrief) — git-history-aware context packer for LLMs
- [gpr](https://github.com/faw21/gpr) — AI commit messages + PR descriptions
- [standup-ai](https://github.com/faw21/standup-ai) — daily standup from git commits
- [changelog-ai](https://github.com/faw21/changelog-ai) — AI-generated CHANGELOG
- [prcat](https://github.com/faw21/prcat) — AI reviewer for teammates' pull requests
- [git-chronicle](https://github.com/faw21/chronicle) — AI git history narrator (understand WHY code changed)
- [testfix](https://github.com/faw21/testfix) — AI failing test auto-fixer

## License

MIT
