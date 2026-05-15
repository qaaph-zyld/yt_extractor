#!/usr/bin/env python3
"""Extract YouTube playlist transcripts and save as Markdown files."""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Playlist URL
PLAYLIST_URL = "https://www.youtube.com/watch?v=6Tcg8MjnBi0&list=PLI99ObbYUvDn_0tkbXsOYB4ApTyHFQxSi"
OUTPUT_DIR = Path("d:/Project/YT_Playlist_app/Transcripts")


def sanitize_filename(title):
    """Sanitize a video title for use as a filename."""
    if not title:
        title = "Unknown"
    title = re.sub(r'[\\/*?"<>|:]', "_", title)
    title = re.sub(r"\s+", "_", title)
    return title[:100]


def get_playlist_videos():
    """Get all video IDs, titles, and descriptions from the playlist using yt-dlp."""
    import subprocess

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--flat-playlist",
        "--dump-single-json",
        PLAYLIST_URL,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"yt-dlp error: {result.stderr}")
        return []

    data = json.loads(result.stdout)
    entries = data.get("entries", [])
    videos = []
    for entry in entries:
        videos.append({
            "id": entry.get("id"),
            "title": entry.get("title", "Unknown"),
            "url": f"https://www.youtube.com/watch?v={entry.get('id')}",
            "description": entry.get("description", ""),
        })
    return videos


def fetch_video_metadata(video_id):
    """Fetch video metadata including description using yt-dlp."""
    import subprocess
    import json
    try:
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--dump-single-json",
            "--skip-download",
            f"https://www.youtube.com/watch?v={video_id}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"  Metadata fetch failed: {result.stderr[:100]}")
            return {"description": "Description unavailable"}
        
        data = json.loads(result.stdout)
        desc = data.get("description", "No description available")
        if desc:
            print(f"  Description: {desc[:50]}...")
        return {
            "description": desc
        }
    except Exception as e:
        print(f"  Metadata error: {e}")
        return {"description": f"Description unavailable: {e}"}

def fetch_transcript(video_id):
    """Fetch transcript using yt-dlp SRT download."""
    import subprocess
    try:
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--write-auto-sub",
            "--skip-download",
            "--sub-lang", "en",
            "--sub-format", "srt",
            "--output", f"{video_id}",
            f"https://www.youtube.com/watch?v={video_id}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(OUTPUT_DIR))
        if result.returncode != 0:
            return f"[Transcript unavailable: yt-dlp error]"
        
        # Read the downloaded SRT file
        srt_file = OUTPUT_DIR / f"{video_id}.en.srt"
        if srt_file.exists():
            content = srt_file.read_text(encoding="utf-8", errors="ignore")
            srt_file.unlink()  # Clean up
            # Simple SRT to text conversion (remove timestamps and numbers)
            lines = []
            for line in content.split("\n"):
                if line.strip() and not "-->" in line and not line.strip().isdigit():
                    lines.append(line.strip())
            return "\n".join(lines)
        return f"[Transcript unavailable: no subtitle file]"
    except Exception as e:
        return f"[Transcript unavailable: {e}]"


def save_transcript(video, transcript_text):
    """Save transcript as a Markdown file."""
    safe_title = sanitize_filename(video["title"])
    filename = f"{safe_title}.md"
    filepath = OUTPUT_DIR / filename

    content = f"""# {video['title']}

**URL:** {video['url']}
**Video ID:** {video['id']}
**Extracted:** {datetime.now().isoformat()}

---

{transcript_text}

---

## Video Description

{video.get('description', 'No description available')}
"""
    filepath.write_text(content, encoding="utf-8")
    return filepath


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching playlist videos...")
    videos = get_playlist_videos()
    print(f"Found {len(videos)} videos.")

    for i, video in enumerate(videos, 1):
        title_display = video.get("title", "Unknown")[:60] if video.get("title") else "Unknown"
        print(f"[{i}/{len(videos)}] {title_display}...")
        
        # Fetch transcript
        transcript = fetch_transcript(video["id"])
        
        # Fetch video description
        metadata = fetch_video_metadata(video["id"])
        video["description"] = metadata["description"]
        
        save_transcript(video, transcript)

    # Create an index file
    index_path = OUTPUT_DIR / "_index.md"
    lines = ["# Playlist Transcripts\n", f"**Playlist:** {PLAYLIST_URL}\n", f"**Total videos:** {len(videos)}\n", "---\n"]
    for v in videos:
        safe = sanitize_filename(v["title"])
        lines.append(f"- [{v['title']}]({safe}.md) — {v['url']}\n")
    index_path.write_text("".join(lines), encoding="utf-8")

    print(f"\nDone. Saved {len(videos)} transcripts to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
