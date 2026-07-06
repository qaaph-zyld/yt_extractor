import json
from pathlib import Path

with open('catalogue_cache.json') as f:
    cache = json.load(f)

repos = []
for url, info in cache.items():
    info['url'] = url
    repos.append(info)

repos.sort(key=lambda x: x.get('stars', 0), reverse=True)
top50 = repos[:50]

# Relevance keywords for our workspace
workspace_keywords = [
    "automation", "report", "efficiency", "manufacturing", "dashboard",
    "analytics", "monitoring", "mcp", "agent", "ai", "llm", "claude",
    "self-hosted", "database", "visualization", "metrics", "extract",
    "script", "tool", "pipeline", "data", "analysis", "sync",
    "ocr", "pdf", "document", "email", "notification", "deploy"
]

def assess_relevance(repo):
    text = f"{repo.get('name','')} {repo.get('description','')} {' '.join(repo.get('topics',[]))} {repo.get('category','')}".lower()
    hits = [k for k in workspace_keywords if k in text]
    score = len(hits)
    if score >= 4:
        return "High", hits
    elif score >= 2:
        return "Medium", hits
    else:
        return "Low", hits

# Print text list
print("=" * 80)
print("TOP 50 REPOS BY STARS")
print("=" * 80)
for i, r in enumerate(top50, 1):
    rel, hits = assess_relevance(r)
    desc = (r.get('description','')[:70] or '').encode('ascii','ignore').decode('ascii')
    print(f"{i:2}. {r['name']:<40} {r.get('stars',0):>7,}*  [{rel:6}]  {r.get('category','?')[:20]}")
    print(f"     {desc}...")
    print()

# Generate focused HTML
html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Top 50 GitHub Repos - Ranked by Stars</title>
<style>
:root { --bg:#0d1117; --card:#161b22; --text:#c9d1d9; --muted:#8b949e; --accent:#58a6ff; --border:#30363d; --high:#238636; --med:#9e6a03; --low:#8b949e; }
body { font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background: var(--bg); color: var(--text); margin:0; padding:2rem; }
h1 { text-align:center; margin-bottom:.5rem; }
h2 { text-align:center; color:var(--muted); font-size:.9rem; font-weight:normal; margin-bottom:2rem; }
table { width:100%; border-collapse:collapse; font-size:.85rem; }
th { text-align:left; padding:.6rem .8rem; border-bottom:1px solid var(--border); color:var(--accent); font-size:.8rem; text-transform:uppercase; position:sticky; top:0; background:var(--bg); }
td { padding:.6rem .8rem; border-bottom:1px solid var(--border); vertical-align:top; }
tr:hover td { background:#1c2128; }
.rank { font-weight:bold; color:var(--accent); font-size:1.1rem; width:40px; }
.stars { color:#e3b341; font-weight:bold; white-space:nowrap; }
.name a { color:var(--accent); text-decoration:none; font-weight:bold; }
.name a:hover { text-decoration:underline; }
.lang { color:var(--muted); font-size:.75rem; }
.desc { color:var(--muted); max-width:400px; }
.rel-high { color:#3fb950; font-weight:bold; }
.rel-med { color:#d29922; }
.rel-low { color:var(--muted); }
.tag { display:inline-block; background:#21262d; padding:1px 6px; border-radius:10px; font-size:.65rem; margin:1px 2px; color:var(--muted); }
.source { font-size:.7rem; color:var(--muted); font-style:italic; }
</style>
</head>
<body>
<h1>Top 50 GitHub Repos by Stars</h1>
<h2>From 2,218 repos across the playlist transcripts | Ranked &amp; Relevance-Assessed</h2>
<table>
<thead>
<tr><th>#</th><th>Repo</th><th>⭐ Stars</th><th>Lang</th><th>Category</th><th>Relevance</th><th>Description</th></tr>
</thead>
<tbody>
"""

for i, r in enumerate(top50, 1):
    rel, hits = assess_relevance(r)
    rel_class = f"rel-{rel.lower()}"
    hits_str = ', '.join(hits[:4]) if hits else '-'
    topics_html = ''.join(f'<span class="tag">{t}</span>' for t in r.get('topics', [])[:5])
    html += f"""<tr>
<td class="rank">{i}</td>
<td class="name"><a href="{r['url']}" target="_blank">{r['name']}</a><br>{topics_html}</td>
<td class="stars">{r.get('stars',0):,}</td>
<td class="lang">{r.get('language','-') or '-'}</td>
<td>{r.get('category','?')}</td>
<td class="{rel_class}">{rel}<br><span style="font-size:.7rem">{hits_str}</span></td>
<td class="desc">{r.get('description','')[:120]}</td>
</tr>
"""

html += """</tbody>
</table>
<p style="text-align:center; color:var(--muted); margin-top:2rem; font-size:.8rem;">
Relevance assessed against workspace focus: automation, reporting, efficiency, manufacturing, dashboards, analytics, AI/LLM tooling, data pipelines.<br>
Generated from YouTube playlist transcripts via build_catalogue.py
</p>
</body>
</html>"""

Path('top50.html').write_text(html, encoding='utf-8')
print(f"\nSaved top50.html with {len(top50)} repos.")
