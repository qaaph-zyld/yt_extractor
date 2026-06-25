"""Tests for configuration precedence: defaults -> TOML -> CLI."""

from __future__ import annotations

import pytest

from ytmp3dl.config import (
    DEFAULT_ARCHIVE_NAME,
    Config,
    build_config,
    load_toml,
)


def test_defaults_match_plan():
    cfg = Config()
    assert cfg.audio_format == "mp3"
    assert cfg.audio_quality == "320K"
    assert cfg.output_dir == "downloads"
    assert cfg.concurrency == 1
    assert cfg.retries == 2
    assert cfg.use_archive is True
    assert cfg.embed_metadata is True
    assert cfg.embed_thumbnail is True


def test_archive_path_defaults_under_output_dir():
    cfg = Config(output_dir="out")
    assert cfg.archive_path() == f"out/{DEFAULT_ARCHIVE_NAME}"


def test_archive_path_explicit_override():
    cfg = Config(output_dir="out", archive="/custom/arch.txt")
    assert cfg.archive_path() == "/custom/arch.txt"


def test_archive_path_disabled():
    cfg = Config(use_archive=False)
    assert cfg.archive_path() is None


def test_toml_overrides_defaults():
    cfg = build_config(toml_values={"audio_quality": "256K", "concurrency": 3})
    assert cfg.audio_quality == "256K"
    assert cfg.concurrency == 3
    # Untouched values keep their defaults.
    assert cfg.audio_format == "mp3"


def test_cli_overrides_toml():
    cfg = build_config(
        toml_values={"audio_quality": "256K", "output_dir": "from_toml"},
        cli_overrides={"audio_quality": "320K"},
    )
    assert cfg.audio_quality == "320K"  # CLI wins
    assert cfg.output_dir == "from_toml"  # TOML still applies where CLI silent


def test_cli_none_values_should_be_filtered_by_caller():
    # build_config does not special-case None, so callers must drop unset flags.
    # Here we simulate a caller passing only set values.
    cfg = build_config(cli_overrides={"limit": 5})
    assert cfg.limit == 5
    assert cfg.dateafter is None


def test_load_toml_reads_table_wrapper(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[ytmp3dl]\naudio_quality = "192K"\nlimit = 7\n')
    values = load_toml(p)
    assert values == {"audio_quality": "192K", "limit": 7}


def test_load_toml_reads_top_level(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('output_dir = "music"\n')
    assert load_toml(p) == {"output_dir": "music"}


def test_load_toml_rejects_unknown_keys(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('bogus_key = 1\n')
    with pytest.raises(ValueError, match="Unknown config key"):
        load_toml(p)


def test_full_precedence_chain(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        '[ytmp3dl]\n'
        'audio_format = "m4a"\n'
        'audio_quality = "256K"\n'
        'output_dir = "toml_dir"\n'
    )
    toml_values = load_toml(p)
    cfg = build_config(
        toml_values=toml_values,
        cli_overrides={"output_dir": "cli_dir", "limit": 2},
    )
    # default where neither sets it
    assert cfg.concurrency == 1
    # toml where cli silent
    assert cfg.audio_format == "m4a"
    assert cfg.audio_quality == "256K"
    # cli wins over toml
    assert cfg.output_dir == "cli_dir"
    # cli-only value
    assert cfg.limit == 2
