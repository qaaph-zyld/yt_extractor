"""Configuration handling for ytmp3dl.

Precedence (lowest to highest):

1. Built-in defaults (the :class:`Config` dataclass field defaults).
2. A TOML config file (read with the stdlib :mod:`tomllib`).
3. CLI overrides (whatever the user actually passed on the command line).

The merge is intentionally explicit so the precedence is easy to reason about
and test: :func:`build_config` layers a dict of TOML values, then a dict of
CLI overrides, on top of the dataclass defaults.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

# Default location of the download archive, relative to the output dir.
DEFAULT_ARCHIVE_NAME = ".ytmp3dl-archive.txt"

# Default output template. ``uploader`` groups by channel; the date prefix keeps
# files chronologically sortable; the ``[id]`` suffix guarantees uniqueness and
# matches what the download archive keys on.
DEFAULT_OUTPUT_TEMPLATE = (
    "%(uploader)s/%(upload_date>%Y-%m-%d)s - %(title)s [%(id)s].%(ext)s"
)


@dataclass
class Config:
    """Resolved, fully-merged configuration for a single run."""

    # --- target / output ---
    url: str | None = None
    output_dir: str = "downloads"
    output_template: str = DEFAULT_OUTPUT_TEMPLATE

    # --- audio ---
    audio_format: str = "mp3"
    audio_quality: str = "320K"
    keep_original: bool = False

    # --- content scope ---
    include_shorts: bool = False
    include_streams: bool = False

    # --- enumeration filters ---
    limit: int | None = None
    dateafter: str | None = None
    datebefore: str | None = None
    playlist_items: str | None = None

    # --- archive / idempotency ---
    use_archive: bool = True
    archive: str | None = None  # explicit path; falls back to output_dir/DEFAULT

    # --- embedding ---
    embed_metadata: bool = True
    embed_thumbnail: bool = True

    # --- politeness / resilience ---
    concurrency: int = 1
    sleep_min: float = 1.0
    sleep_max: float = 5.0
    sleep_requests: float = 1.0
    rate_limit: str | None = None
    retries: int = 2  # outer per-video retries (yt-dlp has its own inner retries)

    # --- auth ---
    cookies_from_browser: str | None = None
    cookies: str | None = None

    # --- ffmpeg ---
    ffmpeg_location: str | None = None

    # --- logging / modes ---
    log_file: str | None = None
    verbose: bool = False
    quiet: bool = False
    dry_run: bool = False
    list_only: bool = False

    def archive_path(self) -> str | None:
        """Return the resolved download-archive path, or ``None`` if disabled."""
        if not self.use_archive:
            return None
        if self.archive:
            return self.archive
        return str(Path(self.output_dir) / DEFAULT_ARCHIVE_NAME)


_VALID_FIELDS = {f.name for f in fields(Config)}


def load_toml(path: str | Path) -> dict[str, Any]:
    """Load a TOML config file into a plain dict.

    Only keys that correspond to :class:`Config` fields are kept; unknown keys
    raise :class:`ValueError` so typos in a config file are caught early rather
    than silently ignored.
    """
    path = Path(path)
    with path.open("rb") as fh:
        data = tomllib.load(fh)

    # Allow an optional [ytmp3dl] table wrapper for cleanliness.
    if "ytmp3dl" in data and isinstance(data["ytmp3dl"], dict):
        data = data["ytmp3dl"]

    unknown = set(data) - _VALID_FIELDS
    if unknown:
        raise ValueError(
            f"Unknown config key(s) in {path}: {', '.join(sorted(unknown))}"
        )
    return data


def build_config(
    *,
    toml_values: dict[str, Any] | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> Config:
    """Build a :class:`Config` by layering TOML then CLI on top of defaults.

    ``cli_overrides`` should contain only keys the user actually set (a value of
    ``None`` for an unset flag must be filtered out by the caller so it does not
    clobber a TOML/default value).
    """
    merged: dict[str, Any] = {}
    if toml_values:
        merged.update({k: v for k, v in toml_values.items() if k in _VALID_FIELDS})
    if cli_overrides:
        merged.update({k: v for k, v in cli_overrides.items() if k in _VALID_FIELDS})
    return Config(**merged)


__all__ = [
    "DEFAULT_ARCHIVE_NAME",
    "DEFAULT_OUTPUT_TEMPLATE",
    "Config",
    "build_config",
    "load_toml",
]
