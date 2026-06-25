# Plan: Dependable YouTube Channel → MP3 Downloader (`ytmp3dl`)

## Context

The repo currently holds a single, unrelated script (`extract_transcripts.py`) that
shells out to `yt-dlp` to pull playlist transcripts. We now want a **separate,
dependable command-line tool** that downloads **MP3 audio for every video on a
YouTube channel** (example: <https://www.youtube.com/@PapaPedroBeats>) and can be
re-run safely to pick up only new uploads.

"Dependable" is the whole point: the tool must survive flaky networks, throttling,
individual unavailable videos, and interrupted runs without losing progress or
corrupting output. It is built as a thin, well-tested wrapper around the
industry-standard `yt-dlp` + `ffmpeg`, adding battle-tested defaults, fault
isolation, resumability, structured reporting, and tests.

This work is **orchestrated**: this document + the milestone breakdown are prepared
by the orchestrator, and the implementation is delegated to an AI coder agent. The
orchestrator owns the plan, code review, the test gate, and all git operations.

## Goals

- Enumerate **all** videos on a channel given its URL or `@handle`.
- Download each as an **MP3** (default **320 kbps**), with embedded metadata + cover art.
- Be **idempotent / resumable**: re-runs skip already-downloaded videos (download archive).
- **Never let one bad video abort the batch**; retry transient failures with backoff.
- Produce a **manifest + summary report** and clear logs.
- Ship with an **automated test suite** that needs no network or ffmpeg (mock-based).

## Non-goals

- A GUI, a server, or a scheduler (idempotency makes external cron trivial; out of scope).
- Video (non-audio) downloads, subtitle/transcript extraction (already covered by the existing script).
- Bypassing paywalls, DRM, age/region restrictions beyond user-supplied cookies.

## Defaults (configurable; chosen by orchestrator pending user confirmation)

| Setting | Default | Override |
|---|---|---|
| Content scope | Regular videos (`/videos` tab) only | `--include-shorts`, `--include-streams` |
| Audio format | `mp3` | `--audio-format {mp3,m4a,opus,flac,wav,best}` |
| Audio quality | `320K` | `--audio-quality` |
| Keep source file | No | `--keep-original` |
| Output dir | `./downloads` | `-o/--output-dir` |
| Output template | `%(uploader)s/%(upload_date>%Y-%m-%d)s - %(title)s [%(id)s].%(ext)s` | `--output-template` |
| Archive file | `<output_dir>/.ytmp3dl-archive.txt` | `--archive` / `--no-archive` |
| Embed metadata + thumbnail | On | `--no-embed-metadata`, `--no-embed-thumbnail` |
| Concurrency | 1 (polite, sequential) | `--concurrency N` |
| Per-video retries (outer) | 2, exponential backoff | `--retries` |

## Architecture

A small installable Python package, `ytmp3dl`, with a console entry point. Python
3.11+ (matches the environment; uses stdlib `tomllib`, `argparse`, `logging`,
`dataclasses`). Only runtime dependency is `yt-dlp`; `ffmpeg`/`ffprobe` are system
deps that are **preflight-checked**. We use `yt-dlp` primarily as a **library**
(`yt_dlp.YoutubeDL`) for fine-grained control (progress hooks, postprocessors,
structured errors), which is more dependable than parsing CLI output.

```
ytmp3dl/
  __init__.py          # __version__
  __main__.py          # `python -m ytmp3dl`
  cli.py               # argparse CLI; merges config; dispatches commands
  config.py            # defaults -> TOML config -> CLI overrides (precedence)
  preflight.py         # detect ffmpeg/ffprobe + yt-dlp version; verify output dir writable
  channel.py           # normalize @handle/URL -> tab URLs; flat-enumerate videos; filters
  downloader.py        # assemble YoutubeDL opts (postprocessors, archive, outtmpl, sleeps); download one video
  runner.py            # batch loop: fault isolation, retries+backoff, drives manifest
  report.py            # manifest.json + failures file + console summary
  logging_setup.py     # console + rotating file logging; route yt-dlp logger
  errors.py            # typed exceptions (PreflightError, TransientDownloadError, ...)
tests/                 # pytest, mock-based (no network / no ffmpeg required)
  test_config.py  test_channel.py  test_preflight.py
  test_downloader_opts.py  test_runner.py  test_report.py  test_cli.py
  test_integration_live.py   # gated by env YTMP3DL_LIVE=1; skipped by default
pyproject.toml         # packaging, deps, console_script `ytmp3dl`, ruff + pytest config
README.md              # install (incl. ffmpeg per-OS), usage, examples, responsible-use note
.github/workflows/ci.yml   # ruff lint + pytest (mocked) on 3.11/3.12
```

`extract_transcripts.py` is left **untouched**.

### Key `yt-dlp` mechanics (verified against current docs)

- **Audio:** postprocessor `{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}`.
- **Metadata/art:** `writethumbnail=True` + postprocessors `FFmpegMetadata` and `EmbedThumbnail` (order: ExtractAudio → Metadata → Thumbnail).
- **Resumability:** `download_archive='<path>'` records completed IDs; re-runs skip them.
- **Enumeration:** `extract_flat='in_playlist'` on the tab URL to list videos without downloading.
- **Channel targeting:** pass `https://www.youtube.com/@Handle/videos` (and `/shorts`, `/streams` when enabled).
- **Resilience:** `retries`, `fragment_retries`, `extractor_retries`, `sleep_interval`/`max_sleep_interval`/`sleep_requests`, `ratelimit`, optional `cookiesfrombrowser`.

## Dependability features

1. **Preflight gate** — fail fast with actionable messages if ffmpeg/ffprobe missing
   (per-OS install hint) or output dir not writable; log yt-dlp version.
2. **Idempotent resume** — download archive + `.part`/atomic renames; safe to re-run/schedule.
3. **Per-video fault isolation** — each video in its own try/except; the batch always
   completes. Transient errors (network/HTTP/throttle) retried with exponential backoff;
   permanent ones (private/removed/geo) recorded and skipped.
4. **Structured outputs** — `manifest.json` (id → status/file/title/date/duration/error),
   a `failures` list, and a console summary (downloaded / skipped / failed / elapsed).
   Non-zero exit code if hard failures occurred (toggleable).
5. **Logging** — human console + rotating debug file; yt-dlp's logger routed through ours.
6. **Politeness** — modest default sleeps + sequential downloads to reduce throttling/bans.

## CLI (sketch)

```
ytmp3dl <channel-url-or-@handle> [options]
  -o/--output-dir  --audio-format  --audio-quality  --keep-original
  --include-shorts  --include-streams  --videos-only
  --limit N  --dateafter/--datebefore  --playlist-items
  --archive PATH | --no-archive
  --no-embed-metadata  --no-embed-thumbnail
  --concurrency N  --sleep-min  --sleep-max  --rate-limit
  --cookies-from-browser BROWSER | --cookies FILE
  --config PATH  --ffmpeg-location PATH
  --dry-run        # enumerate + print plan, download nothing
  --list           # print enumerated videos and exit
  --log-file PATH  --verbose | --quiet  --version
```

## Testing strategy (mock-first)

The CI environment (and this container) have **no ffmpeg and unreliable YouTube
access**, so the automated suite must not depend on either:

- Mock `yt_dlp.YoutubeDL` to assert **option assembly** (codec/quality, archive path,
  postprocessor presence + order, sleep/retry opts, `outtmpl`).
- `channel.py` URL-normalization unit tests (`@handle`, `/channel/`, `/c/`, legacy → tab URLs).
- `runner.py` fault-isolation: inject a fake downloader that fails on chosen IDs
  (transient vs permanent) → assert batch completes, backoff invoked (patch `sleep`),
  manifest/failures correct.
- `preflight.py`: patch `shutil.which` to simulate ffmpeg present/absent.
- `config.py` precedence; `cli.py` smoke (`--help`, `--version`, `--dry-run`).
- `test_integration_live.py`: real flat-list of the example channel, **skipped unless
  `YTMP3DL_LIVE=1`**.
- CI: `ruff` + `pytest` (mocked) on Python 3.11/3.12; no network, no ffmpeg.

## Verification

- **Automated (here + CI):** `pip install -e .[dev]`, then `pytest` (all mocked tests green);
  `ruff check`. `ytmp3dl --help/--version/--dry-run` run without error.
- **End-to-end (real MP3):** because this container lacks ffmpeg and reliable YouTube
  egress, a genuine download is verified by the **user on their Windows machine**, or via
  the gated `YTMP3DL_LIVE=1` test where network permits. Smoke command:
  `ytmp3dl https://www.youtube.com/@PapaPedroBeats --limit 1 -o ./downloads`.

## Orchestration model & milestones

One persistent **AI coder** agent implements; the **orchestrator** specs each
milestone, reviews the diff, runs the test gate, and performs every git commit/push.
The coder does **not** run git. Milestones (each gated on review + green tests):

- **M1 — Scaffold & preflight:** package layout, `pyproject.toml`, `config.py`,
  `preflight.py`, `logging_setup.py`, CLI skeleton (`--help/--version/--dry-run` stub),
  `.gitignore` additions, venv + deps. Tests: config + preflight.
- **M2 — Enumeration:** `channel.py` URL normalization + flat listing + filters;
  `--dry-run`/`--list`. Tests: normalization + filters (mocked).
- **M3 — Download core:** `downloader.py` opts/postprocessors/archive/progress + MP3
  extraction. Tests: opts assembly + archive skip.
- **M4 — Dependability:** `runner.py` fault isolation, retries/backoff, `report.py`
  manifest + summary + exit codes. Tests: runner failure scenarios.
- **M5 — Polish:** metadata/thumbnail embed, `README.md` (install incl. ffmpeg per-OS,
  usage, responsible-use), CI workflow, final suite green.

## Responsible use

This tool downloads publicly available media. Users are responsible for complying with
YouTube's Terms of Service and applicable copyright law (e.g. personal/offline use of
content they own or that is appropriately licensed). The README will state this clearly.