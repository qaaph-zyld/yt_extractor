# ytmp3dl

Dependably download **MP3 audio for every video on a YouTube channel**, with
embedded metadata and cover art. Re-runs are idempotent: a download archive
means each run only picks up new uploads. Built as a thin, well-tested wrapper
around [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) + [`ffmpeg`](https://ffmpeg.org/),
adding fault isolation, retries with backoff, structured reporting, and a
mock-based test suite.

## Why "dependable"?

- **Preflight gate** — fails fast with an actionable, per-OS hint if `ffmpeg`/`ffprobe`
  are missing or the output directory is not writable; logs the `yt-dlp` version.
- **Idempotent resume** — a download archive records completed video IDs, so
  re-running (or scheduling via your OS) only fetches new videos. Previously
  fetched videos are reported as `skipped` (so a re-run with nothing new shows
  `skipped: N, downloaded: 0`).
- **Per-video fault isolation** — each video downloads in its own try/except;
  one bad video (private/removed/geo-blocked) never aborts the batch.
- **Retry with backoff** — transient failures (network/HTTP 5xx/429/throttling)
  are retried with exponential backoff; permanent failures are recorded and skipped.
- **Structured output** — a `manifest.json` (id → status/file/title/date/duration/error),
  a `failures.json`, a console summary, and a non-zero exit code when hard failures occur.

## Requirements

- **Python 3.11+**
- **ffmpeg** (and `ffprobe`, which ships with ffmpeg) on your `PATH`, or passed
  via `--ffmpeg-location`. Required for audio extraction, metadata, and thumbnail
  embedding.

### Installing ffmpeg

**Windows**

```powershell
winget install Gyan.FFmpeg
# or: choco install ffmpeg   /   scoop install ffmpeg
```

Or download a build from <https://www.gyan.dev/ffmpeg/builds/>, unzip it, and
either add its `bin\` folder to your `PATH` or pass
`--ffmpeg-location "C:\path\to\ffmpeg\bin"`.

**macOS**

```bash
brew install ffmpeg
```

**Linux**

```bash
# Debian/Ubuntu
sudo apt install ffmpeg
# Fedora
sudo dnf install ffmpeg
# Arch
sudo pacman -S ffmpeg
```

## Installing ytmp3dl

From a checkout of this repository:

```bash
python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS/Linux:    source .venv/bin/activate
pip install -e .
```

For development (tests + linter):

```bash
pip install -e ".[dev]"
```

This installs the `ytmp3dl` console command (and `python -m ytmp3dl` works too).

## Usage

Download every regular video from a channel as 320 kbps MP3 into `./downloads`:

```bash
ytmp3dl https://www.youtube.com/@PapaPedroBeats
```

Grab just the latest upload (handy first smoke test):

```bash
ytmp3dl https://www.youtube.com/@PapaPedroBeats --limit 1
```

Preview what would be downloaded without downloading anything:

```bash
ytmp3dl https://www.youtube.com/@PapaPedroBeats --dry-run
ytmp3dl https://www.youtube.com/@PapaPedroBeats --list
```

More examples:

```bash
# A different format/quality, into a chosen folder
ytmp3dl @SomeChannel --audio-format m4a --audio-quality 256K -o ~/Music/SomeChannel

# Include Shorts and past live streams as well
ytmp3dl @SomeChannel --include-shorts --include-streams

# Only videos uploaded in 2024, politely rate-limited
ytmp3dl @SomeChannel --dateafter 20240101 --datebefore 20241231 --rate-limit 1M

# Age/region-restricted content using browser cookies
ytmp3dl @SomeChannel --cookies-from-browser firefox
```

Accepted channel references: `@handle`, a bare handle (`SomeChannel`), full URLs
with or without a tab (`/videos`, `/shorts`, `/streams`), `/channel/<id>`,
`/c/<name>`, and legacy `/user/<name>`.

### Output layout

By default files are written as:

```
downloads/<Uploader>/<YYYY-MM-DD> - <Title> [<videoId>].mp3
```

alongside `downloads/.ytmp3dl-archive.txt` (the resume archive),
`downloads/manifest.json`, and `downloads/failures.json` (only when something failed).

## Configuration file

Any option can be set in a TOML file and pointed at with `--config`. Precedence
is **built-in defaults → config file → command-line flags** (CLI wins).

```toml
# ytmp3dl.toml
[ytmp3dl]
output_dir     = "/home/me/Music/yt"
audio_format   = "mp3"
audio_quality  = "320K"
include_shorts = false
concurrency    = 1
sleep_min      = 1.0
sleep_max      = 5.0
retries        = 2
```

```bash
ytmp3dl @SomeChannel --config ./ytmp3dl.toml
```

(The `[ytmp3dl]` table wrapper is optional; top-level keys work too.)

## Options

Run `ytmp3dl --help` for the full list. Highlights:

| Flag | Purpose |
|---|---|
| `-o, --output-dir` | Output directory (default `./downloads`). |
| `--audio-format` | `mp3` (default), `m4a`, `opus`, `flac`, `wav`, `best`. |
| `--audio-quality` | e.g. `320K` (default). |
| `--keep-original` | Keep the source file alongside the transcoded audio. |
| `--include-shorts` / `--include-streams` | Widen content scope. |
| `--videos-only` | Force just the `/videos` tab. |
| `--limit N` | Cap the number of videos. |
| `--dateafter` / `--datebefore` | Date-range filter (`YYYYMMDD`). |
| `--playlist-items` | `yt-dlp` item selection, e.g. `1-10,15`. |
| `--archive` / `--no-archive` | Resume archive path / disable resume. |
| `--no-embed-metadata` / `--no-embed-thumbnail` | Disable embedding. |
| `--concurrency N` | Parallel downloads (default `1`). |
| `--sleep-min` / `--sleep-max` / `--rate-limit` | Politeness throttling. |
| `--retries N` | Outer per-video retries (default `2`). |
| `--cookies-from-browser` / `--cookies` | Authentication. |
| `--config` | TOML config file. |
| `--ffmpeg-location` | Path to ffmpeg/ffprobe. |
| `--dry-run` / `--list` | Preview without downloading. |
| `--log-file` / `--verbose` / `--quiet` | Logging. |

## Development

```bash
pip install -e ".[dev]"
python -m pytest -q       # mock-based; no network or ffmpeg required
ruff check .
```

A live integration test (`tests/test_integration_live.py`) is **skipped unless**
`YTMP3DL_LIVE=1` is set, since it hits the real network.

## Responsible use

This tool downloads publicly available media. You are responsible for complying
with [YouTube's Terms of Service](https://www.youtube.com/t/terms) and applicable
copyright law — for example, personal/offline use of content you own or that is
appropriately licensed. It does not bypass paywalls, DRM, or age/region
restrictions beyond cookies you supply yourself.
