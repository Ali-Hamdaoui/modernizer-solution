from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration_factory.control_tower.application.redaction import redact_model_summary


_ALLOWED_RUN_FILENAMES = (
    "phase2_transform.log",
    "orchestration_summary.json",
    "test_agent.log",
)
_ALLOWED_BUILD_ERROR_GLOB = "build-error*.json"
_MAX_SNIPPET_CHARS = 700
_MAX_TOTAL_CHARS = 3200
_SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{8,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r'(?i)"[^"]*(password|secret|token|api[_-]?key)[^"]*"\s*:\s*"[^"]+"'),
    re.compile(r"(?i)\b[a-z_][a-z0-9_-]{2,}\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)(password|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]+"),
)
_PATH_TRAVERSAL_MARKERS = ("..", "~")


@dataclass(frozen=True)
class EvidenceSnippet:
    source: str
    label: str
    text: str


@dataclass(frozen=True)
class FailureEvidencePack:
    run_id: str
    event_type: str
    snippets: tuple[EvidenceSnippet, ...]
    missing_artifacts: tuple[str, ...]
    affected_paths: tuple[str, ...]
    redaction_status: str
    total_chars: int


class FailureEvidenceCollector:
    def __init__(
        self,
        *,
        max_snippet_chars: int = _MAX_SNIPPET_CHARS,
        max_total_chars: int = _MAX_TOTAL_CHARS,
    ) -> None:
        self._max_snippet_chars = max_snippet_chars
        self._max_total_chars = max_total_chars

    def collect(
        self,
        *,
        run_id: str,
        event_type: str,
        run_dir: str | Path | None,
        sandbox_path: str | Path | None,
        artifact_refs: dict[str, Any] | None,
        payload: dict[str, Any] | None,
    ) -> FailureEvidencePack:
        payload_data = payload if isinstance(payload, dict) else {}
        run_root = self._resolve_root(run_dir)
        sandbox_root = self._resolve_root(sandbox_path)
        allowed_roots = tuple(root for root in (run_root, sandbox_root) if root is not None)

        snippets: list[EvidenceSnippet] = []
        missing: list[str] = []
        affected_paths: list[str] = []
        total_chars = 0

        def add_snippet(source: str, label: str, text: str) -> None:
            nonlocal total_chars
            if total_chars >= self._max_total_chars:
                return
            cleaned = self._sanitize_text(text)
            if not cleaned:
                return
            remaining = self._max_total_chars - total_chars
            bounded = cleaned[: min(self._max_snippet_chars, remaining)].strip()
            if not bounded:
                return
            snippets.append(EvidenceSnippet(source=source, label=label, text=bounded))
            total_chars += len(bounded)

        for field in (
            "message",
            "stderr",
            "stdout_tail",
            "build_status",
            "test_status",
            "transform_status",
        ):
            value = payload_data.get(field)
            if isinstance(value, str) and value.strip():
                add_snippet("event_payload", field, value)

        artifact_refs_data = artifact_refs if isinstance(artifact_refs, dict) else {}
        if artifact_refs_data:
            add_snippet(
                "event_payload",
                "artifact_refs",
                json.dumps(
                    {str(k): self._display_path(v) for k, v in artifact_refs_data.items()},
                    sort_keys=True,
                ),
            )

        for filename in _ALLOWED_RUN_FILENAMES:
            candidate = self._candidate_in_run(run_root, filename)
            if candidate is None or not candidate.is_file():
                missing.append(filename)
                continue
            add_snippet(filename, filename, self._read_text(candidate))
            affected_paths.append(filename)

        if run_root is not None:
            matches = sorted(run_root.rglob(_ALLOWED_BUILD_ERROR_GLOB))
            if matches:
                for match in matches[:2]:
                    add_snippet("build_error_contract", match.name, self._read_text(match))
                    affected_paths.append(match.name)
            else:
                missing.append(_ALLOWED_BUILD_ERROR_GLOB)
        else:
            missing.append(_ALLOWED_BUILD_ERROR_GLOB)

        summary_ref = self._pick_artifact_ref(
            artifact_refs_data,
            ("orchestration_summary", "summary", "orchestration_summary.json"),
        )
        if summary_ref:
            summary_path = self._resolve_allowed_path(summary_ref, allowed_roots)
            if summary_path is not None and summary_path.is_file():
                add_snippet("artifact_ref", "orchestration_summary", self._read_text(summary_path))
                affected_paths.append(summary_path.name)
            else:
                missing.append("artifact_ref:orchestration_summary")

        test_log_ref = self._pick_artifact_ref(
            artifact_refs_data,
            ("post_transform_test_log", "test_agent_log", "test_log"),
        )
        if test_log_ref:
            test_log_path = self._resolve_allowed_path(test_log_ref, allowed_roots)
            if test_log_path is not None and test_log_path.is_file():
                add_snippet("artifact_ref", "test_agent.log", self._read_text(test_log_path))
                affected_paths.append(test_log_path.name)

        if sandbox_root is not None:
            pom_path = self._resolve_allowed_path(sandbox_root / "pom.xml", (sandbox_root,))
            if pom_path is not None and pom_path.is_file():
                add_snippet("sandbox", "pom.xml", self._read_text(pom_path))
                affected_paths.append("pom.xml")
            else:
                missing.append("pom.xml")
        else:
            missing.append("pom.xml")

        redaction_status = "redacted"
        if not snippets and missing:
            redaction_status = "redacted_missing_artifacts"

        return FailureEvidencePack(
            run_id=run_id,
            event_type=event_type,
            snippets=tuple(snippets),
            missing_artifacts=tuple(dict.fromkeys(missing)),
            affected_paths=tuple(dict.fromkeys(affected_paths)),
            redaction_status=redaction_status,
            total_chars=total_chars,
        )

    def _resolve_root(self, raw_path: str | Path | None) -> Path | None:
        if raw_path in (None, ""):
            return None
        text = str(raw_path).strip()
        if not text or any(marker in text for marker in _PATH_TRAVERSAL_MARKERS):
            raise ValueError(f"Rejected unsafe path: {raw_path!r}")
        return Path(text).resolve()

    def _candidate_in_run(self, run_root: Path | None, filename: str) -> Path | None:
        if run_root is None:
            return None
        candidate = (run_root / filename).resolve()
        return candidate if self._is_within(candidate, run_root) else None

    def _resolve_allowed_path(
        self,
        raw_path: str | Path,
        allowed_roots: tuple[Path, ...],
    ) -> Path | None:
        text = str(raw_path).strip()
        if not text or any(marker in text for marker in _PATH_TRAVERSAL_MARKERS):
            raise ValueError(f"Rejected unsafe path: {raw_path!r}")
        candidate = Path(text)
        if not candidate.is_absolute():
            for root in allowed_roots:
                resolved = (root / candidate).resolve()
                if self._is_within(resolved, root):
                    return resolved
            return None
        resolved = candidate.resolve()
        for root in allowed_roots:
            if self._is_within(resolved, root):
                return resolved
        return None

    def _is_within(self, path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _pick_artifact_ref(
        self,
        artifact_refs: dict[str, Any],
        keys: tuple[str, ...],
    ) -> str:
        for key in keys:
            value = artifact_refs.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    def _read_text(self, path: Path) -> str:
        try:
            if path.suffix.lower() == ".json":
                payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                return json.dumps(payload, indent=2, sort_keys=True)
            return path.read_text(encoding="utf-8", errors="replace")
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return ""

    def _display_path(self, value: Any) -> str:
        text = str(value or "")
        if not text:
            return ""
        return Path(text).name or text

    def _sanitize_text(self, text: str) -> str:
        result = text
        for pattern in _SECRET_PATTERNS:
            result = pattern.sub("[REDACTED]", result)
        result = redact_model_summary(result)
        return result.strip()
