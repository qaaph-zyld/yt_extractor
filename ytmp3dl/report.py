"""Run reporting: manifest, failures file, and console summary.

The manifest (``manifest.json``) is the durable record of a run: a mapping of
video id -> status/file/title/date/duration/error. It is written incrementally
by the runner so an interrupted run still leaves a partial, valid record. The
console summary and exit-code logic live here too.
"""

from __future__ import annotations

import contextlib
import json
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from ytmp3dl.logging_setup import get_logger

logger = get_logger()

DEFAULT_MANIFEST_NAME = "manifest.json"
DEFAULT_FAILURES_NAME = "failures.json"


class Status(StrEnum):
    """Per-video outcome."""

    DOWNLOADED = "downloaded"
    SKIPPED = "skipped"  # already in archive / nothing to do
    FAILED = "failed"


@dataclass
class VideoResult:
    """The recorded outcome for a single video."""

    id: str
    status: Status
    title: str | None = None
    file: str | None = None
    upload_date: str | None = None
    duration: float | None = None
    error: str | None = None
    attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class RunReport:
    """Accumulates results across a batch and renders outputs."""

    output_dir: Path
    manifest_path: Path
    failures_path: Path
    results: dict[str, VideoResult] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)

    @classmethod
    def create(cls, output_dir: str | Path) -> RunReport:
        out = Path(output_dir)
        return cls(
            output_dir=out,
            manifest_path=out / DEFAULT_MANIFEST_NAME,
            failures_path=out / DEFAULT_FAILURES_NAME,
        )

    # --- mutation -----------------------------------------------------------

    def record(self, result: VideoResult) -> None:
        """Record (or overwrite) the outcome for a video."""
        self.results[result.id] = result

    def write_manifest(self) -> None:
        """Persist the manifest to disk (atomic via temp-file rename)."""
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "videos": {vid: r.to_dict() for vid, r in self.results.items()},
            "summary": self.counts(),
        }
        _atomic_write_json(self.manifest_path, payload)

    def write_failures(self) -> None:
        """Persist the list of failed videos (only if there are any)."""
        failures = [
            r.to_dict() for r in self.results.values() if r.status is Status.FAILED
        ]
        if failures:
            _atomic_write_json(self.failures_path, failures)
        elif self.failures_path.exists():
            # Clear a stale failures file from a previous, worse run.
            with contextlib.suppress(OSError):  # pragma: no cover - best effort
                self.failures_path.unlink()

    # --- queries ------------------------------------------------------------

    def counts(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Status}
        for r in self.results.values():
            counts[r.status.value] += 1
        return counts

    @property
    def downloaded(self) -> int:
        return self.counts()[Status.DOWNLOADED.value]

    @property
    def skipped(self) -> int:
        return self.counts()[Status.SKIPPED.value]

    @property
    def failed(self) -> int:
        return self.counts()[Status.FAILED.value]

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def has_hard_failures(self) -> bool:
        """True if any video ultimately failed (drives the process exit code)."""
        return self.failed > 0

    def exit_code(self) -> int:
        """Process exit code: non-zero when hard failures occurred."""
        return 1 if self.has_hard_failures() else 0

    # --- rendering ----------------------------------------------------------

    def summary_line(self) -> str:
        c = self.counts()
        return (
            f"Done in {self.elapsed():.1f}s -- "
            f"downloaded: {c[Status.DOWNLOADED.value]}, "
            f"skipped: {c[Status.SKIPPED.value]}, "
            f"failed: {c[Status.FAILED.value]}"
        )

    def print_summary(self) -> None:
        """Log the human-facing summary; list failures at WARNING level."""
        logger.info(self.summary_line())
        if self.failed:
            logger.warning("Failed videos:")
            for r in self.results.values():
                if r.status is Status.FAILED:
                    logger.warning("  %s -- %s", r.id, r.error or "unknown error")
            logger.warning("See %s for details.", self.failures_path)


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Write JSON to ``path`` atomically (write temp, then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    tmp.replace(path)


__all__ = [
    "DEFAULT_FAILURES_NAME",
    "DEFAULT_MANIFEST_NAME",
    "RunReport",
    "Status",
    "VideoResult",
]
