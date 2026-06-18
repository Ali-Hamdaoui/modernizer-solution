from __future__ import annotations

import re
from typing import Any

from migration_factory.control_tower.application.redaction import redact_model_summary
from migration_factory.control_tower.application.v2_failure_evidence import (
    EvidenceSnippet,
    FailureEvidencePack,
)


_WILDCARD_VERSION_RE = re.compile(r"<version>\s*[^<\s]+\.x\s*</version>", re.IGNORECASE)
_WILDCARD_PROPERTY_VERSION_RE = re.compile(
    r"<[A-Za-z0-9_.-]*version[A-Za-z0-9_.-]*>\s*[0-9]+(?:\.[0-9]+)*\.x\s*</[A-Za-z0-9_.-]*version[A-Za-z0-9_.-]*>",
    re.IGNORECASE,
)
_BOOT3_CONTEXT_RE = re.compile(r"(spring-boot[^\\n<]*3\.[0-9]|jakarta)", re.IGNORECASE)
_JAVAX_DEPENDENCY_RE = re.compile(r"javax\.(persistence|servlet)", re.IGNORECASE)
_JAVAX_NAMESPACE_RE = re.compile(r"package\s+javax\.[^\s]+", re.IGNORECASE)
_DOES_NOT_EXIST_RE = re.compile(r"does not exist", re.IGNORECASE)
_SOURCE_TARGET_RE = re.compile(r"(source option|target release).*(unsupported|invalid|not supported)", re.IGNORECASE)
_WILDCARD_COORD_RE = re.compile(
    r"[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:(?:[A-Za-z0-9_.-]+:)?[A-Za-z0-9_.-]*\.x\b",
    re.IGNORECASE,
)
_MAVEN_REPO_WILDCARD_PATH_RE = re.compile(
    r"/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*/[0-9]+(?:\.[0-9]+)*\.x/[A-Za-z0-9_.-]+(?:-[0-9]+(?:\.[0-9]+)*\.x)?\.(?:pom|jar)\b",
    re.IGNORECASE,
)
_PROPERTY_LINE_RE = re.compile(
    r"<(?:javax\.(?:persistence|servlet)\.version)>\s*[0-9]+(?:\.[0-9]+)*\.x\s*</(?:javax\.(?:persistence|servlet)\.version)>",
    re.IGNORECASE,
)
_JAR_OR_POM_COORD_RE = re.compile(
    r"[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:(?:jar|pom):[0-9]+(?:\.[0-9]+)*\.x\b",
    re.IGNORECASE,
)
_SNIPPET_SOURCE_PRIORITY = {
    "sandbox": 0,
    "build_error_contract": 1,
    "phase2_transform.log": 2,
    "orchestration_summary.json": 3,
    "artifact_ref": 4,
    "event_payload": 5,
}


def classify_failure(
    *,
    evidence_pack: FailureEvidencePack,
    payload: dict[str, Any] | None,
    stage_index: int,
    event_type: str,
) -> dict[str, Any]:
    payload_data = payload if isinstance(payload, dict) else {}
    snippet_blobs = [snippet.classification_text or snippet.raw_text or snippet.text for snippet in evidence_pack.snippets]
    blob = "\n".join(
        [
            *snippet_blobs,
            *(str(payload_data.get(field, "")) for field in (
                "message",
                "stderr",
                "stdout_tail",
                "build_status",
                "test_status",
                "transform_status",
            )),
        ]
    )
    normalized = blob.lower()
    ranked_snippets = sorted(
        evidence_pack.snippets,
        key=lambda snippet: (
            _SNIPPET_SOURCE_PRIORITY.get(snippet.source, 10),
            _SNIPPET_SOURCE_PRIORITY.get(snippet.label, 10),
        ),
    )
    evidence = [
        {
            "source": snippet.source,
            "label": snippet.label,
            "text": snippet.text,
        }
        for snippet in ranked_snippets[:4]
    ]
    affected_paths = list(evidence_pack.affected_paths)
    file_backed_sources = {
        snippet.source
        for snippet in evidence_pack.snippets
        if snippet.source not in {"event_payload"}
    }

    if "illegalaccesserror" in normalized and "lombok" in normalized and (
        stage_index == 1 or "stage 1" in normalized or "java 17" in normalized or "jdk 17" in normalized
    ):
        return _result(
            failure_type="stage1_wrong_jdk_lombok",
            likely_root_cause="Stage 1 build likely using Lombok with incompatible JDK/module access settings.",
            confidence="high",
            evidence=evidence,
            recommended_fix_type="align_lombok_and_jdk_for_stage1",
            affected_paths=affected_paths,
            validation_plan="Check Stage 1 Java version and Lombok version, update build config, rerun compile in sandbox.",
            requires_human_review=False,
        )

    if (
        _WILDCARD_VERSION_RE.search(blob)
        or _WILDCARD_PROPERTY_VERSION_RE.search(blob)
        or _WILDCARD_COORD_RE.search(blob)
        or _MAVEN_REPO_WILDCARD_PATH_RE.search(blob)
    ):
        return _result(
            failure_type="invalid_maven_wildcard_version",
            likely_root_cause=(
                "Generated or transformed pom.xml contains invalid wildcard Maven versions such as 3.0.x or 5.0.x. "
                "Maven cannot resolve wildcard dependency/plugin versions; PKIX appears during attempted downloads, "
                "but deterministic actionable root cause is invalid wildcard version syntax."
            ),
            confidence="high",
            evidence=_wildcard_evidence(ranked_snippets) or evidence,
            recommended_fix_type="pin_exact_maven_version",
            affected_paths=affected_paths or ["pom.xml"],
            validation_plan="Replace wildcard version with exact managed version and rerun Maven dependency resolution in sandbox.",
            requires_human_review=False,
        )

    if "pkix path building failed" in normalized:
        return _result(
            failure_type="maven_truststore_pkix",
            likely_root_cause="Maven/TLS truststore validation failed with PKIX path building error.",
            confidence="high",
            evidence=evidence,
            recommended_fix_type="update_truststore_or_repository_certificates",
            affected_paths=affected_paths,
            validation_plan="Verify repository certificate chain, truststore config, then rerun Maven build in sandbox.",
            requires_human_review=True,
        )

    if _JAVAX_NAMESPACE_RE.search(blob) and _DOES_NOT_EXIST_RE.search(blob):
        return _result(
            failure_type="jakarta_namespace_issue",
            likely_root_cause="Compilation still references javax package names that no longer exist after Jakarta migration.",
            confidence="high",
            evidence=evidence,
            recommended_fix_type="rename_javax_imports_to_jakarta",
            affected_paths=affected_paths,
            validation_plan="Update imports/packages to jakarta namespace where required, then rerun compile/test in sandbox.",
            requires_human_review=False,
        )

    if _BOOT3_CONTEXT_RE.search(blob) and _JAVAX_DEPENDENCY_RE.search(blob):
        return _result(
            failure_type="jakarta_migration_dependency_issue",
            likely_root_cause="Boot 3/Jakarta migration context still depends on javax-era servlet or persistence APIs.",
            confidence="medium",
            evidence=evidence,
            recommended_fix_type="align_dependencies_with_jakarta",
            affected_paths=affected_paths,
            validation_plan="Review Boot 3 dependency tree, replace javax-era artifacts with Jakarta-compatible coordinates, rerun build.",
            requires_human_review=False,
        )

    if _SOURCE_TARGET_RE.search(blob):
        return _result(
            failure_type="compiler_source_target_issue",
            likely_root_cause="Configured compiler source/target release is unsupported by active JDK.",
            confidence="high",
            evidence=evidence,
            recommended_fix_type="align_compiler_release_with_jdk",
            affected_paths=affected_paths,
            validation_plan="Check Maven compiler source/target or release value against sandbox JDK, then rerun build.",
            requires_human_review=False,
        )

    if "no plugin found for prefix 'rewrite'" in normalized:
        return _result(
            failure_type="openrewrite_plugin_resolution_issue",
            likely_root_cause="Maven could not resolve OpenRewrite plugin prefix.",
            confidence="high",
            evidence=evidence,
            recommended_fix_type="configure_openrewrite_plugin_coordinates",
            affected_paths=affected_paths or ["pom.xml"],
            validation_plan="Confirm rewrite plugin declaration or fully qualified goal, then rerun transform/build in sandbox.",
            requires_human_review=False,
        )

    if evidence_pack.missing_artifacts and not file_backed_sources:
        return _result(
            failure_type="unknown_build_failure",
            likely_root_cause="Missing failure artifacts: " + ", ".join(evidence_pack.missing_artifacts),
            confidence="low",
            evidence=evidence,
            recommended_fix_type="collect_missing_artifacts",
            affected_paths=affected_paths,
            validation_plan="Collect listed artifacts from run directory or sandbox, then rerun deterministic diagnosis.",
            requires_human_review=False,
        )

    return _result(
        failure_type="unknown_build_failure",
        likely_root_cause=f"Unable to deterministically classify {event_type}.",
        confidence="low",
        evidence=evidence,
        recommended_fix_type="inspect_available_failure_evidence",
        affected_paths=affected_paths,
        validation_plan=(
            "Review bounded stderr/stdout plus available artifacts, gather missing evidence if any, then rerun diagnosis."
        ),
        requires_human_review=True,
    )


def _result(
    *,
    failure_type: str,
    likely_root_cause: str,
    confidence: str,
    evidence: list[dict[str, Any]],
    recommended_fix_type: str,
    affected_paths: list[str],
    validation_plan: str,
    requires_human_review: bool,
) -> dict[str, Any]:
    return {
        "failure_type": failure_type,
        "severity": "BLOCKER",
        "migration_blocker": True,
        "security_env_warning": False,
        "likely_root_cause": likely_root_cause,
        "confidence": confidence,
        "evidence": evidence,
        "recommended_fix_type": recommended_fix_type,
        "recommended_next_step": validation_plan,
        "affected_paths": affected_paths,
        "validation_plan": validation_plan,
        "send_to_copilot": False,
        "requires_human_review": requires_human_review,
    }


def _wildcard_evidence(snippets: list[EvidenceSnippet]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    patterns = (_PROPERTY_LINE_RE, _JAR_OR_POM_COORD_RE, _MAVEN_REPO_WILDCARD_PATH_RE)
    for snippet in snippets:
        raw = snippet.classification_text or snippet.raw_text or snippet.text
        for pattern in patterns:
            for match in pattern.finditer(raw):
                text = _safe_wildcard_match_text(match.group(0), pattern=pattern)
                key = (snippet.label, text)
                if not text or key in seen:
                    continue
                evidence.append(
                    {
                        "source": snippet.source,
                        "label": snippet.label,
                        "text": text,
                    }
                )
                seen.add(key)
                if len(evidence) >= 4:
                    return evidence
    return evidence


def _safe_wildcard_match_text(value: str, *, pattern: re.Pattern[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if pattern is _MAVEN_REPO_WILDCARD_PATH_RE:
        return redact_model_summary(text).strip()
    return text
