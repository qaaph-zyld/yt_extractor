"""Live integration test (network-dependent).

Skipped unless the environment variable ``YTMP3DL_LIVE=1`` is set. It performs a
real *flat* enumeration of the example channel -- it does NOT download media, so
it needs network access but not ffmpeg. Run it explicitly with:

    YTMP3DL_LIVE=1 python -m pytest tests/test_integration_live.py -v

A full end-to-end MP3 download (which does require ffmpeg) is verified manually;
see the README and the project report.
"""

from __future__ import annotations

import os

import pytest

from ytmp3dl.channel import enumerate_videos
from ytmp3dl.config import Config

LIVE = os.environ.get("YTMP3DL_LIVE") == "1"

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not LIVE, reason="set YTMP3DL_LIVE=1 to run live network tests"),
]

EXAMPLE_CHANNEL = "https://www.youtube.com/@PapaPedroBeats"


def test_live_flat_enumeration_returns_videos():
    """Real flat-list of the example channel yields at least one video."""
    cfg = Config(limit=5)
    videos = enumerate_videos(EXAMPLE_CHANNEL, cfg)
    assert videos, "expected at least one video from the live channel"
    assert len(videos) <= 5
    first = videos[0]
    assert first.id
    assert first.url


def test_live_handle_normalization_matches_url():
    """Enumerating via @handle and via full URL should agree on video IDs."""
    cfg = Config(limit=3)
    by_handle = {v.id for v in enumerate_videos("@PapaPedroBeats", cfg)}
    by_url = {v.id for v in enumerate_videos(EXAMPLE_CHANNEL, cfg)}
    assert by_handle and by_url
    # The two enumerations should overlap substantially (same channel).
    assert by_handle & by_url
