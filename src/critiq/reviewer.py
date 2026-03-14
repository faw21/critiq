"""Core AI review logic for critiq."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .config import CritiqConfig
from .git_utils import DiffResult
from .providers import LLMProvider


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
    SUGGESTION = "suggestion"


# Language-specific antipatterns injected into the review prompt
LANGUAGE_RULES: dict[str, list[str]] = {
    "python": [
        "Mutable default arguments (e.g. `def f(x=[])`) — default value is shared across calls",
        "Bare `except:` without exception type — catches SystemExit and KeyboardInterrupt",
        "`== None` or `!= None` instead of `is None` / `is not None`",
        "Missing type annotations on public function signatures",
        "String formatting with `%` or `.format()` when f-strings are available (Python 3.6+)",
        "`print()` debug statements left in production code",
        "Using `global` or `nonlocal` to mutate shared state",
        "Catching and re-raising exceptions without `raise ... from e` (loses traceback chain)",
        "`time.sleep()` in async code (blocks the event loop; use `asyncio.sleep()`)",
        "Shadowing built-ins: `list`, `dict`, `id`, `type`, `input`, etc.",
    ],
    "javascript": [
        "`var` instead of `let` or `const` — `var` has function scope and hoisting issues",
        "Loose equality `==` instead of strict `===` (coercion bugs)",
        "Async functions without try/catch — unhandled Promise rejections",
        "Mutating function arguments directly (side effects)",
        "`console.log()` / `console.debug()` debug statements left in code",
        "Callback hell (deeply nested callbacks) — prefer async/await",
        "Missing `await` on async calls inside async functions",
        "Prototype pollution risk when merging untrusted objects",
    ],
    "typescript": [
        "`any` type — defeats TypeScript's type safety; use `unknown` with type narrowing",
        "Non-null assertion `!` overuse — causes runtime errors if assumption is wrong",
        "`@ts-ignore` or `@ts-expect-error` without a clear justification comment",
        "Type assertions `as T` instead of proper type guards",
        "Missing `readonly` on properties that should be immutable",
        "Optional chaining `?.` used without considering the undefined case downstream",
        "`console.log()` debug statements left in code",
    ],
    "go": [
        "Ignored error return values (`err` assigned but never checked)",
        "`defer` inside a loop — only runs at function exit, not loop iteration exit",
        "`context.TODO()` or `context.Background()` passed deep into functions that should accept context",
        "Goroutine leak: goroutines started without a cancel/done channel or WaitGroup",
        "Naked return in functions longer than 5 lines — reduces readability",
        "`time.Sleep` in production code without justification",
        "Panic in library code (should return error instead)",
        "Unused `err` variable shadowed by `:=` in nested scope",
    ],
    "rust": [
        "`.unwrap()` or `.expect()` in non-test code without justification — use `?` or proper match",
        "`.clone()` on large data structures — check if a reference would work",
        "`panic!()` in library code — should return `Result` or `Option`",
        "`unsafe` block without a clear `// SAFETY:` comment explaining invariants",
        "`.to_string()` in hot paths — prefer `format!` sparingly or avoid allocation",
        "`unwrap_or_default()` masking unexpected None/Err — verify it's intentional",
    ],
}

# File extension → language key
EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".go": "go",
    ".rs": "rust",
}


def _detect_languages(files: list[str]) -> set[str]:
    """Return the set of languages detected from file extensions."""
    langs: set[str] = set()
    for f in files:
        ext = Path(f).suffix.lower()
        lang = EXT_TO_LANG.get(ext)
        if lang:
            langs.add(lang)
    return langs


def _build_language_hints(files: list[str]) -> str:
    """Build a language-specific antipattern section for the prompt."""
    langs = _detect_languages(files)
    if not langs:
        return ""

    parts = []
    for lang in sorted(langs):
        rules = LANGUAGE_RULES.get(lang, [])
        if rules:
            rule_list = "\n".join(f"  - {r}" for r in rules)
            parts.append(f"**{lang.capitalize()} — watch for these antipatterns:**\n{rule_list}")

    if not parts:
        return ""

    return "\n\n## Language-specific checks\n" + "\n\n".join(parts)


@dataclass
class ReviewComment:
    """A single review finding."""

    severity: Severity
    file: str
    line: str  # "L42" or "L42-50" or "" for file-level
    title: str
    body: str
    category: str  # e.g. "security", "performance", "readability"


@dataclass
class ReviewResult:
    """Result of a full code review."""

    comments: list[ReviewComment]
    summary: str
    overall_rating: str  # "✅ LGTM", "⚠️ Minor issues", "🚨 Needs work"
    provider_model: str


FOCUS_DESCRIPTIONS = {
    "all": "security vulnerabilities, performance issues, correctness bugs, code style, readability, and best practices",
    "security": "security vulnerabilities such as injection attacks, authentication issues, unsafe data handling, secret exposure, SSRF, XSS, CSRF, and authorization bypass",
    "performance": "performance bottlenecks, N+1 queries, unnecessary allocations, inefficient algorithms, missing caching opportunities, and blocking I/O",
    "readability": "code readability, naming conventions, complexity (too-long functions, deep nesting), missing documentation, and maintainability",
    "correctness": "logic bugs, edge cases, off-by-one errors, null/None handling, race conditions, and incorrect error handling",
    "style": "code style, formatting, naming conventions, dead code, unused imports, and consistency with the surrounding codebase",
}


def _build_system_prompt(
    focus: str,
    config: CritiqConfig | None = None,
    language_hints: str = "",
) -> str:
    focus_desc = FOCUS_DESCRIPTIONS.get(focus, FOCUS_DESCRIPTIONS["all"])

    # Build project-specific additions
    project_section = ""
    if config and not config.is_empty():
        parts = []
        if config.ignore_patterns:
            ignore_list = "\n".join(f"  - {p}" for p in config.ignore_patterns)
            parts.append(
                f"## Project preferences — DO NOT flag these:\n{ignore_list}"
            )
        if config.custom_rules:
            rules_list = "\n".join(f"  - {r}" for r in config.custom_rules)
            parts.append(
                f"## Project-specific rules — ALWAYS check these:\n{rules_list}"
            )
        if parts:
            project_section = "\n\n" + "\n\n".join(parts)

    return f"""You are an expert code reviewer with deep experience in software engineering, security, and performance optimization.

Your task: review a git diff and provide actionable, specific feedback.

Focus areas: {focus_desc}{project_section}{language_hints}

Output format — respond with EXACTLY this structure:

## Summary
<1-2 sentence overview of what the change does and your overall impression>

## Rating
<one of: "✅ LGTM", "⚠️ Minor issues", "🚨 Needs work">

## Findings
<For each issue, use this format:>

### [SEVERITY] Title
**File:** `filename` (line N or lines N-M, or "file-level")
**Category:** category-name
**Issue:** Concise description of the problem
**Fix:** Specific, actionable recommendation

SEVERITY must be one of: CRITICAL, WARNING, INFO, SUGGESTION

Rules:
- Only flag real issues, not personal preferences
- Be specific: include the actual code snippet causing the issue when helpful
- Prioritize: CRITICAL = must fix before merge, WARNING = should fix, INFO = consider fixing, SUGGESTION = nice to have
- If the diff is clean, say so under Findings: "No significant issues found."
- Keep each finding concise — 3-6 lines max
- Do NOT add any other sections or commentary outside this structure"""


def _build_user_prompt(diff: DiffResult, context: str | None = None) -> str:
    parts = []

    if diff.files_changed:
        parts.append(f"**Files changed:** {', '.join(diff.files_changed)}")
    parts.append(f"**Stats:** +{diff.insertions} insertions, -{diff.deletions} deletions")

    if context:
        parts.append(f"\n**Context:**\n{context}")

    parts.append(f"\n**Diff:**\n```diff\n{diff.diff}\n```")

    return "\n".join(parts)


def _parse_severity(text: str) -> Severity:
    t = text.upper().strip()
    for s in Severity:
        if s.value.upper() in t:
            return s
    return Severity.INFO


def _parse_review(raw: str, model: str) -> ReviewResult:
    """Parse the LLM response into structured ReviewResult."""
    lines = raw.strip().splitlines()

    summary = ""
    overall_rating = "⚠️ Minor issues"
    comments: list[ReviewComment] = []

    # Extract summary
    in_summary = False
    for i, line in enumerate(lines):
        if line.strip().startswith("## Summary"):
            in_summary = True
            continue
        if in_summary:
            if line.strip().startswith("##"):
                in_summary = False
            elif line.strip():
                summary += line.strip() + " "

    summary = summary.strip()

    # Extract rating
    for line in lines:
        if line.strip().startswith("## Rating"):
            continue
        if "✅" in line:
            overall_rating = "✅ LGTM"
            break
        if "🚨" in line:
            overall_rating = "🚨 Needs work"
            break
        if "⚠️" in line or "⚠" in line:
            overall_rating = "⚠️ Minor issues"
            break

    # Extract findings
    finding_sections = []
    current: list[str] = []
    in_findings = False

    for line in lines:
        if line.strip().startswith("## Findings"):
            in_findings = True
            continue
        if not in_findings:
            continue
        if line.strip().startswith("### "):
            if current:
                finding_sections.append(current)
            current = [line]
        elif current:
            current.append(line)

    if current:
        finding_sections.append(current)

    for section in finding_sections:
        header = section[0]  # "### [CRITICAL] Title" or "### CRITICAL: Title"
        # Parse header
        title = header.lstrip("#").strip()
        severity = Severity.INFO
        import re as _re
        for s in Severity:
            sv = s.value.upper()
            # Match both "[CRITICAL] Title" and "CRITICAL: Title" formats
            if f"[{sv}]" in title.upper():
                severity = s
                title = _re.sub(
                    rf"\[{sv}\]\s*", "", title, flags=_re.IGNORECASE
                ).strip()
                break
            elif _re.match(rf"^{sv}\s*[:\-]\s*", title, flags=_re.IGNORECASE):
                severity = s
                title = _re.sub(
                    rf"^{sv}\s*[:\-]\s*", "", title, flags=_re.IGNORECASE
                ).strip()
                break

        file_ref = ""
        line_ref = ""
        category = ""
        body_lines = []

        for content_line in section[1:]:
            stripped = content_line.strip()
            if stripped.startswith("**File:**"):
                file_ref = stripped.replace("**File:**", "").strip().strip("`")
            elif stripped.startswith("**Category:**"):
                category = stripped.replace("**Category:**", "").strip()
            elif stripped.startswith("**Issue:**") or stripped.startswith("**Fix:**"):
                body_lines.append(stripped)
            elif stripped:
                body_lines.append(stripped)

        # Parse file/line from file_ref like "`auth.py` (line 42)"
        if "(" in file_ref:
            parts = file_ref.split("(", 1)
            file_name = parts[0].strip().strip("`")
            line_ref = parts[1].rstrip(")").strip()
        else:
            file_name = file_ref.strip().strip("`")

        if title and title != "No significant issues found.":
            comments.append(
                ReviewComment(
                    severity=severity,
                    file=file_name,
                    line=line_ref,
                    title=title,
                    body="\n".join(body_lines),
                    category=category,
                )
            )

    return ReviewResult(
        comments=comments,
        summary=summary,
        overall_rating=overall_rating,
        provider_model=model,
    )


def review_result_to_dict(result: ReviewResult) -> dict:
    """Serialize a ReviewResult to a plain dict (for JSON output)."""
    return {
        "summary": result.summary,
        "overall_rating": result.overall_rating,
        "provider_model": result.provider_model,
        "comments": [
            {
                "severity": c.severity.value,
                "file": c.file,
                "line": c.line,
                "title": c.title,
                "body": c.body,
                "category": c.category,
            }
            for c in result.comments
        ],
    }


def review_diff(
    diff: DiffResult,
    provider: LLMProvider,
    focus: str = "all",
    context: str | None = None,
    model_label: str = "unknown",
    config: CritiqConfig | None = None,
) -> ReviewResult:
    """Run AI review on a diff and return structured results."""
    language_hints = _build_language_hints(diff.files_changed)
    system = _build_system_prompt(focus, config=config, language_hints=language_hints)
    user = _build_user_prompt(diff, context)

    raw = provider.complete(system, user)
    return _parse_review(raw, model_label)
