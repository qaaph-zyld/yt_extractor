"""Tests for channel URL normalization and flat enumeration."""

from __future__ import annotations

import pytest

from ytmp3dl import channel
from ytmp3dl.channel import (
    VideoEntry,
    apply_filters,
    enumerate_videos,
    normalize_channel_base,
    tab_urls,
)
from ytmp3dl.config import Config

BASE = "https://www.youtube.com"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("@PapaPedroBeats", f"{BASE}/@PapaPedroBeats"),
        ("PapaPedroBeats", f"{BASE}/@PapaPedroBeats"),
        (f"{BASE}/@Foo", f"{BASE}/@Foo"),
        (f"{BASE}/@Foo/videos", f"{BASE}/@Foo"),
        (f"{BASE}/@Foo/shorts", f"{BASE}/@Foo"),
        ("https://youtube.com/@Foo/streams", f"{BASE}/@Foo"),
        ("http://www.youtube.com/@Foo", f"{BASE}/@Foo"),
        (f"{BASE}/channel/UC123abc", f"{BASE}/channel/UC123abc"),
        (f"{BASE}/channel/UC123abc/videos", f"{BASE}/channel/UC123abc"),
        (f"{BASE}/c/SomeName", f"{BASE}/c/SomeName"),
        (f"{BASE}/c/SomeName/videos", f"{BASE}/c/SomeName"),
        (f"{BASE}/user/LegacyName", f"{BASE}/user/LegacyName"),
        ("youtube.com/user/LegacyName", f"{BASE}/user/LegacyName"),
        (f"{BASE}/SomeCustom", f"{BASE}/SomeCustom"),
        ("  @Spaced  ", f"{BASE}/@Spaced"),
    ],
)
def test_normalize_channel_base(given, expected):
    assert normalize_channel_base(given) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "@bad/handle",
        "https://vimeo.com/12345",
        "https://www.youtube.com/",
    ],
)
def test_normalize_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        normalize_channel_base(bad)


def test_tab_urls_videos_only_by_default():
    cfg = Config()
    assert tab_urls("@Foo", cfg) == [f"{BASE}/@Foo/videos"]


def test_tab_urls_includes_shorts_and_streams_when_enabled():
    cfg = Config(include_shorts=True, include_streams=True)
    assert tab_urls("@Foo", cfg) == [
        f"{BASE}/@Foo/videos",
        f"{BASE}/@Foo/shorts",
        f"{BASE}/@Foo/streams",
    ]


# --- filters ---------------------------------------------------------------


def _vids():
    return [
        VideoEntry(id="a", url="u", title="A", upload_date="20240101"),
        VideoEntry(id="b", url="u", title="B", upload_date="20240601"),
        VideoEntry(id="c", url="u", title="C", upload_date="20241231"),
        VideoEntry(id="d", url="u", title="D", upload_date=None),  # missing date
    ]


def test_apply_filters_limit():
    cfg = Config(limit=2)
    out = apply_filters(_vids(), cfg)
    assert [v.id for v in out] == ["a", "b"]


def test_apply_filters_limit_zero():
    cfg = Config(limit=0)
    assert apply_filters(_vids(), cfg) == []


def test_apply_filters_dateafter_keeps_unknown_dates():
    cfg = Config(dateafter="20240301")
    out = apply_filters(_vids(), cfg)
    # b, c pass; a is before; d has unknown date -> kept (filtered downstream)
    assert [v.id for v in out] == ["b", "c", "d"]


def test_apply_filters_datebefore():
    cfg = Config(datebefore="20240701")
    out = apply_filters(_vids(), cfg)
    assert [v.id for v in out] == ["a", "b", "d"]


def test_apply_filters_date_range_accepts_dashed_dates():
    cfg = Config(dateafter="2024-03-01", datebefore="2024-07-01")
    out = apply_filters(_vids(), cfg)
    assert [v.id for v in out] == ["b", "d"]


def test_apply_filters_limit_applied_after_date():
    cfg = Config(dateafter="20240301", limit=1)
    out = apply_filters(_vids(), cfg)
    assert [v.id for v in out] == ["b"]


# --- enumeration (mocked yt_dlp) -------------------------------------------


def _make_factory(info_map):
    """Build a fake YoutubeDL factory returning canned info per URL."""

    class _FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            return info_map.get(url)

    return _FakeYDL


def test_enumerate_videos_flat_listing():
    cfg = Config()
    url = f"{BASE}/@Foo/videos"
    info = {
        "entries": [
            {"id": "v1", "title": "One", "url": "https://youtu.be/v1", "upload_date": "20240101"},
            {"id": "v2", "title": "Two", "url": "https://youtu.be/v2", "upload_date": "20240202"},
        ]
    }
    factory = _make_factory({url: info})
    out = enumerate_videos("@Foo", cfg, ydl_factory=factory)
    assert [v.id for v in out] == ["v1", "v2"]
    assert out[0].title == "One"


def test_enumerate_videos_dedupes_across_tabs():
    cfg = Config(include_shorts=True)
    videos_url = f"{BASE}/@Foo/videos"
    shorts_url = f"{BASE}/@Foo/shorts"
    info_map = {
        videos_url: {"entries": [{"id": "v1", "title": "One"}, {"id": "dup", "title": "Dup"}]},
        shorts_url: {"entries": [{"id": "dup", "title": "Dup"}, {"id": "s1", "title": "Short"}]},
    }
    factory = _make_factory(info_map)
    out = enumerate_videos("@Foo", cfg, ydl_factory=factory)
    assert [v.id for v in out] == ["v1", "dup", "s1"]


def test_enumerate_videos_handles_nested_entries():
    cfg = Config()
    url = f"{BASE}/@Foo/videos"
    info = {
        "entries": [
            {"entries": [{"id": "n1", "title": "Nested1"}, {"id": "n2", "title": "Nested2"}]},
            {"id": "top", "title": "Top"},
        ]
    }
    factory = _make_factory({url: info})
    out = enumerate_videos("@Foo", cfg, ydl_factory=factory)
    assert {v.id for v in out} == {"n1", "n2", "top"}


def test_enumerate_videos_skips_none_holes():
    # ignoreerrors can leave None entries; they must be skipped.
    cfg = Config()
    url = f"{BASE}/@Foo/videos"
    info = {"entries": [{"id": "v1", "title": "One"}, None, {"id": "v2", "title": "Two"}]}
    factory = _make_factory({url: info})
    out = enumerate_videos("@Foo", cfg, ydl_factory=factory)
    assert [v.id for v in out] == ["v1", "v2"]


def test_enumerate_videos_one_failing_tab_does_not_abort():
    cfg = Config(include_shorts=True)
    shorts_url = f"{BASE}/@Foo/shorts"

    class _FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            if url == shorts_url:
                raise RuntimeError("network boom on shorts tab")
            return {"entries": [{"id": "v1", "title": "One"}]}

    out = enumerate_videos("@Foo", cfg, ydl_factory=_FakeYDL)
    # videos tab still yields its entry despite the shorts tab failing.
    assert [v.id for v in out] == ["v1"]


def test_enumerate_videos_applies_limit():
    cfg = Config(limit=1)
    url = f"{BASE}/@Foo/videos"
    info = {"entries": [{"id": "v1"}, {"id": "v2"}, {"id": "v3"}]}
    factory = _make_factory({url: info})
    out = enumerate_videos("@Foo", cfg, ydl_factory=factory)
    assert [v.id for v in out] == ["v1"]


def test_flat_opts_carry_filters():
    cfg = Config(playlist_items="1-5", dateafter="20240101", cookies="/c.txt")
    opts = channel._flat_opts(cfg)
    assert opts["extract_flat"] == "in_playlist"
    assert opts["skip_download"] is True
    assert opts["ignoreerrors"] is True
    assert opts["playlist_items"] == "1-5"
    assert opts["dateafter"] == "20240101"
    assert opts["cookiefile"] == "/c.txt"
