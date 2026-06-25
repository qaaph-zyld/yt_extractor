"""Command-line interface for ytmp3dl.

Responsibilities:

* Parse arguments (argparse).
* Merge configuration with the documented precedence
  (defaults -> TOML -> CLI overrides).
* Configure logging.
* Dispatch: ``--list`` / ``--dry-run`` enumerate and print; otherwise run the
  full preflight -> enumerate -> download -> report pipeline.

Exit codes: ``0`` success, ``1`` hard download failures, ``2`` preflight or
usage/config errors.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from ytmp3dl import __version__
from ytmp3dl.config import Config, build_config, load_toml
from ytmp3dl.errors import PreflightError
from ytmp3dl.logging_setup import get_logger, setup_logging

logger = get_logger()

EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_PREFLIGHT = 2


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        prog="ytmp3dl",
        description=(
            "Dependably download MP3 audio for every video on a YouTube "
            "channel. Re-runs skip already-downloaded videos."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  ytmp3dl https://www.youtube.com/@PapaPedroBeats --limit 1\n"
        ),
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Channel URL or @handle (e.g. https://www.youtube.com/@Name or @Name).",
    )

    # --- output / audio ---
    out = parser.add_argument_group("output & audio")
    out.add_argument("-o", "--output-dir", dest="output_dir", help="Output directory (default: ./downloads).")
    out.add_argument("--output-template", dest="output_template", help="yt-dlp output template (advanced).")
    out.add_argument(
        "--audio-format",
        dest="audio_format",
        choices=["mp3", "m4a", "opus", "flac", "wav", "best"],
        help="Audio format (default: mp3).",
    )
    out.add_argument("--audio-quality", dest="audio_quality", help="Audio quality, e.g. 320K (default: 320K).")
    out.add_argument(
        "--keep-original",
        dest="keep_original",
        action="store_true",
        default=None,
        help="Keep the original source file alongside the transcoded audio.",
    )

    # --- content scope ---
    scope = parser.add_argument_group("content scope")
    scope.add_argument(
        "--include-shorts",
        dest="include_shorts",
        action="store_true",
        default=None,
        help="Also download the channel's Shorts.",
    )
    scope.add_argument(
        "--include-streams",
        dest="include_streams",
        action="store_true",
        default=None,
        help="Also download the channel's past live streams.",
    )
    scope.add_argument(
        "--videos-only",
        dest="videos_only",
        action="store_true",
        default=None,
        help="Only the /videos tab (default; explicitly disables shorts/streams).",
    )

    # --- filters ---
    filt = parser.add_argument_group("filters")
    filt.add_argument("--limit", dest="limit", type=int, help="Download at most N videos.")
    filt.add_argument("--dateafter", dest="dateafter", help="Only videos uploaded on/after this date (YYYYMMDD).")
    filt.add_argument("--datebefore", dest="datebefore", help="Only videos uploaded on/before this date (YYYYMMDD).")
    filt.add_argument("--playlist-items", dest="playlist_items", help="yt-dlp playlist-items selection, e.g. '1-10,15'.")

    # --- archive ---
    arch = parser.add_argument_group("archive / idempotency")
    arch.add_argument("--archive", dest="archive", help="Path to the download-archive file.")
    arch.add_argument(
        "--no-archive",
        dest="use_archive",
        action="store_false",
        default=None,
        help="Disable the download archive (re-download everything).",
    )

    # --- embedding ---
    embed = parser.add_argument_group("embedding")
    embed.add_argument(
        "--no-embed-metadata",
        dest="embed_metadata",
        action="store_false",
        default=None,
        help="Do not embed metadata tags.",
    )
    embed.add_argument(
        "--no-embed-thumbnail",
        dest="embed_thumbnail",
        action="store_false",
        default=None,
        help="Do not embed the cover-art thumbnail.",
    )

    # --- politeness / resilience ---
    pol = parser.add_argument_group("politeness & resilience")
    pol.add_argument("--concurrency", dest="concurrency", type=int, help="Parallel downloads (default: 1).")
    pol.add_argument("--sleep-min", dest="sleep_min", type=float, help="Minimum sleep between downloads (s).")
    pol.add_argument("--sleep-max", dest="sleep_max", type=float, help="Maximum sleep between downloads (s).")
    pol.add_argument("--rate-limit", dest="rate_limit", help="Max download rate, e.g. 1M or 500K.")
    pol.add_argument("--retries", dest="retries", type=int, help="Outer per-video retries on transient errors (default: 2).")

    # --- auth ---
    auth = parser.add_argument_group("authentication")
    auth.add_argument("--cookies-from-browser", dest="cookies_from_browser", help="Load cookies from a browser, e.g. firefox.")
    auth.add_argument("--cookies", dest="cookies", help="Path to a Netscape-format cookies file.")

    # --- misc ---
    misc = parser.add_argument_group("misc")
    misc.add_argument("--config", dest="config", help="Path to a TOML config file.")
    misc.add_argument("--ffmpeg-location", dest="ffmpeg_location", help="Path to the ffmpeg/ffprobe binaries or their folder.")
    misc.add_argument("--dry-run", dest="dry_run", action="store_true", default=None, help="Enumerate and print the plan; download nothing.")
    misc.add_argument("--list", dest="list_only", action="store_true", default=None, help="Print enumerated videos and exit.")
    misc.add_argument("--log-file", dest="log_file", help="Write a rotating debug log to this file.")
    misc.add_argument("--verbose", dest="verbose", action="store_true", default=None, help="Verbose (DEBUG) console output.")
    misc.add_argument("--quiet", dest="quiet", action="store_true", default=None, help="Quiet (warnings and errors only).")
    misc.add_argument("--version", action="version", version=f"ytmp3dl {__version__}")

    return parser


# Argparse dests that are not Config fields (handled specially / dropped).
_NON_CONFIG_DESTS = {"config", "videos_only"}


def _cli_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Extract only the options the user actually set (non-``None``).

    Unset flags are ``None`` (we set ``default=None`` on store_true/store_false
    too) so they don't clobber TOML/default values during the merge.
    """
    overrides: dict[str, Any] = {}
    for key, value in vars(args).items():
        if key in _NON_CONFIG_DESTS:
            continue
        if value is None:
            continue
        overrides[key] = value

    # --videos-only is an explicit "no shorts/streams" intent.
    if getattr(args, "videos_only", None):
        overrides["include_shorts"] = False
        overrides["include_streams"] = False

    return overrides


def resolve_config(args: argparse.Namespace) -> Config:
    """Merge defaults, optional TOML, and CLI overrides into a :class:`Config`."""
    toml_values: dict[str, Any] = {}
    if getattr(args, "config", None):
        toml_values = load_toml(args.config)
    return build_config(toml_values=toml_values, cli_overrides=_cli_overrides(args))


def _print_plan(videos: list[Any], config: Config, *, dry_run: bool) -> None:
    """Print the enumerated videos (for ``--list`` / ``--dry-run``)."""
    header = "DRY RUN -- the following videos would be downloaded:" if dry_run else "Enumerated videos:"
    print(header)
    for i, v in enumerate(videos, 1):
        date = v.upload_date or "????????"
        title = v.title or "(title unavailable)"
        print(f"  {i:>4}. [{v.id}] {date}  {title}")
    print(f"Total: {len(videos)} video(s).")
    if dry_run:
        archive = config.archive_path()
        print(f"Output dir : {config.output_dir}")
        print(f"Audio      : {config.audio_format} @ {config.audio_quality}")
        print(f"Archive    : {archive if archive else '(disabled)'}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.url:
        parser.error("a channel URL or @handle is required")

    try:
        config = resolve_config(args)
    except (OSError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_PREFLIGHT

    setup_logging(
        verbose=bool(config.verbose),
        quiet=bool(config.quiet),
        log_file=config.log_file,
    )

    # Deferred imports keep --help/--version fast and import-light.
    from ytmp3dl.channel import enumerate_videos  # noqa: PLC0415
    from ytmp3dl.preflight import run_preflight  # noqa: PLC0415
    from ytmp3dl.runner import run_batch  # noqa: PLC0415

    list_or_dry = bool(config.list_only or config.dry_run)

    # For list/dry-run we skip the ffmpeg requirement (no transcoding happens),
    # but still verify yt-dlp and (for dry-run) the output dir.
    if not list_or_dry:
        try:
            run_preflight(
                output_dir=config.output_dir,
                ffmpeg_location=config.ffmpeg_location,
            )
        except PreflightError as exc:
            logger.error("Preflight failed:\n%s", exc)
            return EXIT_PREFLIGHT

    try:
        videos = enumerate_videos(args.url, config)
    except ValueError as exc:
        logger.error("Could not interpret channel reference: %s", exc)
        return EXIT_PREFLIGHT

    if list_or_dry:
        _print_plan(videos, config, dry_run=bool(config.dry_run))
        return EXIT_OK

    report = run_batch(videos, config)
    report.print_summary()
    return report.exit_code()


__all__ = ["EXIT_FAILURES", "EXIT_OK", "EXIT_PREFLIGHT", "build_parser", "main", "resolve_config"]
