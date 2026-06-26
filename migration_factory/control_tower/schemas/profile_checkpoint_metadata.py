"""F3-T6 Profile checkpoint metadata — defines how source/target profile
choices are persisted on artifacts and checkpoints.

This module provides the canonical metadata structure that must appear
in checkpoint artifacts, artifact revisions, and any persistence layer
that records profile-based migration routing decisions.

The metadata captures:
  - Selected source and target profiles
  - Derived stage route (included, excluded, skipped stages)
  - Validation outcome and reason
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field

from .common import StrictModel


# ── Safe checkpoint fields ──────────────────────────────────────────

# Fields that are safe to include in checkpoint/artifact metadata.
# These are profile-routing metadata fields — NOT provider, model,
# env, sandbox, or command fields.
PROFILE_CHECKPOINT_FIELDS: frozenset[str] = frozenset({
    "source_profile",
    "target_profile",
    "source_level",
    "target_level",
    "included_stages",
    "excluded_stages",
    "skipped_stages",
    "valid",
    "reason",
})


# ── CheckpointProfileMetadata ─────────────────────────────────────────

class CheckpointProfileMetadata(StrictModel):
    """Profile routing metadata persisted on artifacts and checkpoints.

    Captures the source/target profile selection and the resulting
    stage route decisions. This metadata is stored alongside artifact
    revisions so that downstream consumers (audit, resume, reporting)
    can determine which profile route was in effect.

    Design invariants:
      - All fields have safe defaults (empty strings, -1, empty tuples).
      - Never exposes provider, model, deployment, sandbox_path, argv,
        env, or raw command fields.
      - JSON-serializable via to_dict()/to_json() for artifact storage.
    """

    source_profile: str = ""
    target_profile: str = ""
    source_level: int = Field(default=-1, ge=-1)
    target_level: int = Field(default=-1, ge=-1)
    included_stages: tuple[int, ...] = Field(default_factory=tuple)
    excluded_stages: tuple[int, ...] = Field(default_factory=tuple)
    skipped_stages: tuple[int, ...] = Field(default_factory=tuple)
    valid: bool = False
    reason: str = ""

    # ── Serialization ───────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON storage or API responses."""
        return {
            "source_profile": self.source_profile,
            "target_profile": self.target_profile,
            "source_level": self.source_level,
            "target_level": self.target_level,
            "included_stages": list(self.included_stages),
            "excluded_stages": list(self.excluded_stages),
            "skipped_stages": list(self.skipped_stages),
            "valid": self.valid,
            "reason": self.reason,
        }

    def to_json(self) -> str:
        """Serialize to a JSON string for artifact_refs_json storage."""
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CheckpointProfileMetadata":
        """Deserialize from a plain dict.

        Guards against None values because dict[str, Any] callers may
        pass keys with None values (e.g. from database NULL columns).
        absent keys fall back to safe defaults; present-but-None keys
        are also treated as absent for safety.
        """
        sp = data.get("source_profile")
        tp = data.get("target_profile")
        sl = data.get("source_level")
        tl = data.get("target_level")
        inc = data.get("included_stages")
        exc = data.get("excluded_stages")
        skp = data.get("skipped_stages")
        v = data.get("valid")
        r = data.get("reason")

        return cls(
            source_profile=str(sp) if sp is not None else "",
            target_profile=str(tp) if tp is not None else "",
            source_level=int(sl) if sl is not None else -1,
            target_level=int(tl) if tl is not None else -1,
            included_stages=(
                tuple(int(s) for s in inc) if inc is not None else ()
            ),
            excluded_stages=(
                tuple(int(s) for s in exc) if exc is not None else ()
            ),
            skipped_stages=(
                tuple(int(s) for s in skp) if skp is not None else ()
            ),
            valid=bool(v) if v is not None else False,
            reason=str(r) if r is not None else "",
        )

    @classmethod
    def from_json(cls, json_str: str) -> "CheckpointProfileMetadata":
        """Deserialize from a JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def from_profile_route(cls, route: Any) -> "CheckpointProfileMetadata":
        """Create from a ProfileRoute (from v2_stage_progression).

        Uses getattr to avoid a hard import dependency on the
        application-layer ProfileRoute dataclass.
        """
        return cls(
            source_profile=getattr(route, "source_profile", ""),
            target_profile=getattr(route, "target_profile", ""),
            source_level=getattr(route, "source_level", -1),
            target_level=getattr(route, "target_level", -1),
            included_stages=getattr(route, "included_stages", ()),
            excluded_stages=getattr(route, "excluded_stages", ()),
            skipped_stages=getattr(route, "skipped_stages", ()),
            valid=getattr(route, "valid", False),
            reason=getattr(route, "reason", ""),
        )

    # ── Derived properties ──────────────────────────────────────────

    @property
    def has_profiles(self) -> bool:
        """True if both source and target profiles are specified."""
        return bool(self.source_profile and self.target_profile)

    @property
    def stage_count(self) -> int:
        """Number of included stages in the route."""
        return len(self.included_stages)

    @property
    def is_no_op(self) -> bool:
        """True when source equals target (no migration stages needed)."""
        return (
            self.has_profiles
            and self.source_profile == self.target_profile
        )
