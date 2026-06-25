"""Preflight checks: fail fast with actionable messages.

Before any enumeration or download work, verify the environment is ready:

* ``ffmpeg`` and ``ffprobe`` are available (on ``PATH`` or under an explicit
  ``--ffmpeg-location``) -- they are required for audio extraction, metadata,
  and thumbnail embedding.
* ``yt-dlp`` imports, and its version is logged for reproducibility.
* The output directory exists (or can be created) and is writable.

Any failure raises :class:`~ytmp3dl.errors.PreflightError` with a per-OS hint.
"""

from __future__ import annotations

import os
import platform
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ytmp3dl.errors import PreflightError
from ytmp3dl.logging_setup import get_logger

logger = get_logger()


def _ffmpeg_install_hint() -> str:
    """Return an OS-appropriate hint for installing ffmpeg."""
    system = platform.system()
    if system == "Windows":
        return (
            "Install ffmpeg, e.g.:\n"
            "  winget install Gyan.FFmpeg\n"
            "  (or: choco install ffmpeg / scoop install ffmpeg)\n"
            "or download a build from https://www.gyan.dev/ffmpeg/builds/ and "
            "either add its 'bin' folder to PATH or pass --ffmpeg-location "
            "<path-to-bin>."
        )
    if system == "Darwin":
        return (
            "Install ffmpeg, e.g.:\n"
            "  brew install ffmpeg\n"
            "or download a build from https://evermeet.cx/ffmpeg/ and pass "
            "--ffmpeg-location <path-to-bin>."
        )
    # Linux / other
    return (
        "Install ffmpeg, e.g.:\n"
        "  Debian/Ubuntu: sudo apt install ffmpeg\n"
        "  Fedora:        sudo dnf install ffmpeg\n"
        "  Arch:          sudo pacman -S ffmpeg\n"
        "or pass --ffmpeg-location <path-to-bin>."
    )


@dataclass
class PreflightResult:
    """Outcome of a successful preflight check."""

    ffmpeg_path: str
    ffprobe_path: str
    ytdlp_version: str
    output_dir: Path


def _find_binary(name: str, ffmpeg_location: str | None) -> str | None:
    """Locate a binary, honouring an explicit ffmpeg location first.

    ``ffmpeg_location`` may be a directory containing the binaries or the path
    to the ffmpeg binary itself; both forms are accepted (matching yt-dlp).
    """
    if ffmpeg_location:
        loc = Path(ffmpeg_location)
        candidates: list[Path] = []
        if loc.is_dir():
            candidates.append(loc / name)
            candidates.append(loc / f"{name}.exe")
        else:
            # Treat as a path to a binary; look for siblings by name too.
            candidates.append(loc)
            candidates.append(loc.parent / name)
            candidates.append(loc.parent / f"{name}.exe")
        for cand in candidates:
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand)
        # Fall through to PATH if not found under the explicit location.
    return shutil.which(name)


def check_ffmpeg(ffmpeg_location: str | None = None) -> tuple[str, str]:
    """Ensure ffmpeg and ffprobe are available; return their resolved paths."""
    ffmpeg = _find_binary("ffmpeg", ffmpeg_location)
    ffprobe = _find_binary("ffprobe", ffmpeg_location)

    missing = [
        name
        for name, found in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe))
        if not found
    ]
    if missing:
        where = (
            f" under --ffmpeg-location '{ffmpeg_location}' or on PATH"
            if ffmpeg_location
            else " on PATH"
        )
        raise PreflightError(
            f"Required dependency not found: {', '.join(missing)}{where}.\n"
            + _ffmpeg_install_hint()
        )

    assert ffmpeg is not None and ffprobe is not None  # for type-checkers
    logger.debug("ffmpeg: %s", ffmpeg)
    logger.debug("ffprobe: %s", ffprobe)
    return ffmpeg, ffprobe


def check_ytdlp() -> str:
    """Ensure yt-dlp imports; return and log its version."""
    try:
        import yt_dlp  # noqa: PLC0415  (deferred import keeps preflight cheap)
    except ImportError as exc:  # pragma: no cover - dependency always installed
        raise PreflightError(
            "yt-dlp is not installed. Install it with:\n"
            "  pip install yt-dlp\n"
            "(or reinstall this tool: pip install -e .)"
        ) from exc

    version = getattr(yt_dlp.version, "__version__", "unknown")
    logger.info("yt-dlp version: %s", version)
    return version


def check_output_dir(output_dir: str | Path) -> Path:
    """Ensure the output directory exists and is writable; return its path."""
    path = Path(output_dir)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PreflightError(
            f"Cannot create output directory '{path}': {exc}.\n"
            "Choose a writable location with -o/--output-dir."
        ) from exc

    # Probe writability with a temp file rather than trusting permissions bits.
    try:
        with tempfile.NamedTemporaryFile(dir=path, prefix=".ytmp3dl-write-test-"):
            pass
    except OSError as exc:
        raise PreflightError(
            f"Output directory '{path}' is not writable: {exc}.\n"
            "Choose a writable location with -o/--output-dir."
        ) from exc

    return path


def run_preflight(
    *,
    output_dir: str | Path,
    ffmpeg_location: str | None = None,
) -> PreflightResult:
    """Run all preflight checks; raise :class:`PreflightError` on the first failure."""
    ffmpeg, ffprobe = check_ffmpeg(ffmpeg_location)
    version = check_ytdlp()
    resolved_dir = check_output_dir(output_dir)
    logger.debug("Preflight passed (output dir: %s)", resolved_dir)
    return PreflightResult(
        ffmpeg_path=ffmpeg,
        ffprobe_path=ffprobe,
        ytdlp_version=version,
        output_dir=resolved_dir,
    )


__all__ = [
    "PreflightResult",
    "check_ffmpeg",
    "check_output_dir",
    "check_ytdlp",
    "run_preflight",
]