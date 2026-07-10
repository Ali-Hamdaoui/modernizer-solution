"""Shared redaction and forbidden-path baseline for V1.

This module defines the canonical redaction primitives used across
all V1 layers (API responses, audit records, model invocation summaries,
context packs, and evidence retrieval). It also establishes the baseline
for forbidden path patterns that must never be exposed.

Design:
- All redaction functions are pure (no I/O, no DB access).
- Forbidden path patterns are compile-time constants.
- Secrets/prompts/deployment IDs are always redacted from public DTOs.
- Raw absolute paths are redacted to path-kind placeholders.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PureWindowsPath
from typing import Any

DEFAULT_PUBLIC_TEXT_LIMIT = 4_000
DEFAULT_PUBLIC_DIFF_TEXT_LIMIT = 20_000


# ── Forbidden path patterns ──────────────────────────────────────────

# Pattern matches Windows absolute paths like C:\Users\... or D:/data/...
# Does NOT match URLs (http://, https://, etc.)
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z]:)(?<![A-Za-z])[A-Za-z]:[\\/](?:[^\\/\s:]*[\\/])*[^\\/\s:]*"
)

_UNC_ABSOLUTE_PATH_RE = re.compile(r"\\\\[^\\/\s]+[\\/][^\\/\s]+(?:[\\/][^\\/\s]+)*")

# Pattern matches POSIX absolute paths like /home/user/.ssh/id_rsa
# Does NOT match URLs (http://, https://) or single / between words
_POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_:/<])(?<!/)/(?:[^/\s]+/)*[^/\s]+"
)

# Pattern matches environment variable assignments like SECRET=value
_ENV_ASSIGNMENT_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}=[^\s]+")

# Pattern matches common secret-related key names as whole words
_SECRET_KEY_RE = re.compile(
    r"\b(secret|token|password|passwd|passphrase|credential|api[_-]?key|private[_-]?key|access[_-]?key|authorization)\b",
    re.IGNORECASE,
)

_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(-D)?("
    r"[A-Za-z0-9_.-]*(?:password|passwd|passphrase|secret|token|api[_-]?key|private[_-]?key|"
    r"access[_-]?key|client[_-]?secret|credential)[A-Za-z0-9_.-]*"
    r")\s*([=:])\s*(\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;&]+)"
)

_AUTHORIZATION_HEADER_RE = re.compile(
    r"(?im)\b(authorization\s*:\s*)(?:bearer|basic|token|apikey|api-key)\s+[^\s,;]+"
)

_CONNECTION_CREDENTIALS_RE = re.compile(
    r"(?i)\b((?:jdbc:)?[a-z][a-z0-9+.-]*://)([^/@\s:]+):([^/@\s]+)@"
)

_PROMPT_ASSIGNMENT_RE = re.compile(
    r"(?im)\b((?:raw_|system_|developer_|hidden_)?prompt|system_message|developer_message|hidden_instructions)\s*([=:])\s*.*$"
)

_PUBLIC_PROMPT_KEY_RE = re.compile(
    r"(?:^|_)(?:raw_)?prompt(?:_|$)|system_message|developer_message|hidden_instructions|system_prompt|developer_prompt",
    re.IGNORECASE,
)

_PUBLIC_INTERNAL_DETAIL_KEY_RE = re.compile(
    r"traceback|stack[_-]?trace|raw[_-]?(?:exception|error)|internal[_-]?(?:exception|error)|"
    r"provider[_-]?(?:response|error)|sql[_-]?error|error[_-]?body",
    re.IGNORECASE,
)

_PUBLIC_PROCESS_KEY_RE = re.compile(r"\bpid\b|\bprocess[_-]?id\b|\bhandle\b", re.IGNORECASE)

_STACK_TRACE_RE = re.compile(r"traceback\s+\(most recent call last\)|\bFile \"[^\"]+\", line \d+", re.IGNORECASE)

_INTERNAL_EXCEPTION_RE = re.compile(
    r"\b(?:sqlite3|sqlalchemy|psycopg2|asyncpg|openai|azure|httpx|requests)\.[A-Za-z0-9_.]*"
    r"|(?:OperationalError|ProgrammingError|IntegrityError):"
    r"|\b(?:provider|sql|python)\s+(?:exception|error)\b",
    re.IGNORECASE,
)

# Pattern matches deployment/model resource identifiers
_DEPLOYMENT_ID_RE = re.compile(
    r"(deployment[_-]?id|model[_-]?id|endpoint[_-]?id|resource[_-]?id)"
    r"\s*[:=]\s*\S+",
    re.IGNORECASE,
)

# Pattern matches raw prompt content (heuristic: quoted blocks with >50 chars)
_RAW_PROMPT_RE = re.compile(
    r"""[("'"`]{3,}[\s\S]{50,}?[)""'"`]{3,}"""
)

# Pattern matches common home directory references (applied before POSIX path re)
_HOME_DIR_RE = re.compile(
    r"(?:^|(?<=\s))(?:/home/[^/\s]+)(?:/|\s|$)"
)

# Forbidden path prefixes that must never appear in public output
FORBIDDEN_PATH_PREFIXES: tuple[str, ...] = (
    "/etc/",
    "/var/",
    "/proc/",
    "/sys/",
    "/dev/",
    "/boot/",
    "/root/",
    "/private/",
    "c:/windows/",
    "c:/program files/",
    "c:/users/",
)

# Forbidden file extensions that should trigger redaction
FORBIDDEN_FILE_EXTENSIONS: tuple[str, ...] = (
    ".pem",
    ".key",
    ".pkcs8",
    ".pfx",
    ".p12",
    ".keystore",
    ".env",
    ".env.local",
    ".env.production",
)

# Backend-owned sandbox path keys that must survive redaction
# so _resolve_stage_sandbox_root can reconstruct the stage
# sandbox from event payloads.
_BACKEND_SANDBOX_PATH_KEYS: frozenset[str] = frozenset({
    "sandbox_path",
})

# Environment variable names that should always be redacted
SENSITIVE_ENV_VARS: tuple[str, ...] = (
    "AZURE_OPENAI_KEY",
    "AZURE_OPENAI_API_KEY",
    "OPENAI_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ACCESS_KEY_ID",
    "GITHUB_TOKEN",
    "GITLAB_TOKEN",
    "DOCKER_TOKEN",
    "SSH_PRIVATE_KEY",
    "DEPLOYMENT_ID",
    "MODEL_DEPLOYMENT_ID",
)

# Pattern matches sensitive env var assignments
_SENSITIVE_ENV_VAR_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(v) for v in SENSITIVE_ENV_VARS) + r")\s*=\s*\S+"
)

# Pattern matches bearer/API token values commonly surfaced in smoke errors
_TOKEN_VALUE_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{6,}|gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]+|Bearer\s+[A-Za-z0-9._-]{8,})\b",
    re.IGNORECASE,
)

# ── Redaction functions ──────────────────────────────────────────────


def redact_absolute_paths(text: str) -> str:
    """Replace absolute paths with a path-kind placeholder.

    Preserves URLs (http/https) from path redaction.
    """
    text = _UNC_ABSOLUTE_PATH_RE.sub("[redacted-path]", text)
    text = _WINDOWS_ABSOLUTE_PATH_RE.sub("[redacted-windows-path]", text)
    text = _POSIX_ABSOLUTE_PATH_RE.sub("[redacted-path]", text)
    text = _HOME_DIR_RE.sub("[redacted-home-path]", text)
    return text


def redact_env_assignments(text: str) -> str:
    """Replace environment variable assignments with placeholder."""
    return _ENV_ASSIGNMENT_RE.sub("[redacted-env]", text)


def redact_sensitive_env_vars(text: str) -> str:
    """Replace sensitive environment variable assignments."""
    return _SENSITIVE_ENV_VAR_RE.sub("[redacted-sensitive-env]", text)


def redact_sensitive_assignments(text: str) -> str:
    """Replace password/token/API-key assignment values case-insensitively."""
    return _SENSITIVE_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1) or ''}{match.group(2)}{match.group(3)}[redacted]",
        text,
    )


def redact_authorization_values(text: str) -> str:
    """Replace Authorization header values."""
    return _AUTHORIZATION_HEADER_RE.sub(lambda match: f"{match.group(1)}[redacted]", text)


def redact_connection_credentials(text: str) -> str:
    """Replace credentials embedded in connection URLs."""
    return _CONNECTION_CREDENTIALS_RE.sub(lambda match: f"{match.group(1)}[redacted]@", text)


def redact_secret_keys(text: str) -> str:
    """Replace secret-related key names with 'redacted'."""
    return _SECRET_KEY_RE.sub("redacted", text)


def redact_deployment_identifiers(text: str) -> str:
    """Replace deployment/model identifiers with placeholder."""
    return _DEPLOYMENT_ID_RE.sub("[redacted-deployment-id]", text)


def redact_raw_prompts(text: str) -> str:
    """Replace raw prompt blocks with placeholder."""
    text = _PROMPT_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted-prompt]", text)
    return _RAW_PROMPT_RE.sub("[redacted-prompt]", text)


def redact_model_summary(summary: str) -> str:
    """Redact a model invocation summary for public DTOs.

    Applies all redaction primitives: paths, env vars, secret keys,
    deployment IDs, and raw prompts.
    """
    result = summary
    result = redact_connection_credentials(result)
    result = redact_authorization_values(result)
    result = redact_sensitive_assignments(result)
    result = redact_absolute_paths(result)
    result = redact_sensitive_env_vars(result)
    result = redact_env_assignments(result)
    result = redact_secret_keys(result)
    result = redact_deployment_identifiers(result)
    result = _TOKEN_VALUE_RE.sub("[redacted-token]", result)
    result = redact_raw_prompts(result)
    return result


def redact_public_message(message: str, *, max_chars: int | None = DEFAULT_PUBLIC_TEXT_LIMIT) -> str:
    """Redact and bound a string for public API/display output."""
    text = str(message)
    if _STACK_TRACE_RE.search(text) or _INTERNAL_EXCEPTION_RE.search(text):
        return _bound_public_text("Internal details redacted.", max_chars=max_chars)
    return _bound_public_text(redact_model_summary(text), max_chars=max_chars)


def redact_public_value(
    value: Any,
    *,
    preserve_backend_sandbox_paths: bool = True,
    max_string_chars: int | None = DEFAULT_PUBLIC_TEXT_LIMIT,
) -> Any:
    """Recursively redact a value for public API output.

    Strings are redacted through all primitives.
    Dict keys with secret-related names have their values replaced.
    """
    if isinstance(value, dict):
        return {
            k: _redact_dict_value(
                k,
                v,
                preserve_backend_sandbox_paths=preserve_backend_sandbox_paths,
                max_string_chars=max_string_chars,
            )
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            redact_public_value(
                item,
                preserve_backend_sandbox_paths=preserve_backend_sandbox_paths,
                max_string_chars=max_string_chars,
            )
            for item in value
        ]
    if isinstance(value, str):
        return redact_public_message(value, max_chars=max_string_chars)
    return value


def redact_public_api_value(value: Any) -> Any:
    """Strict public-response redaction that never preserves backend paths."""
    return redact_public_value(value, preserve_backend_sandbox_paths=False)


def project_public_diff(exact_diff: str, *, max_chars: int = DEFAULT_PUBLIC_DIFF_TEXT_LIMIT) -> dict[str, Any]:
    """Return display-safe diff fields while preserving exact bytes elsewhere."""
    exact = str(exact_diff or "")
    redacted_unbounded = redact_public_message(exact, max_chars=None)
    display = _bound_public_text(redacted_unbounded, max_chars=max_chars)
    redacted = redacted_unbounded != exact
    truncated = len(redacted_unbounded) > max_chars
    if redacted and truncated:
        status = "redacted_and_truncated"
    elif redacted:
        status = "redacted"
    elif truncated:
        status = "truncated"
    else:
        status = "clean"
    return {
        "display_proposed_diff": display,
        "display_diff_redacted": redacted,
        "display_diff_status": status,
    }


def redact_audit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact an audit record payload for public exposure.

    Preserves structural fields (ids, types, timestamps) while
    redacting paths, env refs, and secret-like values.
    """
    return redact_public_value(payload)


def contains_forbidden_path(path: str | Path) -> bool:
    """Check if a path or path string contains forbidden patterns.

    Returns True if the path starts with any forbidden prefix or
    has a forbidden file extension.
    """
    path_str = str(path)

    # Normalize separators and lowercase for comparison
    normalized = path_str.replace("\\", "/").lower()

    for ext in FORBIDDEN_FILE_EXTENSIONS:
        if normalized.endswith(ext.lower()):
            return True

    for prefix in FORBIDDEN_PATH_PREFIXES:
        if normalized.startswith(prefix):
            return True

        # Also check for substring match (handles mixed separators)
        if prefix in normalized:
            return True

    return False


def validate_not_forbidden(path: str | Path) -> None:
    """Raise ValueError if the given path contains forbidden patterns."""
    if contains_forbidden_path(path):
        raise ValueError(
            f"Path contains forbidden pattern: {path!r}"
        )


def is_sensitive_env_var(name: str) -> bool:
    """Check if an environment variable name is classified as sensitive."""
    return name.upper() in SENSITIVE_ENV_VARS


def is_forbidden_file(path: str | Path) -> bool:
    """Check if a file path has a forbidden extension or location."""
    return contains_forbidden_path(path)


# ── V2 display helpers for local operator mode ───────────────────────


def redact_local_mode_path(path: str) -> str:
    """Redact a local absolute path for safe public display.

    In local operator mode, the frontend may display absolute paths
    using a placeholder for the user-specific prefix while preserving
    the rest of the path for orientation (e.g., "[user-home]/apps/my-app").
    Forbidden paths (secrets, env, etc.) are fully redacted.
    """
    if contains_forbidden_path(path):
        return "[redacted-path]"
    return redact_absolute_paths(path)


def redact_allowed_roots_for_display(roots: tuple[str, ...]) -> tuple[str, ...]:
    """Redact a tuple of allowed roots for safe public display."""
    return tuple(redact_local_mode_path(r) if r else r for r in roots)


def env_ref_or_none(env_var_name: str | None) -> str:
    """Return the env ref name for display, or empty string if None."""
    if not env_var_name:
        return ""
    return env_var_name


# ── Internal helpers ─────────────────────────────────────────────────


def _looks_like_url(text: str) -> bool:
    """Check if text looks like a URL (http/https)."""
    return bool(text.startswith(("http://", "https://")))


def _redact_dict_value(
    key: str,
    value: Any,
    *,
    preserve_backend_sandbox_paths: bool,
    max_string_chars: int | None,
) -> Any:
    """Redact a dict value if the key indicates sensitive content.

    Backend-owned sandbox path keys are excluded from path redaction
    because they must survive the event persistence pipeline for
    later stage resolution.  The sandbox path is always generated by
    the orchestrator from a validated result contract and is never
    user-supplied.
    """
    lowered = key.lower()
    if _PUBLIC_PROMPT_KEY_RE.search(lowered) or _PUBLIC_INTERNAL_DETAIL_KEY_RE.search(lowered):
        return "[redacted]"
    if _SECRET_KEY_RE.search(lowered):
        return "[redacted]"
    if _PUBLIC_PROCESS_KEY_RE.search(lowered):
        return "[redacted]"
    # Backend-owned sandbox roots must survive redaction so
    # _resolve_stage_sandbox_root can reconstruct the stage
    # sandbox from event payloads.
    if preserve_backend_sandbox_paths and lowered in _BACKEND_SANDBOX_PATH_KEYS and isinstance(value, str):
        stripped = value.strip()
        # Reject obviously unsafe values even for sandbox keys.
        if not stripped or any(part == ".." for part in Path(stripped).parts):
            return "[redacted]"
        return stripped
    if "path" in lowered and isinstance(value, str):
        return redact_absolute_paths(value)
    if isinstance(value, str):
        return redact_public_message(value, max_chars=max_string_chars)
    return redact_public_value(
        value,
        preserve_backend_sandbox_paths=preserve_backend_sandbox_paths,
        max_string_chars=max_string_chars,
    )


def _bound_public_text(text: str, *, max_chars: int | None) -> str:
    if max_chars is None or len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n[... public text truncated at {max_chars} chars ...]"


# ── Patch preview redaction (F15-JOB-109) ────────────────────────────

# Default max chars for a patch preview
DEFAULT_PATCH_PREVIEW_CHAR_LIMIT = 10_000

# Patterns for secrets commonly found in patches
_PATCH_SECRET_PATTERNS: list[tuple[str, str]] = [
    (r'password\s*=\s*\S+', 'password=[redacted]'),
    (r'api[_-]?key\s*=\s*\S+', 'api_key=[redacted]'),
    (r'token\s*=\s*\S+', 'token=[redacted]'),
    (r'secret\s*=\s*\S+', 'secret=[redacted]'),
    (r'access[_-]?key[-_=]?\S+', 'access_key=[redacted]'),
    (r'secret[_-]?key[-_=]?\S+', 'secret_key=[redacted]'),
]


_DEFAULT_PATCH_SECRET_RE = re.compile(
    "|".join(pattern for pattern, _ in _PATCH_SECRET_PATTERNS),
    re.IGNORECASE,
)


def redact_patch_preview(
    patch_content: str,
    *,
    max_chars: int = DEFAULT_PATCH_PREVIEW_CHAR_LIMIT,
    redact_secrets: bool = True,
    redact_paths: bool = True,
) -> str:
    """Redact a repair patch preview for safe display.

    Applies:
      1. Absolute path redaction (sandbox paths, user-specific paths)
      2. Secret value redaction (passwords, tokens, API keys)
      3. Size bounding with omitted-section markers

    Args:
        patch_content: Raw patch/unified-diff content.
        max_chars: Maximum characters for the preview.
        redact_secrets: Whether to redact secret-like values.
        redact_paths: Whether to redact absolute paths.

    Returns:
        Redacted, bounded patch preview.
    """
    result = patch_content

    # 1. Redact absolute paths (sandbox, user home, tmp, etc.)
    if redact_paths:
        result = redact_absolute_paths(result)

    # 2. Redact secret-like values
    if redact_secrets:
        result = _DEFAULT_PATCH_SECRET_RE.sub(
            lambda m: _PATCH_SECRET_PATTERNS[m.lastindex - 1][1]
            if m.lastindex and m.lastindex <= len(_PATCH_SECRET_PATTERNS)
            else "[redacted]",
            result,
        )

    # 3. Size bounding
    if len(result) > max_chars:
        result = result[:max_chars] + "\n[... patch preview truncated at {} chars ...]".format(max_chars)

    return result
