"""Generate 50-repo batched HTML reports from the full catalogue cache.

Reads catalogue_cache.json, sorts by stars descending, splits into 50-repo chunks,
and generates one HTML file per batch in transcripts/50-grouped_batches/.
"""

import json
from pathlib import Path

CACHE_FILE = Path("catalogue_cache.json")
OUTPUT_DIR = Path("transcripts/50-grouped_batches")
BATCH_SIZE = 50

# Relevance keywords for our workspace
WORKSPACE_KEYWORDS = [
    "automation", "report", "efficiency", "manufacturing", "dashboard",
    "analytics", "monitoring", "mcp", "agent", "ai", "llm", "claude",
    "self-hosted", "database", "visualization", "metrics", "extract",
    "script", "tool", "pipeline", "data", "analysis", "sync",
    "ocr", "pdf", "document", "email", "notification", "deploy"
]

def assess_relevance(repo):
    text = f"{repo.get('name','')} {repo.get('description','')} {' '.join(repo.get('topics',[]))} {repo.get('category','')}".lower()
    hits = [k for k in WORKSPACE_KEYWORDS if k in text]
    score = len(hits)
    if score >= 4:
        return "High", hits
    elif score >= 2:
        return "Medium", hits
    else:
        return "Low", hits

def build_batch_html(batch_num, total_batches, repos):
    """Build HTML table for one 50-repo batch."""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Batch {batch_num:03d} — Repos {(batch_num-1)*BATCH_SIZE+1}-{min(batch_num*BATCH_SIZE, len(repos)+(batch_num-1)*BATCH_SIZE)}</title>
<style>
:root {{ --bg:#0d1117; --card:#161b22; --text:#c9d1d9; --muted:#8b949e; --accent:#58a6ff; --border:#30363d; --high:#238636; --med:#9e6a03; --low:#8b949e; }}
body {{ font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background: var(--bg); color: var(--text); margin:0; padding:2rem; }}
h1 {{ text-align:center; margin-bottom:.5rem; }}
h2 {{ text-align:center; color:var(--muted); font-size:.9rem; font-weight:normal; margin-bottom:2rem; }}
.nav {{ text-align:center; margin-bottom:1.5rem; }}
.nav a {{ color:var(--accent); text-decoration:none; margin:0 .5rem; padding:.3rem .8rem; border:1px solid var(--border); border-radius:4px; font-size:.8rem; }}
.nav a:hover {{ background:var(--card); }}
table {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
th {{ text-align:left; padding:.6rem .8rem; border-bottom:1px solid var(--border); color:var(--accent); font-size:.8rem; text-transform:uppercase; position:sticky; top:0; background:var(--bg); }}
td {{ padding:.6rem .8rem; border-bottom:1px solid var(--border); vertical-align:top; }}
tr:hover td {{ background:#1c2128; }}
.rank {{ font-weight:bold; color:var(--accent); font-size:1.1rem; width:40px; }}
.stars {{ color:#e3b341; font-weight:bold; white-space:nowrap; }}
.name a {{ color:var(--accent); text-decoration:none; font-weight:bold; }}
.name a:hover {{ text-decoration:underline; }}
.lang {{ color:var(--muted); font-size:.75rem; }}
.desc {{ color:var(--muted); max-width:400px; }}
.rel-high {{ color:#3fb950; font-weight:bold; }}
.rel-med {{ color:#d29922; }}
.rel-low {{ color:var(--muted); }}
.tag {{ display:inline-block; background:#21262d; padding:1px 6px; border-radius:10px; font-size:.65rem; margin:1px 2px; color:var(--muted); }}
.source {{ font-size:.7rem; color:var(--muted); font-style:italic; }}
</style>
</head>
<body>
<h1>Batch {batch_num:03d} of {total_batches:03d}</h1>
<h2>Repos {(batch_num-1)*BATCH_SIZE+1}–{min(batch_num*BATCH_SIZE, (batch_num-1)*BATCH_SIZE+len(repos))} | Sorted by ⭐ Stars</h2>
<div class="nav">
{'<a href="batch_{:03d}.html">&larr; Prev</a>'.format(batch_num-1) if batch_num > 1 else '<span style="color:var(--muted)">&larr; Prev</span>'}
{'<a href="batch_{:03d}.html">Next &rarr;</a>'.format(batch_num+1) if batch_num < total_batches else '<span style="color:var(--muted)">Next &rarr;</span>'}
<a href="../catalogue.html">Full Catalogue</a>
</div>
<table>
<thead>
<tr><th>#</th><th>Repo</th><th>Stars</th><th>Lang</th><th>Category</th><th>Relevance</th><th>Description</th></tr>
</thead>
<tbody>
"""
    for i, r in enumerate(repos, 1):
        global_rank = (batch_num - 1) * BATCH_SIZE + i
        rel, hits = assess_relevance(r)
        rel_class = f"rel-{rel.lower()}"
        hits_str = ', '.join(hits[:4]) if hits else '-'
        topics_html = ''.join(f'<span class="tag">{t}</span>' for t in r.get('topics', [])[:5])
        desc = (r.get('description', '') or '')[:120]
        html += f"""<tr>
<td class="rank">{global_rank}</td>
<td class="name"><a href="{r['url']}" target="_blank">{r['name']}</a><br>{topics_html}</td>
<td class="stars">{r.get('stars',0):,}</td>
<td class="lang">{r.get('language','-') or '-'}</td>
<td>{r.get('category','?')}</td>
<td class="{rel_class}">{rel}<br><span style="font-size:.7rem">{hits_str}</span></td>
<td class="desc">{desc}</td>
</tr>
"""

    html += f"""</tbody>
</table>
<p style="text-align:center; color:var(--muted); margin-top:2rem; font-size:.8rem;">
Generated from 2,218 repos extracted from YouTube playlist transcripts.<br>
Relevance assessed against workspace focus: automation, reporting, efficiency, dashboards, analytics, AI/LLM tooling, data pipelines.
</p>
</body>
</html>"""
    return html

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(CACHE_FILE, encoding='utf-8') as f:
        cache = json.load(f)

    repos = []
    for url, info in cache.items():
        info['url'] = url
        repos.append(info)

    # Sort by stars descending
    repos.sort(key=lambda x: x.get('stars', 0), reverse=True)

    total = len(repos)
    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

    print(f"Total repos: {total}")
    print(f"Batches of {BATCH_SIZE}: {total_batches}")
    print(f"Output dir: {OUTPUT_DIR.resolve()}")
    print()

    for batch_num in range(1, total_batches + 1):
        start = (batch_num - 1) * BATCH_SIZE
        end = min(batch_num * BATCH_SIZE, total)
        batch = repos[start:end]

        html = build_batch_html(batch_num, total_batches, batch)
        out_path = OUTPUT_DIR / f"batch_{batch_num:03d}.html"
        out_path.write_text(html, encoding='utf-8')

        print(f"[{batch_num:03d}/{total_batches:03d}] batch_{batch_num:03d}.html — repos {start+1}-{end}")

    print(f"\nDone. {total_batches} batch files written to {OUTPUT_DIR.resolve()}")

if __name__ == "__main__":
    main()
