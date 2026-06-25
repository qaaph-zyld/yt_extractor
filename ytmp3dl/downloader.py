"""Assemble yt-dlp options and download a single video as audio.

The option assembly is deliberately pure and side-effect-free
(:func:`build_ydl_opts`) so it can be asserted in tests without touching the
network or ffmpeg. :func:`download_one` performs the actual work for one video.

Postprocessor order matters and is fixed:

1. ``FFmpegExtractAudio`` -- transcode to the target codec/quality.
2. ``FFmpegMetadata``     -- write tags (title, artist, ...).
3. ``EmbedThumbnail``     -- embed the cover art (needs the audio file to exist).

These three keys were verified against the installed yt-dlp (2026.06.09).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ytmp3dl.errors import PermanentDownloadError, TransientDownloadError
from ytmp3dl.logging_setup import YtdlpLoggerAdapter, get_logger

if TYPE_CHECKING:
    from ytmp3dl.channel import VideoEntry
    from ytmp3dl.config import Config

logger = get_logger()

# Codecs we let the user pick. "best" means "don't re-encode, keep source".
_AUDIO_CODECS = {"mp3", "m4a", "opus", "flac", "wav", "best"}


def _parse_quality(audio_quality: str) -> str:
    """Translate a human quality string into yt-dlp's ``preferredquality``.

    yt-dlp expects either a VBR quality index (0-10) or a bitrate in kbps as a
    bare number. We accept values like ``"320K"``, ``"320k"``, ``"320"`` and
    normalise to ``"320"``; a value of ``"0".."10"`` is passed through as a VBR
    index. Falls back to ``"320"`` if unparseable.
    """
    if audio_quality is None:
        return "320"
    q = audio_quality.strip().lower().rstrip("k")
    if re.fullmatch(r"\d+", q):
        return q
    return "320"


def build_ydl_opts(
    config: Config,
    *,
    archive_path: str | None = None,
    progress_hook: Any | None = None,
    logger_adapter: Any | None = None,
) -> dict[str, Any]:
    """Build the yt-dlp options dict for downloading audio.

    Pure function: returns a dict, performs no I/O. ``archive_path`` overrides
    the value derived from ``config`` (the runner resolves it once and passes it
    in). ``progress_hook`` / ``logger_adapter`` are injection seams.
    """
    if config.audio_format not in _AUDIO_CODECS:
        raise ValueError(
            f"Unsupported audio format {config.audio_format!r}; "
            f"choose one of {sorted(_AUDIO_CODECS)}"
        )

    outtmpl = str(Path(config.output_dir) / config.output_template)

    opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "writethumbnail": True,
        "ignoreerrors": False,  # the runner does fault isolation, not yt-dlp
        "noprogress": True,  # progress goes through our hook/logger
        "quiet": True,
        "no_warnings": False,
        "logger": logger_adapter or YtdlpLoggerAdapter(),
        # --- resilience / politeness ---
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 3,
        "sleep_interval": config.sleep_min,
        "max_sleep_interval": config.sleep_max,
        "sleep_requests": config.sleep_requests,
    }

    # --- postprocessors (order is significant) ---
    postprocessors: list[dict[str, Any]] = []
    if config.audio_format == "best":
        # No transcode: keep the best audio as-is, just (optionally) tag/embed.
        pass
    else:
        postprocessors.append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": config.audio_format,
                "preferredquality": _parse_quality(config.audio_quality),
            }
        )
    if config.embed_metadata:
        postprocessors.append({"key": "FFmpegMetadata"})
    if config.embed_thumbnail:
        postprocessors.append({"key": "EmbedThumbnail"})
    opts["postprocessors"] = postprocessors

    # --- archive / idempotency ---
    if archive_path:
        opts["download_archive"] = archive_path

    # --- keep source file when transcoding ---
    if config.keep_original:
        opts["keepvideo"] = True

    # --- rate limiting ---
    if config.rate_limit:
        parsed_rate = _parse_rate(config.rate_limit)
        if parsed_rate is not None:
            opts["ratelimit"] = parsed_rate

    # --- auth ---
    if config.cookies:
        opts["cookiefile"] = config.cookies
    if config.cookies_from_browser:
        opts["cookiesfrombrowser"] = (config.cookies_from_browser,)

    # --- ffmpeg location ---
    if config.ffmpeg_location:
        opts["ffmpeg_location"] = config.ffmpeg_location

    # --- progress hook ---
    if progress_hook is not None:
        opts["progress_hooks"] = [progress_hook]

    return opts


def _parse_rate(rate: str) -> int | None:
    """Parse a human rate-limit string (e.g. ``"1.5M"``, ``"500K"``) to bytes/s."""
    rate = rate.strip()
    match = re.fullmatch(r"(?i)\s*([\d.]+)\s*([KMG]?)\s*", rate)
    if not match:
        logger.warning("Ignoring unparseable --rate-limit value: %r", rate)
        return None
    value = float(match.group(1))
    suffix = match.group(2).upper()
    multiplier = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}[suffix]
    return int(value * multiplier)


def make_progress_hook() -> Any:
    """Return a progress hook that routes yt-dlp progress through our logger."""

    def hook(d: dict[str, Any]) -> None:
        status = d.get("status")
        if status == "finished":
            logger.debug("Download finished: %s", d.get("filename"))
        elif status == "error":
            logger.debug("Download error event: %s", d.get("filename"))

    return hook


# --- error classification --------------------------------------------------

# Substrings that strongly indicate a *permanent* (non-retryable) condition.
_PERMANENT_MARKERS = (
    "private video",
    "video unavailable",
    "this video is unavailable",
    "removed by the uploader",
    "account associated with this video has been terminated",
    "video has been removed",
    "who has blocked it in your country",
    "not available in your country",
    "members-only",
    "join this channel",
    "sign in to confirm your age",
    "age-restricted",
    "is not available",
    "has been deleted",
    "copyright",
)

# Substrings that strongly indicate a *transient* (retryable) condition.
_TRANSIENT_MARKERS = (
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "connection refused",
    "temporary failure",
    "temporarily unavailable",
    "http error 5",  # 5xx
    "http error 429",
    "too many requests",
    "throttl",
    "unable to download",
    "read operation",
    "remote end closed",
    "name or service not known",
    "network is unreachable",
    "ssl",
    "broken pipe",
)


def classify_error(exc: Exception) -> Exception:
    """Classify a raw yt-dlp exception into a transient/permanent error.

    Returns a :class:`TransientDownloadError` or :class:`PermanentDownloadError`
    wrapping the original (preserving ``__cause__``). Unknown errors are treated
    as *transient* so a retry gets a chance -- the runner caps retries, so this
    is safe and biases toward dependability over giving up early.
    """
    msg = str(exc).lower()

    for marker in _PERMANENT_MARKERS:
        if marker in msg:
            return PermanentDownloadError(str(exc))

    for marker in _TRANSIENT_MARKERS:
        if marker in msg:
            return TransientDownloadError(str(exc))

    # Default: treat as transient (give the retry budget a chance).
    return TransientDownloadError(str(exc))


def download_one(
    video: VideoEntry,
    config: Config,
    *,
    archive_path: str | None = None,
    ydl_factory: Any | None = None,
) -> dict[str, Any] | None:
    """Download a single video as audio.

    Returns the yt-dlp info dict for the download (or ``None`` if yt-dlp skipped
    it via the archive). Raises a classified :class:`TransientDownloadError` /
    :class:`PermanentDownloadError` on failure -- the runner handles retry and
    fault isolation.
    """
    if ydl_factory is None:
        import yt_dlp  # noqa: PLC0415

        ydl_factory = yt_dlp.YoutubeDL

    opts = build_ydl_opts(
        config,
        archive_path=archive_path,
        progress_hook=make_progress_hook(),
    )

    try:
        with ydl_factory(opts) as ydl:
            return ydl.extract_info(video.url, download=True)
    except Exception as exc:
        raise classify_error(exc) from exc


__all__ = [
    "build_ydl_opts",
    "classify_error",
    "download_one",
    "make_progress_hook",
]
