from pathlib import Path


IGNORED_DIR_NAMES = {
    ".gradle",
    ".mvn",
    ".pytest_cache",
    "__pycache__",
    "build",
    "node_modules",
    "target",
}


def is_ignored_generated_path(relative_path: str) -> bool:
    parts = Path(relative_path).parts
    return any(part in IGNORED_DIR_NAMES for part in parts)
