"""Tests for yt-dlp option assembly and download dispatch (mocked YoutubeDL)."""

from __future__ import annotations

import pytest

from ytmp3dl import downloader
from ytmp3dl.channel import VideoEntry
from ytmp3dl.config import Config
from ytmp3dl.downloader import (
    build_ydl_opts,
    classify_error,
    download_one,
)
from ytmp3dl.errors import PermanentDownloadError, TransientDownloadError


def _pp_keys(opts):
    return [pp["key"] for pp in opts["postprocessors"]]


def test_format_is_bestaudio():
    opts = build_ydl_opts(Config())
    assert opts["format"] == "bestaudio/best"


def test_default_codec_and_quality():
    opts = build_ydl_opts(Config())
    extract = opts["postprocessors"][0]
    assert extract["key"] == "FFmpegExtractAudio"
    assert extract["preferredcodec"] == "mp3"
    assert extract["preferredquality"] == "320"


def test_quality_parsing_variants():
    assert build_ydl_opts(Config(audio_quality="320K"))["postprocessors"][0]["preferredquality"] == "320"
    assert build_ydl_opts(Config(audio_quality="256k"))["postprocessors"][0]["preferredquality"] == "256"
    assert build_ydl_opts(Config(audio_quality="192"))["postprocessors"][0]["preferredquality"] == "192"
    # Unparseable falls back to 320.
    assert build_ydl_opts(Config(audio_quality="best"))["postprocessors"][0]["preferredquality"] == "320"


def test_codec_override():
    opts = build_ydl_opts(Config(audio_format="opus"))
    assert opts["postprocessors"][0]["preferredcodec"] == "opus"


def test_postprocessor_order_is_extract_metadata_thumbnail():
    opts = build_ydl_opts(Config())
    assert _pp_keys(opts) == ["FFmpegExtractAudio", "FFmpegMetadata", "EmbedThumbnail"]


def test_postprocessor_order_with_metadata_disabled():
    opts = build_ydl_opts(Config(embed_metadata=False))
    assert _pp_keys(opts) == ["FFmpegExtractAudio", "EmbedThumbnail"]


def test_postprocessor_order_with_thumbnail_disabled():
    opts = build_ydl_opts(Config(embed_thumbnail=False))
    assert _pp_keys(opts) == ["FFmpegExtractAudio", "FFmpegMetadata"]


def test_best_format_skips_transcode_postprocessor():
    opts = build_ydl_opts(Config(audio_format="best"))
    # No FFmpegExtractAudio when keeping source audio as-is.
    assert "FFmpegExtractAudio" not in _pp_keys(opts)
    assert _pp_keys(opts) == ["FFmpegMetadata", "EmbedThumbnail"]


def test_writethumbnail_always_set():
    assert build_ydl_opts(Config())["writethumbnail"] is True


def test_archive_path_included_when_provided():
    opts = build_ydl_opts(Config(), archive_path="/data/.archive.txt")
    assert opts["download_archive"] == "/data/.archive.txt"


def test_archive_omitted_when_none():
    opts = build_ydl_opts(Config(), archive_path=None)
    assert "download_archive" not in opts


def test_outtmpl_combines_output_dir_and_template():
    cfg = Config(output_dir="music", output_template="%(id)s.%(ext)s")
    opts = build_ydl_opts(cfg)
    assert opts["outtmpl"] == "music/%(id)s.%(ext)s"


def test_default_outtmpl_shape():
    opts = build_ydl_opts(Config(output_dir="downloads"))
    assert opts["outtmpl"].startswith("downloads/")
    assert "%(uploader)s" in opts["outtmpl"]
    assert "%(id)s" in opts["outtmpl"]


def test_retry_options_present():
    opts = build_ydl_opts(Config())
    assert opts["retries"] == 10
    assert opts["fragment_retries"] == 10
    assert opts["extractor_retries"] == 3


def test_sleep_options_from_config():
    cfg = Config(sleep_min=2.5, sleep_max=9.0, sleep_requests=1.5)
    opts = build_ydl_opts(cfg)
    assert opts["sleep_interval"] == 2.5
    assert opts["max_sleep_interval"] == 9.0
    assert opts["sleep_requests"] == 1.5


def test_keepvideo_when_keep_original():
    assert build_ydl_opts(Config(keep_original=True))["keepvideo"] is True
    assert "keepvideo" not in build_ydl_opts(Config(keep_original=False))


def test_rate_limit_parsing():
    assert build_ydl_opts(Config(rate_limit="1M"))["ratelimit"] == 1024**2
    assert build_ydl_opts(Config(rate_limit="500K"))["ratelimit"] == 500 * 1024
    assert build_ydl_opts(Config(rate_limit="1.5M"))["ratelimit"] == int(1.5 * 1024**2)
    assert build_ydl_opts(Config(rate_limit="2048"))["ratelimit"] == 2048


def test_rate_limit_unparseable_is_ignored():
    opts = build_ydl_opts(Config(rate_limit="fast"))
    assert "ratelimit" not in opts


def test_cookies_options():
    opts = build_ydl_opts(Config(cookies="/c.txt"))
    assert opts["cookiefile"] == "/c.txt"
    opts2 = build_ydl_opts(Config(cookies_from_browser="firefox"))
    assert opts2["cookiesfrombrowser"] == ("firefox",)


def test_ffmpeg_location_option():
    opts = build_ydl_opts(Config(ffmpeg_location="/opt/ffmpeg/bin"))
    assert opts["ffmpeg_location"] == "/opt/ffmpeg/bin"


def test_progress_hook_wired_when_provided():
    hook = lambda d: None  # noqa: E731
    opts = build_ydl_opts(Config(), progress_hook=hook)
    assert opts["progress_hooks"] == [hook]


def test_ignoreerrors_false_so_runner_handles_isolation():
    # yt-dlp must raise so the runner can classify/retry; it must not swallow.
    assert build_ydl_opts(Config())["ignoreerrors"] is False


def test_unsupported_format_raises():
    with pytest.raises(ValueError, match="Unsupported audio format"):
        build_ydl_opts(Config(audio_format="aac"))


# --- error classification --------------------------------------------------


@pytest.mark.parametrize(
    "msg",
    [
        "ERROR: Private video. Sign in if you've been granted access",
        "ERROR: Video unavailable",
        "This video has been removed by the uploader",
        "Video unavailable. This video is not available in your country",
        "Join this channel to get access to members-only content",
        "Sign in to confirm your age",
    ],
)
def test_classify_permanent(msg):
    assert isinstance(classify_error(Exception(msg)), PermanentDownloadError)


@pytest.mark.parametrize(
    "msg",
    [
        "Unable to download webpage: The read operation timed out",
        "HTTP Error 503: Service Unavailable",
        "HTTP Error 429: Too Many Requests",
        "Connection reset by peer",
        "Temporary failure in name resolution",
        "[download] Got server HTTP error: throttled",
    ],
)
def test_classify_transient(msg):
    assert isinstance(classify_error(Exception(msg)), TransientDownloadError)


def test_classify_unknown_defaults_to_transient():
    # Unknown errors get the benefit of the (bounded) retry budget.
    assert isinstance(classify_error(Exception("something weird happened")), TransientDownloadError)


# --- download_one (mocked YoutubeDL) ---------------------------------------


class _RecordingYDL:
    last_opts = None
    behaviour = None  # callable(url, download) -> info | raises

    def __init__(self, opts):
        type(self).last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        if type(self).behaviour is not None:
            return type(self).behaviour(url, download)
        return {"id": "v1", "title": "T"}


def test_download_one_passes_opts_and_downloads():
    _RecordingYDL.last_opts = None
    _RecordingYDL.behaviour = lambda url, download: {"id": "v1", "title": "T", "_url": url, "_dl": download}
    video = VideoEntry(id="v1", url="https://youtu.be/v1", title="T")
    info = download_one(video, Config(), archive_path="/a.txt", ydl_factory=_RecordingYDL)
    assert info["id"] == "v1"
    assert info["_dl"] is True  # download=True was passed
    # Opts were assembled with the archive path.
    assert _RecordingYDL.last_opts["download_archive"] == "/a.txt"
    assert _RecordingYDL.last_opts["format"] == "bestaudio/best"


def test_download_one_classifies_permanent_error():
    def boom(url, download):
        raise Exception("ERROR: Private video")

    _RecordingYDL.behaviour = boom
    video = VideoEntry(id="v1", url="u", title="T")
    with pytest.raises(PermanentDownloadError):
        download_one(video, Config(), ydl_factory=_RecordingYDL)


def test_download_one_classifies_transient_error():
    def boom(url, download):
        raise Exception("HTTP Error 503: Service Unavailable")

    _RecordingYDL.behaviour = boom
    video = VideoEntry(id="v1", url="u", title="T")
    with pytest.raises(TransientDownloadError):
        download_one(video, Config(), ydl_factory=_RecordingYDL)


def test_make_progress_hook_is_callable():
    hook = downloader.make_progress_hook()
    # Should not raise on representative events.
    hook({"status": "finished", "filename": "x.mp3"})
    hook({"status": "downloading", "filename": "x.mp3"})
    hook({"status": "error", "filename": "x.mp3"})
