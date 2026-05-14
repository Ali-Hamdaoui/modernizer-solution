import json
import subprocess
from pathlib import Path

from openrewrite_adapter import run_openrewrite_dryrun


class DummyContext:
    def __init__(self, legacy_app_path: Path, output_dir: Path):
        self.legacy_app_path = str(legacy_app_path)
        self.output_dir = output_dir

    def get_output_path(self, name: str):
        return str(self.output_dir / name)


def test_skipped_when_maven_missing(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy"
    output = tmp_path / "out"
    legacy.mkdir()
    output.mkdir()

    def _missing(*args, **kwargs):
        raise FileNotFoundError("mvn not found")

    monkeypatch.setattr("subprocess.run", _missing)

    result = run_openrewrite_dryrun(DummyContext(legacy, output))

    assert result["status"] == "skipped"
    assert "warnings" in result and result["warnings"]

    preview = json.loads((output / "rewrite_preview.json").read_text())
    assert preview["status"] == "skipped"


def test_success_captures_patch(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy"
    output = tmp_path / "out"
    legacy.mkdir()
    output.mkdir()

    patch = legacy / "rewrite.patch"
    patch.write_text("diff --git a/A b/A\n")

    def _ok(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", _ok)

    result = run_openrewrite_dryrun(DummyContext(legacy, output))

    assert result["status"] == "used"
    assert result.get("patch_file") == "rewrite_dry_run.patch"
    assert (output / "rewrite_dry_run.patch").exists()

    preview = json.loads((output / "rewrite_preview.json").read_text())
    assert preview["status"] == "used"
    assert preview["patch_file"] == "rewrite_dry_run.patch"


def test_failure_is_non_blocking_and_writes_warning(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy"
    output = tmp_path / "out"
    legacy.mkdir()
    output.mkdir()

    def _fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], "", "boom")

    monkeypatch.setattr("subprocess.run", _fail)

    result = run_openrewrite_dryrun(DummyContext(legacy, output))

    assert result["status"] == "failed"
    assert result["warnings"]

    preview = json.loads((output / "rewrite_preview.json").read_text())
    assert preview["status"] == "failed"
    assert preview["warnings"]
