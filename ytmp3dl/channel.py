"""Channel URL normalization and flat video enumeration.

Accepts the many shapes a user might paste -- ``@handle``, ``/channel/<id>``,
``/c/<name>``, ``/user/<name>``, a bare handle, or a full URL with or without a
tab -- and normalizes them into the canonical channel *tab* URLs that yt-dlp
enumerates cleanly (``/videos``, plus ``/shorts`` and ``/streams`` when the user
opts in).

Enumeration uses ``extract_flat='in_playlist'`` so we list video metadata
without downloading, then applies cheap client-side filters (limit, date range,
playlist-items selection).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from ytmp3dl.logging_setup import YtdlpLoggerAdapter, get_logger

if TYPE_CHECKING:
    from ytmp3dl.config import Config

logger = get_logger()

_YT_HOST_SUFFIXES = ("youtube.com", "youtu.be")

# Tab path segments yt-dlp understands on a channel page.
_KNOWN_TABS = {"videos", "shorts", "streams", "featured", "playlists", "community"}


@dataclass
class VideoEntry:
    """A single enumerated video (pre-download)."""

    id: str
    url: str
    title: str | None = None
    upload_date: str | None = None  # YYYYMMDD as yt-dlp reports it
    duration: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _is_youtube_host(host: str) -> bool:
    host = host.lower()
    return any(host == suf or host.endswith("." + suf) for suf in _YT_HOST_SUFFIXES)


def _channel_base_from_url(url: str) -> str:
    """Return the channel *base* URL (no tab) from an arbitrary YouTube URL.

    Strips any trailing tab segment so we can append the tabs we actually want.
    """
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]

    # Drop a trailing known-tab segment if present.
    if parts and parts[-1].lower() in _KNOWN_TABS:
        parts = parts[:-1]

    if not parts:
        raise ValueError(f"Could not find a channel path in URL: {url}")

    first = parts[0]
    # @handle, /channel/<id>, /c/<name>, /user/<name>
    if first.startswith("@"):
        base_parts = [first]
    elif first in {"channel", "c", "user"} and len(parts) >= 2:
        base_parts = parts[:2]
    else:
        # A bare path like /SomeName -> treat as a legacy custom URL.
        base_parts = [first]

    return "https://www.youtube.com/" + "/".join(base_parts)


def normalize_channel_base(target: str) -> str:
    """Normalize any accepted channel reference into a base channel URL.

    Examples
    --------
    ``@PapaPedroBeats``                       -> ``https://www.youtube.com/@PapaPedroBeats``
    ``PapaPedroBeats``                        -> ``https://www.youtube.com/@PapaPedroBeats``
    ``https://youtube.com/@Foo/videos``       -> ``https://www.youtube.com/@Foo``
    ``https://www.youtube.com/channel/UC123`` -> ``https://www.youtube.com/channel/UC123``
    ``https://www.youtube.com/c/Name``        -> ``https://www.youtube.com/c/Name``
    ``youtube.com/user/Legacy``               -> ``https://www.youtube.com/user/Legacy``
    """
    target = target.strip()
    if not target:
        raise ValueError("Empty channel reference")

    # Bare @handle.
    if target.startswith("@"):
        if "/" in target or " " in target:
            raise ValueError(f"Malformed handle: {target!r}")
        return f"https://www.youtube.com/{target}"

    # Looks like a URL (has a scheme or a youtube host).
    if "://" in target or _looks_like_host(target):
        url = target if "://" in target else f"https://{target}"
        parsed = urlparse(url)
        if not _is_youtube_host(parsed.netloc):
            raise ValueError(f"Not a YouTube URL: {target}")
        return _channel_base_from_url(url)

    # Bare token with no slashes -> treat as a handle.
    if "/" not in target:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", target):
            raise ValueError(f"Cannot interpret channel reference: {target!r}")
        return f"https://www.youtube.com/@{target}"

    raise ValueError(f"Cannot interpret channel reference: {target!r}")


def _looks_like_host(target: str) -> bool:
    """Heuristic: does this bare string start with a youtube host?"""
    head = target.split("/", 1)[0].lower()
    return _is_youtube_host(head)


def tab_urls(target: str, config: Config) -> list[str]:
    """Return the ordered list of channel tab URLs to enumerate.

    ``/videos`` is always included; ``/shorts`` and ``/streams`` are added when
    the corresponding config flags are set.
    """
    base = normalize_channel_base(target)
    urls = [f"{base}/videos"]
    if config.include_shorts:
        urls.append(f"{base}/shorts")
    if config.include_streams:
        urls.append(f"{base}/streams")
    return urls


def _flat_opts(config: Config) -> dict[str, Any]:
    """Build YoutubeDL opts for flat enumeration (no downloading)."""
    opts: dict[str, Any] = {
        "extract_flat": "in_playlist",
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,  # one bad entry should not abort enumeration
        "logger": YtdlpLoggerAdapter(),
    }
    if config.playlist_items:
        opts["playlist_items"] = config.playlist_items
    if config.dateafter:
        opts["dateafter"] = config.dateafter
    if config.datebefore:
        opts["datebefore"] = config.datebefore
    # Cookies can matter even for enumeration of some channels.
    if config.cookies:
        opts["cookiefile"] = config.cookies
    if config.cookies_from_browser:
        opts["cookiesfrombrowser"] = (config.cookies_from_browser,)
    return opts


def _entries_from_info(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Recursively collect leaf video entries from a (possibly nested) info dict.

    Channel tab pages can come back as a playlist of playlists, so we descend
    into nested ``entries`` until we hit actual videos.
    """
    entries = info.get("entries")
    if not entries:
        return [info] if info.get("id") else []

    collected: list[dict[str, Any]] = []
    for entry in entries:
        if entry is None:
            continue  # ignoreerrors can leave None holes
        if entry.get("entries") is not None:
            collected.extend(_entries_from_info(entry))
        else:
            collected.append(entry)
    return collected


def _to_video_entry(raw: dict[str, Any]) -> VideoEntry | None:
    """Convert a raw flat-extracted entry into a :class:`VideoEntry`."""
    vid = raw.get("id")
    if not vid:
        return None
    url = raw.get("url") or raw.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"
    return VideoEntry(
        id=vid,
        url=url,
        title=raw.get("title"),
        upload_date=raw.get("upload_date"),
        duration=raw.get("duration"),
        extra={
            k: raw[k]
            for k in ("uploader", "channel", "view_count")
            if k in raw
        },
    )


def enumerate_videos(
    target: str,
    config: Config,
    *,
    ydl_factory: Any | None = None,
) -> list[VideoEntry]:
    """Enumerate all videos for ``target`` across the configured tabs.

    ``ydl_factory`` is an injection seam for tests: a callable taking an opts
    dict and returning a context-manager yt-dlp instance. Defaults to
    ``yt_dlp.YoutubeDL``.
    """
    if ydl_factory is None:
        import yt_dlp  # noqa: PLC0415

        ydl_factory = yt_dlp.YoutubeDL

    opts = _flat_opts(config)
    seen: set[str] = set()
    results: list[VideoEntry] = []

    for url in tab_urls(target, config):
        logger.debug("Enumerating tab: %s", url)
        try:
            with ydl_factory(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # noqa: BLE001 - one bad tab must not kill the rest
            logger.warning("Failed to enumerate %s: %s", url, exc)
            continue
        if not info:
            continue
        for raw in _entries_from_info(info):
            entry = _to_video_entry(raw)
            if entry is None or entry.id in seen:
                continue
            seen.add(entry.id)
            results.append(entry)

    filtered = apply_filters(results, config)
    logger.info(
        "Enumerated %d video(s) (%d after filters)", len(results), len(filtered)
    )
    return filtered


def apply_filters(videos: list[VideoEntry], config: Config) -> list[VideoEntry]:
    """Apply client-side filters that are cheap to evaluate post-enumeration.

    Date filtering is primarily delegated to yt-dlp via ``dateafter`` /
    ``datebefore`` during enumeration, but we also enforce it here as a
    belt-and-braces measure for entries that carry an ``upload_date`` (flat
    extraction may omit it, in which case the entry is kept and filtered at
    download time by yt-dlp). ``--limit`` is applied last so it caps the final,
    already-filtered list.
    """
    result = videos

    def _digits(date_str: str) -> str:
        return date_str.replace("-", "")

    if config.dateafter:
        after = _digits(config.dateafter)
        result = [
            v for v in result if v.upload_date is None or v.upload_date >= after
        ]
    if config.datebefore:
        before = _digits(config.datebefore)
        result = [
            v for v in result if v.upload_date is None or v.upload_date <= before
        ]

    if config.limit is not None and config.limit >= 0:
        result = result[: config.limit]

    return result


__all__ = [
    "VideoEntry",
    "apply_filters",
    "enumerate_videos",
    "normalize_channel_base",
    "tab_urls",
]
