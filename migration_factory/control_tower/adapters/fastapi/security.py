"""Local-only FastAPI security and readiness settings for Control Tower."""

from __future__ import annotations

from dataclasses import dataclass
import getpass
import os
from pathlib import Path
import sys
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4

from migration_factory.control_tower.application.redaction import (
    redact_public_api_value,
    redact_public_message,
)


MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
DEFAULT_FRONTEND_CLIENT_ID = "control-tower-frontend"


@dataclass(frozen=True, slots=True)
class ActorIdentity:
    actor_type: str
    actor_id: str


class ActorProvider(Protocol):
    def current_actor(self) -> ActorIdentity: ...


class OperatingSystemActorProvider:
    """Derive local operator identity from OS account running the API."""

    def current_actor(self) -> ActorIdentity:
        return ActorIdentity(actor_type="local_operator", actor_id=getpass.getuser())


@dataclass(frozen=True, slots=True)
class LocalApiSecuritySettings:
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    frontend_host: str = "127.0.0.1"
    frontend_port: int = 3000
    frontend_client_id: str = DEFAULT_FRONTEND_CLIENT_ID

    def __post_init__(self) -> None:
        for field_name, value in (
            ("api_host", self.api_host),
            ("frontend_host", self.frontend_host),
        ):
            if value != "127.0.0.1":
                raise ValueError(f"{field_name} must be '127.0.0.1', not {value!r}")
        for field_name, value in (
            ("api_port", self.api_port),
            ("frontend_port", self.frontend_port),
        ):
            if value <= 0 or value > 65535:
                raise ValueError(f"{field_name} must be a valid TCP port")
        if "localhost" in {self.api_host, self.frontend_host}:
            raise ValueError("supported config must not mix or use localhost; use 127.0.0.1")

    @property
    def api_origin(self) -> str:
        return f"http://{self.api_host}:{self.api_port}"

    @property
    def frontend_origin(self) -> str:
        return f"http://{self.frontend_host}:{self.frontend_port}"

    @property
    def trusted_api_host(self) -> str:
        return f"{self.api_host}:{self.api_port}"

    @property
    def cors_allowed_methods(self) -> tuple[str, ...]:
        return ("GET", "POST")

    @property
    def cors_allowed_headers(self) -> tuple[str, ...]:
        return (
            "Content-Type",
            "X-Control-Tower-Client",
            "Idempotency-Key",
            "If-Match",
        )


def generate_correlation_id() -> str:
    return uuid4().hex


def normalize_correlation_id(value: str | None) -> str:
    if value and 1 <= len(value) <= 128:
        return value
    return generate_correlation_id()


def redact_public_data(value: Any) -> Any:
    return redact_public_api_value(value)


def public_error_payload(code: str, message: str, correlation_id: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": redact_public_message(message),
            "correlation_id": correlation_id,
        }
    }


def dependency_versions() -> dict[str, str]:
    import fastapi

    return {
        "python": sys.version.split()[0],
        "fastapi": fastapi.__version__,
        "sqlite": getattr(__import__("sqlite3"), "sqlite_version"),
    }


def path_accessible(path: Path) -> bool:
    return path.exists() and os.access(path, os.R_OK)


def parse_origin(value: str) -> tuple[str, str, int]:
    parsed = urlparse(value)
    port = parsed.port
    if parsed.scheme != "http" or parsed.hostname is None or port is None:
        raise ValueError(f"Origin must be exact http origin with explicit port: {value!r}")
    return parsed.scheme, parsed.hostname, port
