#!/usr/bin/env python3
"""Extract YouTube playlist transcripts and save as Markdown files."""

import json
import re
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import requests

# Disable SSL verification for corporate proxy / SSL inspection
class NoVerifySession(requests.Session):
    def __init__(self):
        super().__init__()
        self.verify = False

requests.Session = NoVerifySession
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

# Playlist URL
PLAYLIST_URL = "https://www.youtube.com/watch?v=6Tcg8MjnBi0&list=PLI99ObbYUvDn_0tkbXsOYB4ApTyHFQxSi"
OUTPUT_DIR = Path("transcripts")

# Load API key from .env
ENV_PATH = Path("../../.env")
YOUTUBE_API_KEY = None
for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
    if "youtube data api v3 key" in line.lower():
        YOUTUBE_API_KEY = line.split(":", 1)[-1].strip().strip("'\"")
        break

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


def sanitize_filename(title):
    """Sanitize a video title for use as a filename."""
    if not title:
        title = "Unknown"
    title = re.sub(r'[\\/*?"<>|:]', "_", title)
    title = re.sub(r"\s+", "_", title)
    return title[:100]


def get_playlist_videos():
    """Get all video IDs, titles from the playlist using yt-dlp."""
    import subprocess

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-check-certificate",
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
            "description": "",
        })
    return videos


def fetch_playlist_items_api(playlist_id):
    """Fetch all video IDs from playlist using YouTube Data API v3."""
    videos = []
    page_token = ""
    while True:
        url = f"{YOUTUBE_API_BASE}/playlistItems"
        params = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": 50,
            "pageToken": page_token,
            "key": YOUTUBE_API_KEY,
        }
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            vid = snippet.get("resourceId", {}).get("videoId")
            if vid:
                videos.append({
                    "id": vid,
                    "title": snippet.get("title", "Unknown"),
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "description": snippet.get("description", ""),
                })
        page_token = data.get("nextPageToken", "")
        if not page_token:
            break
    return videos


def fetch_videos_details_api(video_ids):
    """Fetch descriptions and metadata for a batch of video IDs."""
    url = f"{YOUTUBE_API_BASE}/videos"
    params = {
        "part": "snippet",
        "id": ",".join(video_ids),
        "key": YOUTUBE_API_KEY,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    details = {}
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        details[item["id"]] = snippet.get("description", "")
    return details


def extract_github_links(text):
    """Extract GitHub repo URLs from description text."""
    if not text:
        return []
    # Match github.com/username/repo patterns, including optional http(s)://
    pattern = r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
    return list(set(re.findall(pattern, text)))


def fetch_video_metadata(video_id):
    """Fetch video metadata using YouTube Data API v3."""
    try:
        url = f"{YOUTUBE_API_BASE}/videos"
        params = {
            "part": "snippet",
            "id": video_id,
            "key": YOUTUBE_API_KEY,
        }
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        if not items:
            return {"description": "Description unavailable"}
        desc = items[0].get("snippet", {}).get("description", "No description available")
        if desc:
            print(f"  Description: {desc[:50]}...")
        return {"description": desc}
    except Exception as e:
        print(f"  Metadata error: {e}")
        return {"description": f"Description unavailable: {e}"}

def fetch_transcript(video_id):
    """Fetch transcript using youtube-transcript-api."""
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id, languages=["en"])
        lines = [snippet.text for snippet in transcript]
        return "\n".join(lines)
    except TranscriptsDisabled:
        return "[Transcript unavailable: transcripts disabled for this video]"
    except NoTranscriptFound:
        return "[Transcript unavailable: no English transcript found]"
    except Exception as e:
        return f"[Transcript unavailable: {e}]"


def save_transcript(video, transcript_text):
    """Save transcript as a Markdown file."""
    safe_title = sanitize_filename(video["title"])
    filename = f"{safe_title}.md"
    filepath = OUTPUT_DIR / filename

    github_links = extract_github_links(video.get("description", ""))
    github_section = "\n## GitHub Links\n\n"
    if github_links:
        for link in github_links:
            github_section += f"- {link}\n"
    else:
        github_section += "No GitHub links found in description.\n"

    content = f"""# {video['title']}

**URL:** {video['url']}
**Video ID:** {video['id']}
**Extracted:** {datetime.now().isoformat()}

---

{transcript_text}

---

## Video Description

{video.get('description', 'No description available')}
{github_section}"""
    filepath.write_text(content, encoding="utf-8")
    return filepath


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching playlist videos...")
    videos = get_playlist_videos()
    print(f"Found {len(videos)} videos.")

    # Batch fetch descriptions via API
    print("Fetching descriptions via YouTube Data API...")
    all_ids = [v["id"] for v in videos]
    descriptions = {}
    for batch_start in range(0, len(all_ids), 50):
        batch = all_ids[batch_start:batch_start + 50]
        batch_descs = fetch_videos_details_api(batch)
        descriptions.update(batch_descs)
        time.sleep(0.5)

    for i, video in enumerate(videos, 1):
        title_display = video.get("title", "Unknown")[:60] if video.get("title") else "Unknown"
        print(f"[{i}/{len(videos)}] {title_display}...")
        
        # Attach description from API
        video["description"] = descriptions.get(video["id"], "")
        
        # Fetch transcript
        transcript = fetch_transcript(video["id"])
        if transcript.startswith("[Transcript unavailable"):
            print(f"  {transcript}")
        
        save_transcript(video, transcript)
        time.sleep(1)  # Be polite to APIs

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
