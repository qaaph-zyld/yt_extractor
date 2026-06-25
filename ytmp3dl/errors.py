"""Typed exceptions for ytmp3dl.

The error taxonomy is central to the tool's dependability story:

* :class:`PreflightError` -- an environment problem detected before any
  download work begins (missing ffmpeg, unwritable output dir, ...). These
  abort the whole run with an actionable message.
* :class:`TransientDownloadError` -- a per-video failure that is plausibly
  temporary (network blip, HTTP 5xx, throttling). The runner retries these
  with exponential backoff.
* :class:`PermanentDownloadError` -- a per-video failure that will not improve
  on retry (private/removed/geo-blocked video). The runner records and skips
  these without retrying.
"""

from __future__ import annotations


class Ytmp3dlError(Exception):
    """Base class for all ytmp3dl errors."""


class PreflightError(Ytmp3dlError):
    """Raised when the runtime environment is not ready (fail fast).

    The message is expected to be user-facing and actionable (e.g. it should
    contain a per-OS install hint when a system dependency is missing).
    """


class DownloadFailure(Ytmp3dlError):
    """Base class for per-video download failures."""


class TransientDownloadError(DownloadFailure):
    """A download failure that is plausibly temporary and worth retrying."""


class PermanentDownloadError(DownloadFailure):
    """A download failure that will not improve on retry; record and skip."""


__all__ = [
    "DownloadFailure",
    "PermanentDownloadError",
    "PreflightError",
    "TransientDownloadError",
    "Ytmp3dlError",
]