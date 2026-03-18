#!/usr/bin/env python3
"""
Dead Link Checker
Crawls all internal pages, extracts all outgoing links (a href and img src),
checks their status, and generates an HTML report of broken links per page.
"""

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

START_URL    = config.get("start_url", "https://example.com/")
OUTPUT_FILE  = config.get("dead_link_checker", {}).get("output_file", "dead_links_report.html")
MAX_PAGES    = config.get("max_pages_crawled", 300)
DELAY_SEC    = config.get("delay_seconds_between_requests", 0.2)
TIMEOUT_SEC  = config.get("request_timeout_seconds", 10)
IGNORE_URLS  = config.get("dead_link_checker", {}).get("ignore_urls", [])
# ─────────────────────────────────────────────────────────────────────────────

class LinkExtractor(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        url = None
        if tag == "a" and "href" in attrs_dict:
            url = attrs_dict["href"]
        elif tag == "img" and "src" in attrs_dict:
            url = attrs_dict["src"]
        
        if url:
            # Clean and make absolute
            url = url.strip()
            # Ignore mailto, tel, javascript, etc.
            if url.startswith(("mailto:", "tel:", "javascript:", "#")):
                return
            
            # Remove local page fragment identifiers
            url = url.split("#")[0]
            if not url:
                return

            abs_url = urllib.parse.urljoin(self.base_url, url)
            
            # Ignore configured URLs
            if any(ignored in abs_url for ignored in IGNORE_URLS):
                return
                
            # Ensure it's http/https
            if abs_url.startswith(("http://", "https://")):
                self.links.append(abs_url)


def check_url_status(url: str, user_agent: str = "Mozilla/5.0") -> dict:
    """Check the HTTP status of a URL. Returns a dict with 'status' and optionally 'error'."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent}, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            return {"status": resp.getcode(), "ok": True}
    except urllib.error.HTTPError as e:
        # Some servers don't like HEAD requests, try GET if 403/405
        if e.code in (403, 405, 503):
            req.method = "GET"
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                    return {"status": resp.getcode(), "ok": True}
            except urllib.error.HTTPError as e2:
                return {"status": e2.code, "ok": False, "error": f"HTTP {e2.code}"}
            except Exception as e2:
                return {"status": 0, "ok": False, "error": str(e2)}
        return {"status": e.code, "ok": False, "error": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        return {"status": 0, "ok": False, "error": str(e.reason)}
    except Exception as e:
        return {"status": 0, "ok": False, "error": str(e)}


def crawl_and_extract_links(start_url: str):
    """BFS crawl to find all pages and their links."""
    domain = urllib.parse.urlparse(start_url).netloc
    
    visited_pages = set()
    queue = [start_url]
    
    # Map: page_url -> list(unique_links_found_on_page)
    page_links_map = {}
    
    print(f"\n🔍 Crawling internal pages of {domain} to find all links...")
    print("─" * 60)
    
    while queue and len(visited_pages) < MAX_PAGES:
        url = queue.pop(0)
        # Normalize trailing slash
        clean_url = url.rstrip("/") or url
        if clean_url in visited_pages:
            continue
            
        visited_pages.add(clean_url)
        print(f"  [{len(visited_pages):>3}] Crawling: {url}")
        
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                ct = resp.headers.get_content_type()
                if "html" not in ct:
                    continue
                html = resp.read(500_000).decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
        except Exception as e:
            print(f"      [!] Failed to load {url}: {e}")
            continue

        parser = LinkExtractor(base_url=url)
        try:
            parser.feed(html)
        except Exception:
            pass
            
        unique_links = list(set(parser.links))
        page_links_map[clean_url] = unique_links
        
        # Enqueue new internal links
        for link in unique_links:
            p = urllib.parse.urlparse(link)
            if p.netloc == domain:
                clean_link = link.rstrip("/") or link
                # Only add if it looks like an HTML page (no obvious file extensions)
                if clean_link not in visited_pages and clean_link not in [q.rstrip("/") or q for q in queue]:
                    if not any(clean_link.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".pdf", ".css", ".js", ".svg", ".zip", ".webp")):
                        queue.append(link)

        time.sleep(DELAY_SEC)
        
    return page_links_map


def esc(s: str) -> str:
    """HTML-escape a string."""
    return (str(s) or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def build_html_report(page_dead_links_map: dict, total_pages_checked: int, total_links_checked: int) -> str:
    """Build a nice HTML report grouping dead links by their source page."""
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_dead = sum(len(links) for links in page_dead_links_map.values())
    pages_with_dead = len(page_dead_links_map)
    
    rows_html = ""
    idx = 1
    
    # Sort pages alphabetically
    for page, dead_links in sorted(page_dead_links_map.items()):
        
        # Inner table for dead links on this page
        links_rows = ""
        for dl in dead_links:
            err_msg = dl['error'] or f"HTTP {dl['status']}"
            links_rows += f"""
            <tr class="inner-row">
                <td class="dl-url"><a href="{esc(dl['url'])}" target="_blank" rel="noopener">{esc(dl['url'])}</a></td>
                <td class="dl-status"><span class="err-badge">{esc(err_msg)}</span></td>
            </tr>
            """
            
        rows_html += f"""
        <tr class="page-grouping">
            <td class="idx">{idx}</td>
            <td class="page-url" colspan="2">
                <div class="page-url-header">
                    <strong>Found {len(dead_links)} dead links on:</strong>
                    <br/>
                    <a href="{esc(page)}" target="_blank" rel="noopener">{esc(page)}</a>
                </div>
                <table class="inner-table">
                    <thead>
                        <tr><th style="width:70%;">Dead Link URL</th><th>Error Status</th></tr>
                    </thead>
                    <tbody>
                        {links_rows}
                    </tbody>
                </table>
            </td>
        </tr>
        """
        idx += 1

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Dead Links Report</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --bg:       #0d0f14;
    --surface:  #151820;
    --card:     #1c2030;
    --border:   #2a2f45;
    --accent:   #ef4444; /* red accent for dead links */
    --accent2:  #f87171;
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
    background: linear-gradient(135deg, #301010 0%, #1a0d0d 50%, #0d1a2b 100%);
    padding: 48px 40px 36px;
    border-bottom: 1px solid var(--border);
    position: relative;
    overflow: hidden;
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

  /* ── TABLE ── */
  .table-wrap {{ overflow-x:auto; padding: 40px; }}
  table.main-tbl {{
    width:100%; border-collapse: separate; border-spacing: 0 16px;
  }}
  
  .page-grouping td {{
    background: var(--card);
    padding: 0;
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  .page-grouping td:first-child {{ 
      border-left: 1px solid var(--border); 
      border-radius: var(--radius) 0 0 var(--radius); 
      padding: 24px 16px;
      text-align: center;
  }}
  .page-grouping td:last-child {{ 
      border-right: 1px solid var(--border); 
      border-radius: 0 var(--radius) var(--radius) 0;
  }}
  
  .idx {{ color:var(--muted); font-size:1.2rem; font-weight:600; width:50px; }}
  
  .page-url-header {{
      padding: 20px 24px;
      border-bottom: 1px solid var(--border);
      background: rgba(0,0,0,0.2);
      border-radius: 0 var(--radius) 0 0;
  }}
  .page-url-header strong {{ color: #fff; font-size: 1.05rem; }}
  .page-url-header a {{ color: #60a5fa; text-decoration: none; font-size: .9rem; display:inline-block; margin-top:6px; word-break:break-all; }}
  .page-url-header a:hover {{ text-decoration: underline; }}

  .inner-table {{
      width: 100%;
      border-collapse: collapse;
      border-radius: 0 0 var(--radius) 0;
  }}
  .inner-table th {{
      padding: 10px 24px;
      text-align: left;
      font-size: .75rem;
      text-transform: uppercase;
      letter-spacing: .05em;
      color: var(--muted);
      background: rgba(255,255,255,0.02);
      border-bottom: 1px solid var(--border);
  }}
  .inner-table td {{
      padding: 16px 24px;
      border-bottom: 1px solid rgba(42, 47, 69, 0.5);
      background: transparent;
  }}
  .inner-table tr:last-child td {{ border-bottom: none; }}
  
  .dl-url a {{ color: var(--accent2); text-decoration: none; font-size: .85rem; word-break:break-all; font-family:monospace; }}
  .dl-url a:hover {{ text-decoration: underline; }}
  
  .err-badge {{
      background: rgba(239, 68, 68, 0.15);
      color: #fca5a5;
      padding: 6px 10px;
      border-radius: 6px;
      font-size: .75rem;
      font-weight: 600;
      border: 1px solid rgba(239, 68, 68, 0.3);
      display: inline-block;
  }}

  .success-msg {{
      text-align: center;
      padding: 60px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      margin-top: 40px;
  }}
  .success-msg h2 {{ color: var(--green); }}
  .success-msg p {{ color: var(--muted); margin-top: 8px; }}

  ::-webkit-scrollbar {{ width:6px; height:6px; }}
  ::-webkit-scrollbar-track {{ background:var(--bg); }}
  ::-webkit-scrollbar-thumb {{ background:var(--border); border-radius:3px; }}
</style>
</head>
<body>

<div class="header">
  <h1>🚨 Dead Links Report</h1>
  <p>Site: <strong>{urllib.parse.urlparse(START_URL).netloc}</strong> &nbsp;·&nbsp; Generated: {now}</p>
  <div class="stats">
    <div class="stat"><div class="stat-n">{total_pages_checked}</div><div class="stat-l">Pages Crawled</div></div>
    <div class="stat"><div class="stat-n">{total_links_checked}</div><div class="stat-l">Unique Links Checked</div></div>
    <div class="stat"><div class="stat-n" style="color:var(--red);">{total_dead}</div><div class="stat-l">Dead Links Found</div></div>
    <div class="stat"><div class="stat-n" style="color:var(--amber);">{pages_with_dead}</div><div class="stat-l">Pages with Errors</div></div>
  </div>
</div>

<div class="table-wrap">
  {"<table class='main-tbl'>" + rows_html + "</table>" if total_dead > 0 else 
   "<div class='success-msg'><h2>🎉 All clear!</h2><p>No dead links were found on any of the crawled pages.</p></div>"}
</div>

</body>
</html>"""


def main():
    output_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(output_dir, OUTPUT_FILE)

    # 1. Crawl all pages and extract their links
    page_links_map = crawl_and_extract_links(START_URL)

    # 2. Gather all unique links across the site to avoid redundant checking
    all_unique_links = set()
    for links in page_links_map.values():
        all_unique_links.update(links)

    print(f"\n⚡ Checking status of {len(all_unique_links)} unique links found across {len(page_links_map)} pages...")
    print("─" * 60)
    
    link_status_cache = {}
    
    for i, link in enumerate(list(all_unique_links)):
        if i % 10 == 0 and i > 0:
            print(f"  [{i}/{len(all_unique_links)}] Checked...")
            
        status_info = check_url_status(link)
        link_status_cache[link] = status_info
        time.sleep(0.05) # small delay to prevent IP block

    print(f"  [{len(all_unique_links)}/{len(all_unique_links)}] Done checking links.\n")

    # 3. Associate dead links back to their source pages
    page_dead_links_map = {}
    
    for page, links in page_links_map.items():
        dead_on_this_page = []
        for link in links:
            status_info = link_status_cache[link]
            if not status_info['ok']:
                dead_on_this_page.append({
                    "url": link,
                    "status": status_info["status"],
                    "error": status_info.get("error")
                })
                
        if dead_on_this_page:
            # deduplicate
            unique_dead = []
            seen = set()
            for d in dead_on_this_page:
                if d['url'] not in seen:
                    seen.add(d['url'])
                    unique_dead.append(d)
            page_dead_links_map[page] = unique_dead

    # 4. Generate the report
    print(f"📝 Building Dead Link HTML Report → {output_path}")
    html = build_html_report(
        page_dead_links_map, 
        total_pages_checked=len(page_links_map), 
        total_links_checked=len(all_unique_links)
    )
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
        
    print(f"✅ Report complete! Open: {output_path}")


if __name__ == "__main__":
    main()
