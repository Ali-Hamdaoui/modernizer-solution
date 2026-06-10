"""Command manifest model and checksum verification."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from migration_factory.control_tower.domain.errors import ManifestIntegrityError
from migration_factory.control_tower.schemas.common import StrictModel


class CommandManifest(StrictModel):
    schema_version: str
    job_id: str
    command_id: str
    worker_id: str
    operation: str
    run_configuration_artifact_id: str
    run_configuration_checksum: str
    working_directory_root_id: str
    working_directory_relative_path: str
    stdout_relative_path: str
    stderr_relative_path: str
    result_relative_path: str
    spool_relative_path: str
    timeout_seconds: int
    max_stdout_bytes: int
    max_stderr_bytes: int
    event_schema_version: str
    created_at: str
    manifest_checksum: str = ""


def _manifest_dict_without_checksum(manifest: CommandManifest) -> dict[str, Any]:
    d = manifest.model_dump(mode="json")
    d.pop("manifest_checksum", None)
    return d


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def compute_manifest_checksum(manifest: CommandManifest) -> str:
    d = _manifest_dict_without_checksum(manifest)
    return hashlib.sha256(_canonical_json_bytes(d)).hexdigest()


def verify_manifest_checksum(manifest: CommandManifest) -> None:
    d = _manifest_dict_without_checksum(manifest)
    expected = hashlib.sha256(_canonical_json_bytes(d)).hexdigest()
    if manifest.manifest_checksum != expected:
        raise ManifestIntegrityError(
            f"Manifest checksum mismatch for command {manifest.command_id!r}: "
            f"stored {manifest.manifest_checksum}, computed {expected}"
        )
