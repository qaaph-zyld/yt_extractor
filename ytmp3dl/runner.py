"""Batch download loop: fault isolation, retries, and reporting.

This is where the tool earns the word "dependable":

* **Fault isolation** -- every video is downloaded inside its own try/except, so
  one bad video can never abort the batch. Failures are recorded and the loop
  moves on.
* **Retry with backoff** -- :class:`~ytmp3dl.errors.TransientDownloadError` is
  retried with exponential backoff (default 2 retries). The sleep function is
  injectable so tests run instantly. Permanent errors are not retried.
* **Incremental manifest** -- the manifest is rewritten after each video so an
  interrupted run still leaves a valid, partial record on disk.
* **Optional concurrency** -- sequential by default (polite); a
  :class:`ThreadPoolExecutor` is used only when ``--concurrency > 1``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ytmp3dl.downloader import download_one
from ytmp3dl.errors import PermanentDownloadError, TransientDownloadError
from ytmp3dl.logging_setup import get_logger
from ytmp3dl.report import RunReport, Status, VideoResult

if TYPE_CHECKING:
    from ytmp3dl.channel import VideoEntry
    from ytmp3dl.config import Config

logger = get_logger()

# Base delay (seconds) for exponential backoff; attempt N waits base * 2**(N-1).
DEFAULT_BACKOFF_BASE = 2.0


def load_archived_ids(archive_path: str | None) -> set[str]:
    """Read the yt-dlp download archive and return the set of recorded video ids.

    The archive format is one record per line: ``<extractor> <id>`` (e.g.
    ``youtube dQw4w9WgXcQ``). We take the *last* whitespace-separated token on
    each non-empty, non-comment line as the id, which is robust to the extractor
    prefix and tolerant of stray whitespace. A missing or unreadable file (or a
    disabled archive, ``None``) yields an empty set -- the run then treats every
    video as new, matching the ``--no-archive`` semantics.
    """
    if not archive_path:
        return set()
    path = Path(archive_path)
    if not path.is_file():
        logger.debug("No download archive at %s (nothing pre-skipped)", path)
        return set()

    ids: set[str] = set()
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            ids.add(line.split()[-1])
    except OSError as exc:
        logger.debug("Could not read download archive %s: %s", path, exc)
        return set()

    logger.debug("Loaded %d archived id(s) from %s", len(ids), path)
    return ids


class Downloader(Protocol):
    """The call shape the runner needs from a downloader.

    Matches :func:`ytmp3dl.downloader.download_one`. Tests inject a fake.
    """

    def __call__(
        self,
        video: VideoEntry,
        config: Config,
        *,
        archive_path: str | None = ...,
    ) -> dict[str, Any] | None: ...


def _result_from_info(
    video: VideoEntry, info: dict[str, Any] | None, attempts: int
) -> VideoResult:
    """Build a successful :class:`VideoResult` from a yt-dlp info dict."""
    filename: str | None = None
    title = video.title
    upload_date = video.upload_date
    duration = video.duration

    if info:
        title = info.get("title", title)
        upload_date = info.get("upload_date", upload_date)
        duration = info.get("duration", duration)
        # Prefer the final post-processed filepath when yt-dlp exposes it.
        reqs = info.get("requested_downloads")
        if reqs:
            filename = reqs[0].get("filepath") or reqs[0].get("filename")
        filename = filename or info.get("filepath")

    return VideoResult(
        id=video.id,
        status=Status.DOWNLOADED,
        title=title,
        file=filename,
        upload_date=upload_date,
        duration=duration,
        attempts=attempts,
    )


def download_with_retries(
    video: VideoEntry,
    config: Config,
    *,
    archive_path: str | None,
    downloader: Downloader,
    sleep: Callable[[float], None] = time.sleep,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
) -> VideoResult:
    """Download one video, retrying transient failures with backoff.

    Always returns a :class:`VideoResult` -- it never raises -- so the batch loop
    stays simple and fully fault-isolated. ``sleep`` and ``backoff_base`` are
    injectable so tests assert backoff behaviour without real waits.
    """
    max_attempts = max(1, config.retries + 1)  # retries are *additional* tries
    last_error: str | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            info = downloader(video, config, archive_path=archive_path)
            logger.info("Downloaded %s (%s)", video.id, video.title or "?")
            return _result_from_info(video, info, attempt)
        except PermanentDownloadError as exc:
            logger.warning("Permanent failure for %s: %s", video.id, exc)
            return VideoResult(
                id=video.id,
                status=Status.FAILED,
                title=video.title,
                upload_date=video.upload_date,
                duration=video.duration,
                error=f"permanent: {exc}",
                attempts=attempt,
            )
        except TransientDownloadError as exc:
            last_error = str(exc)
            if attempt >= max_attempts:
                logger.warning(
                    "Transient failure for %s after %d attempt(s): %s",
                    video.id,
                    attempt,
                    exc,
                )
                break
            delay = backoff_base * (2 ** (attempt - 1))
            logger.warning(
                "Transient failure for %s (attempt %d/%d): %s; retrying in %.1fs",
                video.id,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            sleep(delay)
        except Exception as exc:  # noqa: BLE001 - last-resort isolation
            # Should not happen (download_one classifies), but never let an
            # unexpected error escape and abort the batch. This is distinct from
            # retry exhaustion, so it gets its own message.
            logger.error("Unexpected error for %s: %s", video.id, exc)
            return VideoResult(
                id=video.id,
                status=Status.FAILED,
                title=video.title,
                upload_date=video.upload_date,
                duration=video.duration,
                error=f"unexpected: {exc}",
                attempts=attempt,
            )

    return VideoResult(
        id=video.id,
        status=Status.FAILED,
        title=video.title,
        upload_date=video.upload_date,
        duration=video.duration,
        error=f"transient (exhausted retries): {last_error}",
        attempts=max_attempts,
    )


def run_batch(
    videos: list[VideoEntry],
    config: Config,
    *,
    report: RunReport | None = None,
    downloader: Downloader = download_one,
    sleep: Callable[[float], None] = time.sleep,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
) -> RunReport:
    """Download every video, isolating faults and accumulating a report.

    Sequential by default; uses a thread pool when ``config.concurrency > 1``.
    The manifest is rewritten after each completed video so progress survives an
    interruption.
    """
    if report is None:
        report = RunReport.create(config.output_dir)
    archive_path = config.archive_path()

    if not videos:
        logger.info("No videos to download.")
        report.write_manifest()
        return report

    # Partition out videos already in the download archive: record them as
    # SKIPPED up front (no downloader call, no retry) so re-runs report
    # `skipped: N` accurately and the thread pool only ever sees real work.
    # `download_archive` is also passed to yt-dlp (defense in depth) so even an
    # id we miss here is still not re-downloaded.
    archived_ids = load_archived_ids(archive_path)
    pending: list[VideoEntry] = []
    for video in videos:
        if video.id in archived_ids:
            logger.info("Skipping %s (already in archive)", video.id)
            report.record(
                VideoResult(
                    id=video.id,
                    status=Status.SKIPPED,
                    title=video.title,
                    upload_date=video.upload_date,
                    duration=video.duration,
                )
            )
        else:
            pending.append(video)
    if archived_ids:
        report.write_manifest()  # persist skips before downloading begins

    def _one(video: VideoEntry) -> VideoResult:
        return download_with_retries(
            video,
            config,
            archive_path=archive_path,
            downloader=downloader,
            sleep=sleep,
            backoff_base=backoff_base,
        )

    if not pending:
        logger.info("Nothing new to download (%d skipped).", report.skipped)
    elif config.concurrency and config.concurrency > 1:
        logger.info(
            "Downloading %d video(s) with concurrency=%d",
            len(pending),
            config.concurrency,
        )
        with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
            futures = {pool.submit(_one, v): v for v in pending}
            for future in as_completed(futures):
                video = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001 - never abort the batch
                    logger.error("Worker crashed for %s: %s", video.id, exc)
                    result = VideoResult(
                        id=video.id,
                        status=Status.FAILED,
                        title=video.title,
                        error=f"worker crash: {exc}",
                    )
                report.record(result)
                report.write_manifest()
    else:
        logger.info("Downloading %d video(s) sequentially", len(pending))
        for video in pending:
            result = _one(video)
            report.record(result)
            report.write_manifest()  # incremental: survive interruption

    report.write_manifest()
    report.write_failures()
    return report


__all__ = [
    "DEFAULT_BACKOFF_BASE",
    "Downloader",
    "download_with_retries",
    "load_archived_ids",
    "run_batch",
]
