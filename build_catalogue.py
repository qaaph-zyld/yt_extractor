#!/usr/bin/env python3
"""Parse transcripts, fetch GitHub metadata, and build an HTML catalogue.

Only extracts repos from the ## GitHub Links section of each transcript MD.
Uses a local cache (catalogue_cache.json) to resume after rate limits.
"""

import json
import re
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests

# Disable SSL verification for corporate proxy
class NoVerifySession(requests.Session):
    def __init__(self):
        super().__init__()
        self.verify = False

requests.Session = NoVerifySession
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

ENV_PATH = Path("../../.env")
GITHUB_TOKEN = None
for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
    if "github" in line.lower() and "token" in line.lower():
        GITHUB_TOKEN = line.split(":", 1)[-1].strip().strip("'\"")
        break

# Rate-limit config
if GITHUB_TOKEN:
    print("GitHub token found — 5,000 req/hour limit.")
    DELAY = 0.8
else:
    print("No GitHub token — 60 req/hour limit. Consider adding 'github token: ...' to .env")
    DELAY = 62.0  # one per minute

TRANSCRIPTS_DIR = Path("transcripts")
OUTPUT_HTML = Path("catalogue.html")
CACHE_FILE = Path("catalogue_cache.json")

HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"


def extract_github_links_from_section(text):
    """Only grab links that appear under ## GitHub Links."""
    # Split on the GitHub Links heading and grab everything after it
    parts = re.split(r"##\s*GitHub\s*Links", text, flags=re.IGNORECASE)
    if len(parts) < 2:
        return []
    section = parts[-1]
    # Stop at the next markdown heading (if any)
    section = re.split(r"\n##", section)[0]
    pattern = r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
    return sorted(set(re.findall(pattern, section)))


def parse_repo_slug(url):
    parts = url.replace("https://github.com/", "").split("/")
    return parts[0], parts[1]


def fetch_github_metadata(owner, repo):
    url = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 404 or resp.status_code == 451:
            return {"__missing": True}
        if resp.status_code == 403:
            print(f"  ⚠ Rate limited on {owner}/{repo}. Save cache and retry later.")
            return None
        resp.raise_for_status()
        data = resp.json()
        return {
            "stars": data.get("stargazers_count", 0),
            "language": data.get("language", "Unknown"),
            "topics": data.get("topics", []),
            "description": data.get("description", ""),
            "html_url": data.get("html_url", ""),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "archived": data.get("archived", False),
        }
    except Exception as e:
        print(f"  Error fetching {owner}/{repo}: {e}")
        return {"__missing": True}


def infer_category(repo_info):
    name = repo_info.get("name", "").lower()
    desc = (repo_info.get("description") or "").lower()
    topics = [t.lower() for t in repo_info.get("topics", [])]
    all_text = f"{name} {desc} {' '.join(topics)}"

    if any(k in all_text for k in ["claude", "cursor", "skill", "mcp", "prompt", "agentic", "ai-agent"]):
        return "AI Agent Skills & MCP"
    if any(k in all_text for k in ["llm", "gpt", "transformer", "model", "ollama", "inference", "quantization"]):
        return "LLMs & Foundation Models"
    if any(k in all_text for k in ["web", "frontend", "react", "vue", "angular", "ui", "css"]):
        return "Web & Frontend"
    if any(k in all_text for k in ["mobile", "android", "ios", "flutter", "react-native"]):
        return "Mobile"
    if any(k in all_text for k in ["data", "etl", "pipeline", "analytics", "sql", "database", "scraping"]):
        return "Data & Automation"
    if any(k in all_text for k in ["devops", "docker", "kubernetes", "ci/cd", "deployment", "infra"]):
        return "DevOps & Infra"
    if any(k in all_text for k in ["cli", "terminal", "tool", "utility", "productivity", "workflow"]):
        return "Developer Tools"
    if any(k in all_text for k in ["finance", "trading", "hedge", "crypto", "stock", "investment"]):
        return "Finance & Trading"
    if any(k in all_text for k in ["game", "gaming", "unity", "unreal", "engine"]):
        return "Gaming & Graphics"
    if any(k in all_text for k in ["video", "image", "media", "audio", "synthesis", "generation"]):
        return "Media & Generative AI"
    return "General / Other"


def build_html(repos):
    categories = {}
    for repo in repos:
        cat = repo.get("category", "Unknown")
        categories.setdefault(cat, []).append(repo)
    for cat in categories:
        categories[cat].sort(key=lambda r: r.get("stars", 0), reverse=True)
    sorted_cats = sorted(categories.items())

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GitHub Trending Catalogue</title>
<style>
:root {{ --bg:#0d1117; --card:#161b22; --text:#c9d1d9; --muted:#8b949e; --accent:#58a6ff; --border:#30363d; }}
body {{ font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background: var(--bg); color: var(--text); margin:0; padding:2rem; }}
h1 {{ text-align:center; margin-bottom:.5rem; }}
.stats {{ text-align:center; color:var(--muted); margin-bottom:2rem; font-size:.9rem; }}
.category {{ margin-bottom:2.5rem; }}
.category h2 {{ border-bottom:1px solid var(--border); padding-bottom:.5rem; margin-bottom:1rem; color:var(--accent); }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:1rem; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:8px; padding:1rem; transition:transform .15s; }}
.card:hover {{ transform:translateY(-2px); border-color:var(--accent); }}
.card h3 {{ margin:0 0 .4rem 0; font-size:1rem; }}
.card h3 a {{ color:var(--accent); text-decoration:none; }}
.card h3 a:hover {{ text-decoration:underline; }}
.meta {{ font-size:.8rem; color:var(--muted); margin-bottom:.5rem; }}
.meta span {{ margin-right:.75rem; }}
.topics {{ margin:.4rem 0; }}
.tag {{ display:inline-block; background:#21262d; color:var(--muted); padding:2px 8px; border-radius:12px; font-size:.7rem; margin:2px 4px 2px 0; }}
.desc {{ font-size:.85rem; line-height:1.4; margin-top:.5rem; }}
.source {{ font-size:.75rem; color:var(--muted); margin-top:.6rem; font-style:italic; }}
</style>
</head>
<body>
<h1>GitHub Trending Catalogue</h1>
<p class="stats">Generated: {datetime.now().isoformat()} | Repos: {len(repos)} | Categories: {len(sorted_cats)}</p>
"""

    for cat_name, cat_repos in sorted_cats:
        html += f'<div class="category">\n<h2>{cat_name} ({len(cat_repos)})</h2>\n<div class="grid">\n'
        for r in cat_repos:
            topics_html = "".join(f'<span class="tag">{t}</span>' for t in r.get("topics", [])[:6])
            html += f"""
<div class="card">
  <h3><a href="{r['url']}" target="_blank">{r['name']}</a></h3>
  <div class="meta">
    <span>⭐ {r.get('stars',0):,}</span>
    <span>Lang: {r.get('language','N/A')}</span>
    {'<span style="color:#f85149">Archived</span>' if r.get('archived') else ''}
  </div>
  <div class="topics">{topics_html}</div>
  <div class="desc">{r.get('description','') or 'No description available.'}</div>
  <div class="source">From: {r.get('source_video','Unknown')}</div>
</div>
"""
        html += "</div>\n</div>\n"
    html += "</body>\n</html>"
    return html


def main():
    # Load cache
    cache = {}
    if CACHE_FILE.exists():
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        print(f"Loaded {len(cache)} cached repos.")

    print("Scanning transcripts for GitHub links...")
    all_repos = {}

    for md_file in TRANSCRIPTS_DIR.glob("*.md"):
        if md_file.name == "_index.md":
            continue
        content = md_file.read_text(encoding="utf-8")
        title_match = re.search(r"^# (.+)$", content, re.MULTILINE)
        video_title = title_match.group(1) if title_match else md_file.stem

        links = extract_github_links_from_section(content)
        for url in links:
            if url not in all_repos:
                all_repos[url] = {"name": url.split("/")[-1], "url": url, "source_video": video_title}
            elif video_title not in all_repos[url]["source_video"]:
                all_repos[url]["source_video"] += f", {video_title}"

    print(f"Found {len(all_repos)} unique repos from ## GitHub Links sections.")

    pending = {url: info for url, info in all_repos.items() if url not in cache}
    print(f"Resuming: {len(cache)} cached, {len(pending)} pending.")

    repos = []
    rate_limited = False
    for i, (url, info) in enumerate(pending.items(), 1):
        owner, repo_name = parse_repo_slug(url)
        print(f"[{i}/{len(pending)}] {owner}/{repo_name}...")
        meta = fetch_github_metadata(owner, repo_name)
        if meta is None:
            print(f"\n⚠ Rate limited. Saving cache with {len(cache)} entries. Resume later.")
            rate_limited = True
            break
        info.update(meta)
        info["name"] = repo_name
        if meta.get("__missing"):
            info["category"] = "Not Found"
        else:
            info["category"] = infer_category({"name": repo_name, **meta})
        cache[url] = info
        repos.append(info)
        time.sleep(0.8)

    # Merge cached + newly fetched
    for url, info in cache.items():
        if url not in {r["url"] for r in repos}:
            repos.append(info)

    # Save final cache
    CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")

    print("\nBuilding HTML catalogue...")
    html = build_html(repos)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"Saved to {OUTPUT_HTML.resolve()}")
    print(f"Total repos: {len(repos)} | Categories: {len(set(r['category'] for r in repos))}")


if __name__ == "__main__":
    main()
