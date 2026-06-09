"""Canonical JSON and checksum helpers for Control Tower payloads."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any


def canonical_json_bytes(payload: Any) -> bytes:
    return canonical_json(payload).encode("utf-8")


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def sha256_checksum(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
