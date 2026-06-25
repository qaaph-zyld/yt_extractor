"""Tests for preflight checks (ffmpeg presence, output-dir writability)."""

from __future__ import annotations

import pytest

from ytmp3dl import preflight
from ytmp3dl.errors import PreflightError


def test_check_ffmpeg_present(monkeypatch):
    def fake_which(name):
        return f"/usr/bin/{name}"

    monkeypatch.setattr(preflight.shutil, "which", fake_which)
    ffmpeg, ffprobe = preflight.check_ffmpeg()
    assert ffmpeg == "/usr/bin/ffmpeg"
    assert ffprobe == "/usr/bin/ffprobe"


def test_check_ffmpeg_absent_raises_with_hint(monkeypatch):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None)
    with pytest.raises(PreflightError) as exc:
        preflight.check_ffmpeg()
    msg = str(exc.value)
    assert "ffmpeg" in msg
    assert "ffprobe" in msg
    # Hint mentions an install mechanism for the current OS.
    assert "install" in msg.lower()


def test_check_ffmpeg_partial_absent(monkeypatch):
    # ffmpeg present but ffprobe missing -> still an error naming ffprobe.
    monkeypatch.setattr(
        preflight.shutil,
        "which",
        lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None,
    )
    with pytest.raises(PreflightError) as exc:
        preflight.check_ffmpeg()
    # The "not found" line lists only what is actually missing.
    first_line = str(exc.value).splitlines()[0]
    assert "ffprobe" in first_line
    assert "ffmpeg" not in first_line  # ffmpeg was present, so not in the missing list


def test_check_ffmpeg_honors_explicit_location(monkeypatch, tmp_path):
    # Simulate binaries under an explicit folder; PATH lookup returns nothing.
    monkeypatch.setattr(preflight.shutil, "which", lambda name: None)
    bindir = tmp_path / "ff" / "bin"
    bindir.mkdir(parents=True)
    for name in ("ffmpeg", "ffprobe"):
        f = bindir / name
        f.write_text("#!/bin/sh\n")
        f.chmod(0o755)
    ffmpeg, ffprobe = preflight.check_ffmpeg(ffmpeg_location=str(bindir))
    assert ffmpeg == str(bindir / "ffmpeg")
    assert ffprobe == str(bindir / "ffprobe")


def test_check_output_dir_creates_and_returns(tmp_path):
    target = tmp_path / "a" / "b"
    result = preflight.check_output_dir(target)
    assert result == target
    assert target.is_dir()


def test_check_output_dir_unwritable(monkeypatch, tmp_path):
    target = tmp_path / "ro"
    target.mkdir()

    # Force the writability probe to fail regardless of real perms.
    import tempfile

    def boom(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", boom)
    with pytest.raises(PreflightError, match="not writable"):
        preflight.check_output_dir(target)


def test_check_ytdlp_returns_version():
    version = preflight.check_ytdlp()
    assert isinstance(version, str)
    assert version  # non-empty


def test_run_preflight_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.shutil, "which", lambda name: f"/usr/bin/{name}")
    result = preflight.run_preflight(output_dir=str(tmp_path / "out"))
    assert result.ffmpeg_path == "/usr/bin/ffmpeg"
    assert result.ffprobe_path == "/usr/bin/ffprobe"
    assert result.output_dir.is_dir()
    assert result.ytdlp_version
