"""Canonical JSON and checksum helpers for persisted Control Tower payloads."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def canonical_json_text(payload: Any) -> str:
    return canonical_json_bytes(payload).decode("utf-8")


def sha256_canonical_json(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
