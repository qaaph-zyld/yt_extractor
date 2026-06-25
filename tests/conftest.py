"""Shared pytest fixtures and test doubles for the ytmp3dl suite.

Everything here is mock-based: no network, no ffmpeg. The fakes mirror just
enough of the ``yt_dlp.YoutubeDL`` surface that our code touches.
"""

from __future__ import annotations

from typing import Any

import pytest

from ytmp3dl.channel import VideoEntry
from ytmp3dl.config import Config


@pytest.fixture
def base_config(tmp_path) -> Config:
    """A Config pointed at a temp output dir, with tiny sleeps for speed."""
    return Config(
        url="https://www.youtube.com/@Test",
        output_dir=str(tmp_path / "downloads"),
        sleep_min=0.0,
        sleep_max=0.0,
        retries=2,
    )


@pytest.fixture
def sample_videos() -> list[VideoEntry]:
    return [
        VideoEntry(id="aaa", url="https://youtu.be/aaa", title="First", upload_date="20240101"),
        VideoEntry(id="bbb", url="https://youtu.be/bbb", title="Second", upload_date="20240202"),
        VideoEntry(id="ccc", url="https://youtu.be/ccc", title="Third", upload_date="20240303"),
    ]


class FakeYDL:
    """A fake ``YoutubeDL`` that records the opts it was built with.

    Used as a context manager exactly like the real thing. ``extract_info`` can
    be programmed via the class-level ``info_for`` callable.
    """

    last_opts: dict[str, Any] | None = None
    info_for: Any = None  # callable(url, download) -> info dict | None

    def __init__(self, opts: dict[str, Any]):
        type(self).last_opts = opts
        self.opts = opts

    def __enter__(self) -> FakeYDL:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def extract_info(self, url: str, download: bool = False) -> Any:
        if type(self).info_for is not None:
            return type(self).info_for(url, download)
        return {"id": "x", "title": "x"}


@pytest.fixture
def fake_ydl_cls():
    """Return the FakeYDL class with a clean recording slot per test."""
    FakeYDL.last_opts = None
    FakeYDL.info_for = None
    return FakeYDL
