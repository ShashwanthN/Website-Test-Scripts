#!/usr/bin/env python3
"""
Social Preview Scraper
Crawls all URLs using lynx, extracts OG/Twitter card metadata,
and generates a rich HTML report.
"""

import subprocess
import sys
import re
import urllib.request
import urllib.parse
import urllib.error
from html.parser import HTMLParser
from datetime import datetime
import os
import time
import json

# ─── Configuration ───────────────────────────────────────────────────────────
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

try:
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)
except Exception as e:
    print(f"Error loading config.json: {e}")
    sys.exit(1)

START_URL   = config.get("start_url", "https://example.com/")
OUTPUT_FILE = config.get("social_preview_scraper", {}).get("output_file", "social_previews_report.html")
MAX_URLS    = config.get("max_pages_crawled", 300)
DELAY_SEC   = config.get("delay_seconds_between_requests", 0.5)
TIMEOUT_SEC = config.get("request_timeout_seconds", 15)
# ─────────────────────────────────────────────────────────────────────────────


class MetaParser(HTMLParser):
    """Lightweight HTML parser that extracts social-preview relevant tags."""

    def __init__(self):
        super().__init__()
        self.data = {
            "title": "",
            "og:title": "",
            "og:description": "",
            "og:image": "",
            "og:url": "",
            "og:type": "",
            "og:site_name": "",
            "twitter:title": "",
            "twitter:description": "",
            "twitter:image": "",
            "twitter:card": "",
            "description": "",
        }
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            prop    = attrs.get("property", "").lower()
            name    = attrs.get("name", "").lower()
            content = attrs.get("content", "")
            if prop in self.data:
                self.data[prop] = content
            if name in self.data:
                self.data[name] = content

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and not self.data["title"]:
            self.data["title"] = data.strip()


def get_all_links_via_lynx(url: str) -> list[str]:
    """Use lynx -dump to extract all hyperlinks from a page."""
    try:
        result = subprocess.run(
            ["lynx", "-dump", "-listonly", "-nonumbers", url],
            capture_output=True, text=True, timeout=30
        )
        lines = result.stdout.strip().splitlines()
        links = []
        for line in lines:
            line = line.strip()
            if line.startswith("http"):
                links.append(line)
        return links
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  [lynx error] {e}")
        return []


def crawl_site(start_url: str) -> list[str]:
    """BFS crawl using lynx to collect all internal URLs."""
    domain = urllib.parse.urlparse(start_url).netloc
    visited = set()
    queue   = [start_url]
    ordered = []

    print(f"\n🔍 Crawling {start_url} (domain: {domain})")
    print("─" * 60)

    while queue and len(visited) < MAX_URLS:
        url = queue.pop(0)
        # normalize: strip fragments & trailing slashes variations
        url = url.split("#")[0].rstrip("/") or url
        if url in visited:
            continue
        visited.add(url)
        ordered.append(url)

        parsed = urllib.parse.urlparse(url)
        if parsed.netloc and parsed.netloc != domain:
            continue  # external – don't follow

        print(f"  [{len(ordered):>3}] {url}")
        links = get_all_links_via_lynx(url)
        for link in links:
            link = link.split("#")[0].rstrip("/") or link
            p = urllib.parse.urlparse(link)
            # only follow same-domain http(s) links
            if p.scheme in ("http", "https") and p.netloc == domain:
                if link not in visited and link not in queue:
                    queue.append(link)
        time.sleep(DELAY_SEC)

    print(f"\n✅ Found {len(ordered)} unique URLs\n")
    return ordered


def fetch_meta(url: str) -> dict:
    """Fetch a URL and extract all social-preview metadata."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SocialPreviewBot/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            # only parse text/html
            ct = resp.headers.get_content_type()
            if "html" not in ct:
                return {"_error": f"Non-HTML content-type: {ct}"}
            raw = resp.read(500_000)  # cap at ~500 KB
            charset = resp.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        return {"_error": str(e.reason)}
    except Exception as e:
        return {"_error": str(e)}

    parser = MetaParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    return parser.data


def esc(s: str) -> str:
    """HTML-escape a string."""
    return (s or "").\
        replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def make_absolute(img_url: str, page_url: str) -> str:
    if not img_url:
        return ""
    if img_url.startswith("//"):
        return "https:" + img_url
    if img_url.startswith("http"):
        return img_url
    return urllib.parse.urljoin(page_url, img_url)


def build_html(results: list[dict]) -> str:
    rows_html = ""

    for i, r in enumerate(results, 1):
        url   = r["url"]
        meta  = r["meta"]
        err   = meta.get("_error", "")

        # Best values (OG > Twitter > plain)
        title = (meta.get("og:title") or meta.get("twitter:title") or meta.get("title") or "").strip()
        desc  = (meta.get("og:description") or meta.get("twitter:description") or meta.get("description") or "").strip()
        img   = make_absolute(
            (meta.get("og:image") or meta.get("twitter:image") or ""), url
        )
        og_url      = meta.get("og:url","")
        og_type     = meta.get("og:type","")
        og_sitename = meta.get("og:site_name","")
        tw_card     = meta.get("twitter:card","")

        # Preview card chip row
        chip_og  = f'<span class="chip chip-og">OG</span>'  if any([meta.get("og:title"),meta.get("og:description"),meta.get("og:image")]) else ""
        chip_tw  = f'<span class="chip chip-tw">Twitter</span>' if any([meta.get("twitter:title"),meta.get("twitter:card")]) else ""
        chip_err = f'<span class="chip chip-err">{esc(err)}</span>' if err else ""

        # Image cell
        if img:
            img_cell = f'<a href="{esc(img)}" target="_blank"><img src="{esc(img)}" class="preview-img" alt="OG image" loading="lazy" onerror="this.style.display=\'none\'"/></a>'
        else:
            img_cell = '<span class="no-img">No image</span>'

        # WhatsApp / iMessage / Slack / Telegram preview simulation
        sim_title = esc(title or url)
        sim_desc  = esc(desc[:200] + ("…" if len(desc)>200 else "")) if desc else ""
        sim_img   = f'<img src="{esc(img)}" class="sim-img" loading="lazy" onerror="this.style.display=\'none\'"/>' if img else ""

        preview_sim = f"""
        <div class="preview-sim">
          {sim_img}
          <div class="sim-text">
            <p class="sim-title">{sim_title}</p>
            {"<p class='sim-desc'>" + sim_desc + "</p>" if sim_desc else ""}
            <p class="sim-domain">{urllib.parse.urlparse(url).netloc}</p>
          </div>
        </div>"""

        # Meta details table
        meta_rows = ""
        meta_fields = [
            ("og:title",         meta.get("og:title","")),
            ("og:description",   meta.get("og:description","")),
            ("og:image",         meta.get("og:image","")),
            ("og:url",           og_url),
            ("og:type",          og_type),
            ("og:site_name",     og_sitename),
            ("twitter:card",     tw_card),
            ("twitter:title",    meta.get("twitter:title","")),
            ("twitter:description", meta.get("twitter:description","")),
            ("twitter:image",    meta.get("twitter:image","")),
            ("<title>",          meta.get("title","")),
            ("<meta description>", meta.get("description","")),
        ]
        for k, v in meta_fields:
            if v:
                meta_rows += f'<tr><td class="mk">{esc(k)}</td><td class="mv">{esc(v)}</td></tr>'

        status_class = "row-err" if err else ""

        rows_html += f"""
    <tr class="{status_class}">
      <td class="idx">{i}</td>
      <td class="url-cell"><a href="{esc(url)}" target="_blank">{esc(url)}</a><br/>{chip_og}{chip_tw}{chip_err}</td>
      <td>{img_cell}</td>
      <td class="title-cell">{esc(title) or '<span class="missing">—</span>'}</td>
      <td class="desc-cell">{esc(desc) or '<span class="missing">—</span>'}</td>
      <td>{preview_sim}</td>
      <td>
        {"<table class='meta-tbl'>" + meta_rows + "</table>" if meta_rows else '<span class="missing">No meta tags</span>'}
      </td>
    </tr>"""

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(results)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Social Preview Report</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --bg:       #0d0f14;
    --surface:  #151820;
    --card:     #1c2030;
    --border:   #2a2f45;
    --accent:   #6c63ff;
    --accent2:  #00d4ff;
    --green:    #22c55e;
    --red:      #ef4444;
    --amber:    #f59e0b;
    --text:     #e2e8f0;
    --muted:    #64748b;
    --radius:   10px;
  }}

  body {{
    font-family: 'Inter', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 0 0 60px;
  }}

  /* ── HEADER ── */
  .header {{
    background: linear-gradient(135deg, #1a1040 0%, #0d1830 50%, #0d2b1a 100%);
    padding: 48px 40px 36px;
    border-bottom: 1px solid var(--border);
    position: relative;
    overflow: hidden;
  }}
  .header::before {{
    content: '';
    position: absolute; inset: 0;
    background: radial-gradient(ellipse 60% 80% at 70% 50%, rgba(108,99,255,.15), transparent);
    pointer-events: none;
  }}
  .header h1 {{
    font-size: 2rem; font-weight: 700;
    background: linear-gradient(90deg, #fff 30%, var(--accent2));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
  }}
  .header p {{ color: var(--muted); margin-top: 6px; font-size: .95rem; }}
  .stats {{ display:flex; gap:24px; margin-top:28px; flex-wrap:wrap; }}
  .stat {{
    background: rgba(255,255,255,.04);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px 20px;
  }}
  .stat-n {{ font-size:1.6rem; font-weight:700; color:#fff; }}
  .stat-l {{ font-size:.75rem; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }}

  /* ── SEARCH ── */
  .toolbar {{ padding: 20px 40px; display:flex; gap:12px; align-items:center; }}
  #searchInput {{
    flex:1; background: var(--card); border:1px solid var(--border);
    border-radius: var(--radius); padding: 10px 16px; color:var(--text);
    font-size:.9rem; outline:none; transition: border-color .2s;
  }}
  #searchInput:focus {{ border-color: var(--accent); }}
  #searchInput::placeholder {{ color:var(--muted); }}

  /* ── TABLE ── */
  .table-wrap {{ overflow-x:auto; padding: 0 40px; }}
  table.main-tbl {{
    width:100%; border-collapse: separate; border-spacing: 0 6px;
    table-layout: auto;
  }}
  .main-tbl thead th {{
    background: var(--card);
    padding: 12px 14px;
    text-align: left;
    font-size:.72rem; font-weight:600; text-transform:uppercase; letter-spacing:.06em;
    color:var(--muted);
    position: sticky; top:0; z-index:10;
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
  }}
  .main-tbl thead th:first-child {{ border-radius: var(--radius) 0 0 var(--radius); }}
  .main-tbl thead th:last-child  {{ border-radius: 0 var(--radius) var(--radius) 0; }}
  .main-tbl tbody tr {{
    background: var(--card);
    transition: background .15s;
  }}
  .main-tbl tbody tr:hover {{ background: #212640; }}
  .main-tbl tbody tr.row-err {{ background: rgba(239,68,68,.07); }}
  .main-tbl td {{
    padding: 12px 14px;
    vertical-align: top;
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    font-size: .83rem;
  }}
  .main-tbl td:first-child {{ border-left:1px solid var(--border); border-radius: var(--radius) 0 0 var(--radius);}}
  .main-tbl td:last-child  {{ border-right:1px solid var(--border); border-radius: 0 var(--radius) var(--radius) 0;}}

  .idx {{ color:var(--muted); font-size:.8rem; min-width:32px; text-align:center; }}
  .url-cell a {{ color:var(--accent2); text-decoration:none; word-break:break-all; font-size:.8rem; }}
  .url-cell a:hover {{ text-decoration:underline; }}
  .title-cell {{ font-weight:500; min-width:160px; max-width:200px; }}
  .desc-cell  {{ color:var(--muted); min-width:200px; max-width:260px; font-size:.8rem; line-height:1.5; }}
  .missing {{ color: var(--muted); font-style:italic; }}

  /* chips */
  .chip {{ display:inline-block; font-size:.65rem; font-weight:600; border-radius:4px;
           padding:2px 6px; margin-top:5px; margin-right:3px; }}
  .chip-og  {{ background:rgba(108,99,255,.2); color:#a89fff; }}
  .chip-tw  {{ background:rgba(0,212,255,.15); color:#5de0f8; }}
  .chip-err {{ background:rgba(239,68,68,.2);  color:#fca5a5; }}

  /* preview image */
  .preview-img {{ width:120px; height:72px; object-fit:cover; border-radius:6px; border:1px solid var(--border); display:block; }}
  .no-img {{ color:var(--muted); font-size:.78rem; font-style:italic; }}

  /* preview simulation */
  .preview-sim {{
    border:1px solid var(--border); border-radius:8px; overflow:hidden;
    background: var(--surface); min-width:200px; max-width:260px;
  }}
  .sim-img {{ width:100%; height:100px; object-fit:cover; display:block; }}
  .sim-text {{ padding:8px 10px; }}
  .sim-title {{ font-weight:600; font-size:.82rem; color:#e2e8f0; line-height:1.3; }}
  .sim-desc  {{ color:var(--muted); font-size:.75rem; margin-top:3px; line-height:1.4; }}
  .sim-domain{{ color:var(--muted); font-size:.7rem; margin-top:4px; text-transform:uppercase; letter-spacing:.04em; }}

  /* meta mini table */
  .meta-tbl {{ border-collapse:collapse; width:100%; font-size:.75rem; min-width:280px; }}
  .meta-tbl td {{ padding:3px 0; vertical-align:top; border:none; background:transparent; }}
  .mk {{ color:var(--accent); white-space:nowrap; padding-right:10px; font-family:monospace; font-size:.72rem; }}
  .mv {{ color:var(--text); word-break:break-all; }}

  /* no-results */
  .no-results {{ text-align:center; padding:48px; color:var(--muted); display:none; font-size:1rem; }}

  /* scrollbar */
  ::-webkit-scrollbar {{ width:6px; height:6px; }}
  ::-webkit-scrollbar-track {{ background:var(--bg); }}
  ::-webkit-scrollbar-thumb {{ background:var(--border); border-radius:3px; }}
</style>
</head>
<body>

<div class="header">
  <h1>🔗 Social Preview Report</h1>
  <p>Site: <strong>{urllib.parse.urlparse(START_URL).netloc}</strong> &nbsp;·&nbsp; Generated: {now}</p>
  <div class="stats">
    <div class="stat"><div class="stat-n">{total}</div><div class="stat-l">Total URLs</div></div>
    <div class="stat" id="stat-og"><div class="stat-n">…</div><div class="stat-l">Have OG Tags</div></div>
    <div class="stat" id="stat-img"><div class="stat-n">…</div><div class="stat-l">Have OG Image</div></div>
    <div class="stat" id="stat-tw"><div class="stat-n">…</div><div class="stat-l">Twitter Cards</div></div>
    <div class="stat" id="stat-err"><div class="stat-n">…</div><div class="stat-l">Errors</div></div>
  </div>
</div>

<div class="toolbar">
  <input id="searchInput" type="search" placeholder="🔎  Filter by URL, title, or description…"/>
</div>

<div class="table-wrap">
<table class="main-tbl" id="mainTable">
  <thead>
    <tr>
      <th>#</th>
      <th>URL</th>
      <th>OG / Social Image</th>
      <th>Title</th>
      <th>Description</th>
      <th>Link Preview (Simulated)</th>
      <th>All Meta Tags</th>
    </tr>
  </thead>
  <tbody id="tableBody">
{rows_html}
  </tbody>
</table>
<p class="no-results" id="noResults">No matching results.</p>
</div>

<script>
// ── Live search ──
const input = document.getElementById('searchInput');
const rows  = Array.from(document.querySelectorAll('#tableBody tr'));
const noRes = document.getElementById('noResults');

input.addEventListener('input', () => {{
  const q = input.value.toLowerCase();
  let visible = 0;
  rows.forEach(r => {{
    const txt = r.textContent.toLowerCase();
    const show = !q || txt.includes(q);
    r.style.display = show ? '' : 'none';
    if(show) visible++;
  }});
  noRes.style.display = visible === 0 ? 'block' : 'none';
}});

// ── Stats ──
const og  = rows.filter(r => r.querySelector('.chip-og')).length;
const tw  = rows.filter(r => r.querySelector('.chip-tw')).length;
const img = rows.filter(r => r.querySelector('.preview-img')).length;
const err = rows.filter(r => r.classList.contains('row-err')).length;
document.getElementById('stat-og').querySelector('.stat-n').textContent  = og;
document.getElementById('stat-tw').querySelector('.stat-n').textContent  = tw;
document.getElementById('stat-img').querySelector('.stat-n').textContent = img;
document.getElementById('stat-err').querySelector('.stat-n').textContent = err;
</script>
</body>
</html>"""


def main():
    output_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(output_dir, OUTPUT_FILE)

    # Step 1: Crawl all URLs
    urls = crawl_site(START_URL)

    # Step 2: Fetch metadata for each URL
    results = []
    print("📦 Fetching social metadata for each URL…")
    print("─" * 60)
    for i, url in enumerate(urls, 1):
        print(f"  [{i:>3}/{len(urls)}] {url}", end="", flush=True)
        meta = fetch_meta(url)
        results.append({"url": url, "meta": meta})
        err = meta.get("_error", "")
        if err:
            print(f"  ⚠  {err}")
        else:
            found = []
            if meta.get("og:image"):         found.append("img")
            if meta.get("og:title"):         found.append("og:title")
            if meta.get("twitter:card"):     found.append("tw-card")
            print(f"  ✓  [{', '.join(found) or 'no OG/TW tags'}]")
        time.sleep(DELAY_SEC)

    # Step 3: Build HTML
    print(f"\n📝 Building HTML report → {output_path}")
    html = build_html(results)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ Done! Open: {output_path}")


if __name__ == "__main__":
    main()
