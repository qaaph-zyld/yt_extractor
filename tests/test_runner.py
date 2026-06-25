"""Tests for the dependability core: fault isolation, retries, backoff.

A fake downloader is injected so we can script exactly which video IDs fail and
how (transient vs permanent), and assert that:

* the batch always completes (one bad video never aborts it),
* transient failures are retried with exponential backoff the right number of
  times (with ``sleep`` patched so no real waiting happens),
* permanent failures are not retried,
* the manifest and failures records are correct.
"""

from __future__ import annotations

from typing import Any

from ytmp3dl.channel import VideoEntry
from ytmp3dl.config import Config
from ytmp3dl.errors import PermanentDownloadError, TransientDownloadError
from ytmp3dl.report import RunReport, Status
from ytmp3dl.runner import download_with_retries, run_batch


def make_videos(*ids: str) -> list[VideoEntry]:
    return [VideoEntry(id=i, url=f"https://youtu.be/{i}", title=i.upper()) for i in ids]


class FakeDownloader:
    """Scriptable downloader injected into the runner.

    ``plan`` maps video id -> behaviour:
      * "ok": succeed immediately, returning a synthetic info dict.
      * ("transient", n): raise TransientDownloadError on the first n calls,
        then succeed.
      * "transient_always": always raise TransientDownloadError.
      * "permanent": raise PermanentDownloadError immediately.
    """

    def __init__(self, plan: dict[str, Any]):
        self.plan = plan
        self.calls: dict[str, int] = {}

    def __call__(self, video: VideoEntry, config: Config, *, archive_path=None):
        self.calls[video.id] = self.calls.get(video.id, 0) + 1
        n = self.calls[video.id]
        behaviour = self.plan.get(video.id, "ok")

        if behaviour == "ok":
            return {"id": video.id, "title": video.title, "filepath": f"/out/{video.id}.mp3"}
        if behaviour == "permanent":
            raise PermanentDownloadError(f"private video {video.id}")
        if behaviour == "transient_always":
            raise TransientDownloadError(f"HTTP 503 for {video.id}")
        if isinstance(behaviour, tuple) and behaviour[0] == "transient":
            fail_times = behaviour[1]
            if n <= fail_times:
                raise TransientDownloadError(f"timeout {video.id} (attempt {n})")
            return {"id": video.id, "title": video.title, "filepath": f"/out/{video.id}.mp3"}
        raise AssertionError(f"unknown behaviour {behaviour!r}")


class SpySleep:
    """Records sleep durations instead of actually sleeping."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


# --- download_with_retries -------------------------------------------------


def test_success_no_retry():
    sleep = SpySleep()
    dl = FakeDownloader({"a": "ok"})
    cfg = Config(retries=2)
    result = download_with_retries(
        make_videos("a")[0], cfg, archive_path=None, downloader=dl, sleep=sleep
    )
    assert result.status is Status.DOWNLOADED
    assert result.file == "/out/a.mp3"
    assert result.attempts == 1
    assert sleep.delays == []  # no backoff on success
    assert dl.calls["a"] == 1


def test_transient_then_success_retries_with_backoff():
    sleep = SpySleep()
    # Fail twice, succeed on the 3rd attempt; retries=2 allows exactly that.
    dl = FakeDownloader({"a": ("transient", 2)})
    cfg = Config(retries=2)
    result = download_with_retries(
        make_videos("a")[0], cfg, archive_path=None, downloader=dl, sleep=sleep, backoff_base=2.0
    )
    assert result.status is Status.DOWNLOADED
    assert result.attempts == 3
    assert dl.calls["a"] == 3
    # Backoff invoked twice (before attempts 2 and 3): 2*2^0=2, 2*2^1=4.
    assert sleep.delays == [2.0, 4.0]


def test_transient_exhausts_retries_then_fails():
    sleep = SpySleep()
    dl = FakeDownloader({"a": "transient_always"})
    cfg = Config(retries=2)
    result = download_with_retries(
        make_videos("a")[0], cfg, archive_path=None, downloader=dl, sleep=sleep
    )
    assert result.status is Status.FAILED
    assert "exhausted retries" in (result.error or "")
    # 1 initial + 2 retries = 3 attempts; backoff slept twice (not after the last).
    assert dl.calls["a"] == 3
    assert len(sleep.delays) == 2


def test_permanent_error_not_retried():
    sleep = SpySleep()
    dl = FakeDownloader({"a": "permanent"})
    cfg = Config(retries=5)  # generous budget, but permanent must skip it
    result = download_with_retries(
        make_videos("a")[0], cfg, archive_path=None, downloader=dl, sleep=sleep
    )
    assert result.status is Status.FAILED
    assert result.error and result.error.startswith("permanent")
    assert dl.calls["a"] == 1  # tried exactly once
    assert sleep.delays == []  # never slept


def test_retries_zero_means_single_attempt():
    sleep = SpySleep()
    dl = FakeDownloader({"a": "transient_always"})
    cfg = Config(retries=0)
    result = download_with_retries(
        make_videos("a")[0], cfg, archive_path=None, downloader=dl, sleep=sleep
    )
    assert result.status is Status.FAILED
    assert dl.calls["a"] == 1
    assert sleep.delays == []


def test_backoff_is_exponential():
    sleep = SpySleep()
    dl = FakeDownloader({"a": "transient_always"})
    cfg = Config(retries=4)
    download_with_retries(
        make_videos("a")[0], cfg, archive_path=None, downloader=dl, sleep=sleep, backoff_base=1.0
    )
    # 4 retries -> sleeps before attempts 2..5: 1,2,4,8.
    assert sleep.delays == [1.0, 2.0, 4.0, 8.0]


# --- run_batch: fault isolation & reporting --------------------------------


def test_batch_completes_despite_failures(tmp_path):
    sleep = SpySleep()
    videos = make_videos("a", "b", "c", "d")
    plan = {
        "a": "ok",
        "b": "permanent",  # bad video in the middle
        "c": "transient_always",  # exhausts retries
        "d": "ok",  # must still run after b and c failed
    }
    dl = FakeDownloader(plan)
    cfg = Config(output_dir=str(tmp_path / "out"), retries=2)
    report = run_batch(videos, cfg, downloader=dl, sleep=sleep)

    # Every video was attempted; the batch did not abort early.
    assert set(dl.calls) == {"a", "b", "c", "d"}
    assert report.results["a"].status is Status.DOWNLOADED
    assert report.results["b"].status is Status.FAILED
    assert report.results["c"].status is Status.FAILED
    assert report.results["d"].status is Status.DOWNLOADED
    assert report.downloaded == 2
    assert report.failed == 2


def test_batch_writes_manifest_and_failures(tmp_path):
    import json

    sleep = SpySleep()
    videos = make_videos("a", "b")
    dl = FakeDownloader({"a": "ok", "b": "permanent"})
    cfg = Config(output_dir=str(tmp_path / "out"), retries=1)
    report = run_batch(videos, cfg, downloader=dl, sleep=sleep)

    # Manifest exists and reflects both videos.
    manifest = json.loads(report.manifest_path.read_text())
    assert set(manifest["videos"]) == {"a", "b"}
    assert manifest["videos"]["a"]["status"] == "downloaded"
    assert manifest["videos"]["b"]["status"] == "failed"
    assert manifest["summary"]["downloaded"] == 1
    assert manifest["summary"]["failed"] == 1

    # Failures file lists only the failed video.
    failures = json.loads(report.failures_path.read_text())
    assert [f["id"] for f in failures] == ["b"]


def test_batch_exit_code_nonzero_on_failure(tmp_path):
    sleep = SpySleep()
    dl = FakeDownloader({"a": "permanent"})
    cfg = Config(output_dir=str(tmp_path / "out"))
    report = run_batch(make_videos("a"), cfg, downloader=dl, sleep=sleep)
    assert report.exit_code() == 1


def test_batch_exit_code_zero_on_all_success(tmp_path):
    sleep = SpySleep()
    dl = FakeDownloader({"a": "ok", "b": "ok"})
    cfg = Config(output_dir=str(tmp_path / "out"))
    report = run_batch(make_videos("a", "b"), cfg, downloader=dl, sleep=sleep)
    assert report.exit_code() == 0
    assert report.failed == 0


def test_empty_batch_writes_manifest(tmp_path):
    cfg = Config(output_dir=str(tmp_path / "out"))
    report = run_batch([], cfg, downloader=FakeDownloader({}), sleep=SpySleep())
    assert report.manifest_path.exists()
    assert report.downloaded == 0


def test_manifest_written_incrementally(tmp_path):
    # After a failure mid-batch, the manifest on disk should already include the
    # earlier successful video -- proving incremental, crash-resilient writes.
    import json

    sleep = SpySleep()
    seen_on_disk: dict[str, Any] = {}

    class CheckingDownloader(FakeDownloader):
        def __call__(self, video, config, *, archive_path=None):
            # Snapshot the manifest as it stands before this video's result.
            if manifest_path.exists():
                seen_on_disk[video.id] = set(json.loads(manifest_path.read_text())["videos"])
            return super().__call__(video, config, archive_path=archive_path)

    cfg = Config(output_dir=str(tmp_path / "out"), retries=0)
    manifest_path = (tmp_path / "out") / "manifest.json"
    dl = CheckingDownloader({"a": "ok", "b": "ok"})
    run_batch(make_videos("a", "b"), cfg, downloader=dl, sleep=sleep)
    # By the time "b" is downloaded, "a" is already persisted in the manifest.
    assert "a" in seen_on_disk.get("b", set())


def test_concurrent_batch_completes(tmp_path):
    # With concurrency > 1, all videos still complete and faults stay isolated.
    sleep = SpySleep()
    videos = make_videos("a", "b", "c", "d", "e")
    plan = {"c": "permanent"}  # one failure among parallel workers
    dl = FakeDownloader(plan)
    cfg = Config(output_dir=str(tmp_path / "out"), concurrency=3, retries=1)
    report = run_batch(videos, cfg, downloader=dl, sleep=sleep)
    assert set(dl.calls) == {"a", "b", "c", "d", "e"}
    assert report.downloaded == 4
    assert report.failed == 1
    assert report.results["c"].status is Status.FAILED


def test_result_extracts_filepath_from_requested_downloads(tmp_path):
    sleep = SpySleep()

    class RDownloader:
        def __call__(self, video, config, *, archive_path=None):
            return {
                "id": video.id,
                "title": "T",
                "requested_downloads": [{"filepath": "/final/path.mp3"}],
            }

    cfg = Config(output_dir=str(tmp_path / "out"))
    report = run_batch(make_videos("a"), cfg, downloader=RDownloader(), sleep=sleep)
    assert report.results["a"].file == "/final/path.mp3"


def test_run_batch_uses_provided_report(tmp_path):
    sleep = SpySleep()
    report = RunReport.create(str(tmp_path / "out"))
    dl = FakeDownloader({"a": "ok"})
    cfg = Config(output_dir=str(tmp_path / "out"))
    returned = run_batch(make_videos("a"), cfg, report=report, downloader=dl, sleep=sleep)
    assert returned is report
