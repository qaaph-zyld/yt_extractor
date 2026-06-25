"""Tests for the CLI: --help, --version, --dry-run/--list, config merge, dispatch."""

from __future__ import annotations

import pytest

from ytmp3dl import __version__, cli
from ytmp3dl.channel import VideoEntry
from ytmp3dl.config import Config


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "ytmp3dl" in out
    assert "--audio-format" in out
    assert "--dry-run" in out


def test_version_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert __version__ in out


def test_missing_url_errors(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    # argparse error() exits with code 2.
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "required" in err


def test_resolve_config_merges_cli_over_defaults():
    parser = cli.build_parser()
    args = parser.parse_args(["@Foo", "--audio-quality", "256K", "--limit", "3"])
    cfg = cli.resolve_config(args)
    assert cfg.audio_quality == "256K"
    assert cfg.limit == 3
    assert cfg.audio_format == "mp3"  # untouched default


def test_resolve_config_unset_flags_do_not_clobber():
    parser = cli.build_parser()
    # Only --output-dir set; store_true flags left unset must stay at defaults.
    args = parser.parse_args(["@Foo", "-o", "out"])
    cfg = cli.resolve_config(args)
    assert cfg.output_dir == "out"
    assert cfg.keep_original is False
    assert cfg.include_shorts is False
    assert cfg.use_archive is True
    assert cfg.embed_metadata is True


def test_resolve_config_negative_flags():
    parser = cli.build_parser()
    args = parser.parse_args(
        ["@Foo", "--no-archive", "--no-embed-metadata", "--no-embed-thumbnail"]
    )
    cfg = cli.resolve_config(args)
    assert cfg.use_archive is False
    assert cfg.embed_metadata is False
    assert cfg.embed_thumbnail is False


def test_resolve_config_videos_only_overrides_scope():
    parser = cli.build_parser()
    args = parser.parse_args(["@Foo", "--videos-only"])
    cfg = cli.resolve_config(args)
    assert cfg.include_shorts is False
    assert cfg.include_streams is False


def test_resolve_config_with_toml(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[ytmp3dl]\naudio_format = "m4a"\noutput_dir = "from_toml"\n')
    parser = cli.build_parser()
    args = parser.parse_args(["@Foo", "--config", str(p), "-o", "from_cli"])
    cfg = cli.resolve_config(args)
    assert cfg.audio_format == "m4a"  # from toml
    assert cfg.output_dir == "from_cli"  # cli overrides toml


def _patch_enumerate(monkeypatch, videos):
    def fake_enumerate(url, config, **kwargs):
        return videos

    monkeypatch.setattr(cli, "enumerate_videos", fake_enumerate, raising=False)
    # cli imports these names lazily inside main(); patch the source modules too.
    import ytmp3dl.channel as channel_mod

    monkeypatch.setattr(channel_mod, "enumerate_videos", fake_enumerate)


def test_dry_run_prints_plan_and_downloads_nothing(monkeypatch, capsys, tmp_path):
    videos = [
        VideoEntry(id="v1", url="u", title="One", upload_date="20240101"),
        VideoEntry(id="v2", url="u", title="Two", upload_date="20240202"),
    ]
    _patch_enumerate(monkeypatch, videos)

    # Guard: run_batch must never be called in dry-run.
    import ytmp3dl.runner as runner_mod

    def boom(*a, **k):
        raise AssertionError("run_batch should not be called for --dry-run")

    monkeypatch.setattr(runner_mod, "run_batch", boom)

    rc = cli.main(["@Foo", "--dry-run", "-o", str(tmp_path / "out")])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "v1" in out and "v2" in out
    assert "Total: 2" in out


def test_list_prints_videos(monkeypatch, capsys, tmp_path):
    videos = [VideoEntry(id="v1", url="u", title="One", upload_date="20240101")]
    _patch_enumerate(monkeypatch, videos)
    rc = cli.main(["@Foo", "--list", "-o", str(tmp_path / "out")])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Enumerated videos" in out
    assert "v1" in out


def test_dry_run_skips_ffmpeg_preflight(monkeypatch, tmp_path):
    # No ffmpeg on PATH, but --dry-run must not require it.
    import ytmp3dl.preflight as pf

    monkeypatch.setattr(pf.shutil, "which", lambda name: None)
    _patch_enumerate(monkeypatch, [VideoEntry(id="v1", url="u", title="One")])
    rc = cli.main(["@Foo", "--dry-run", "-o", str(tmp_path / "out")])
    assert rc == cli.EXIT_OK


def test_full_run_dispatches_to_runner(monkeypatch, tmp_path):
    videos = [VideoEntry(id="v1", url="u", title="One")]
    _patch_enumerate(monkeypatch, videos)

    # ffmpeg present.
    import ytmp3dl.preflight as pf

    monkeypatch.setattr(pf.shutil, "which", lambda name: f"/usr/bin/{name}")

    called = {}

    class FakeReport:
        def print_summary(self):
            called["summary"] = True

        def exit_code(self):
            return 0

    def fake_run_batch(vids, config, **kwargs):
        called["videos"] = vids
        return FakeReport()

    import ytmp3dl.runner as runner_mod

    monkeypatch.setattr(runner_mod, "run_batch", fake_run_batch)

    rc = cli.main(["@Foo", "-o", str(tmp_path / "out")])
    assert rc == 0
    assert called["videos"] == videos
    assert called.get("summary") is True


def test_bad_channel_reference_returns_preflight_code(monkeypatch, tmp_path):
    import ytmp3dl.preflight as pf

    monkeypatch.setattr(pf.shutil, "which", lambda name: f"/usr/bin/{name}")

    import ytmp3dl.channel as channel_mod

    def raise_value(url, config, **kwargs):
        raise ValueError("cannot interpret")

    monkeypatch.setattr(channel_mod, "enumerate_videos", raise_value)
    rc = cli.main(["not a url at all", "-o", str(tmp_path / "out")])
    assert rc == cli.EXIT_PREFLIGHT


def test_preflight_failure_returns_code(monkeypatch, tmp_path):
    # ffmpeg missing on a real (non-dry) run -> EXIT_PREFLIGHT.
    import ytmp3dl.preflight as pf

    monkeypatch.setattr(pf.shutil, "which", lambda name: None)
    rc = cli.main(["@Foo", "-o", str(tmp_path / "out")])
    assert rc == cli.EXIT_PREFLIGHT


def test_config_dataclass_is_default_constructible():
    # Sanity: Config() must not require any args (defaults complete).
    assert isinstance(Config(), Config)
