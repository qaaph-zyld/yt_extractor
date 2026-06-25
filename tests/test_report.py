"""Tests for run reporting: manifest, failures, summary, exit codes."""

from __future__ import annotations

import json

from ytmp3dl.report import RunReport, Status, VideoResult


def _result(vid, status, **kw):
    return VideoResult(id=vid, status=status, **kw)


def test_video_result_to_dict_serializes_status():
    r = _result("a", Status.DOWNLOADED, title="A", file="/a.mp3", duration=12.0)
    d = r.to_dict()
    assert d["status"] == "downloaded"  # plain string, JSON-friendly
    assert d["id"] == "a"
    assert d["file"] == "/a.mp3"
    # Round-trips through JSON without custom encoders.
    assert json.loads(json.dumps(d))["status"] == "downloaded"


def test_counts_tallies_each_status(tmp_path):
    report = RunReport.create(tmp_path)
    report.record(_result("a", Status.DOWNLOADED))
    report.record(_result("b", Status.DOWNLOADED))
    report.record(_result("c", Status.SKIPPED))
    report.record(_result("d", Status.FAILED, error="boom"))
    counts = report.counts()
    assert counts == {"downloaded": 2, "skipped": 1, "failed": 1}
    assert report.downloaded == 2
    assert report.skipped == 1
    assert report.failed == 1


def test_record_overwrites_same_id(tmp_path):
    report = RunReport.create(tmp_path)
    report.record(_result("a", Status.FAILED, error="first"))
    report.record(_result("a", Status.DOWNLOADED))
    assert report.results["a"].status is Status.DOWNLOADED
    assert report.failed == 0


def test_write_manifest_structure(tmp_path):
    report = RunReport.create(tmp_path)
    report.record(_result("a", Status.DOWNLOADED, title="A", file="/a.mp3", duration=5.0))
    report.write_manifest()
    data = json.loads(report.manifest_path.read_text())
    assert "generated_at" in data
    assert "summary" in data
    assert data["videos"]["a"]["title"] == "A"
    assert data["summary"]["downloaded"] == 1


def test_write_failures_only_when_failures(tmp_path):
    report = RunReport.create(tmp_path)
    report.record(_result("a", Status.DOWNLOADED))
    report.write_failures()
    assert not report.failures_path.exists()  # no failures -> no file

    report.record(_result("b", Status.FAILED, error="nope"))
    report.write_failures()
    assert report.failures_path.exists()
    failures = json.loads(report.failures_path.read_text())
    assert [f["id"] for f in failures] == ["b"]
    assert failures[0]["error"] == "nope"


def test_write_failures_clears_stale_file(tmp_path):
    report = RunReport.create(tmp_path)
    # Pretend a previous run left a failures file.
    report.failures_path.parent.mkdir(parents=True, exist_ok=True)
    report.failures_path.write_text("[]")
    report.record(_result("a", Status.DOWNLOADED))
    report.write_failures()
    assert not report.failures_path.exists()  # stale file removed


def test_exit_code_reflects_failures(tmp_path):
    report = RunReport.create(tmp_path)
    report.record(_result("a", Status.DOWNLOADED))
    assert report.exit_code() == 0
    report.record(_result("b", Status.FAILED, error="x"))
    assert report.exit_code() == 1
    assert report.has_hard_failures() is True


def test_summary_line_mentions_counts(tmp_path):
    report = RunReport.create(tmp_path)
    report.record(_result("a", Status.DOWNLOADED))
    report.record(_result("b", Status.SKIPPED))
    report.record(_result("c", Status.FAILED, error="x"))
    line = report.summary_line()
    assert "downloaded: 1" in line
    assert "skipped: 1" in line
    assert "failed: 1" in line


def test_manifest_write_is_atomic_no_tmp_left(tmp_path):
    report = RunReport.create(tmp_path)
    report.record(_result("a", Status.DOWNLOADED))
    report.write_manifest()
    # The temp file used for the atomic rename must not linger.
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


def test_create_sets_default_paths(tmp_path):
    report = RunReport.create(tmp_path)
    assert report.manifest_path == tmp_path / "manifest.json"
    assert report.failures_path == tmp_path / "failures.json"


def test_print_summary_runs_without_error(tmp_path, caplog):
    report = RunReport.create(tmp_path)
    report.record(_result("a", Status.DOWNLOADED))
    report.record(_result("b", Status.FAILED, error="boom"))
    # Should log a summary and list the failure without raising.
    report.print_summary()
