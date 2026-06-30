#!/usr/bin/env python3
"""Refresh Google Scholar metrics on the existing index.html.

Design notes (read before editing):
  * This does NOT regenerate the page from a template. It patches the
    *existing* index.html in place — updating the four metric numbers and
    the per-paper citation badges — so the curated, richly formatted page
    is preserved. The old template.html is no longer used and can be deleted.
  * Data comes from the SerpAPI Google Scholar Author API, which works from
    CI (direct scraping via `scholarly` is blocked by Google from datacenter
    IPs). Requires a repo secret SERP_API_KEY, read from the environment.
  * Per-paper matching is by Scholar citation_id (the stable
    `citation_for_view=<AUTHOR>:<id>` token already present in each link),
    so it never depends on fragile title matching.
  * It is non-destructive: if the key is missing or the API call fails, it
    logs a warning and exits 0 WITHOUT touching index.html. A failed refresh
    can therefore never blank out or downgrade the page.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from urllib.parse import urlencode

SCHOLAR_ID = "qS2dYUAAAAAJ"
SCHOLAR_URL = f"https://scholar.google.com/citations?user={SCHOLAR_ID}&hl=en"
API = "https://serpapi.com/search.json"

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
JSON_OUT = ROOT / "scholar-data.json"


def warn_and_exit(msg: str) -> None:
    print(f"::warning::{msg}")
    print(msg)
    sys.exit(0)  # exit clean so the scheduled workflow is not auto-disabled


def fetch(key: str, start: int) -> dict:
    params = {
        "engine": "google_scholar_author",
        "author_id": SCHOLAR_ID,
        "api_key": key,
        "num": 100,
        "start": start,
        "sort": "cited_by",
    }
    with urlopen(API + "?" + urlencode(params), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def get_metrics(table: list[dict]) -> dict:
    def cell(name: str) -> dict:
        for row in table:
            if name in row:
                return row[name]
        return {}
    c, h, i = cell("citations"), cell("h_index"), cell("i10_index")
    return {
        "citations_all": c.get("all"),
        "citations_2021": c.get("since_2021"),
        "hindex_all": h.get("all"),
        "hindex_2021": h.get("since_2021"),
        "i10_all": i.get("all"),
        "i10_2021": i.get("since_2021"),
    }


def patch_metric(html: str, label: str, value, since=None) -> str:
    """Update the <div class="metric-value"> (and optional sublabel) of the
    metric-box whose <div class="metric-label"> equals `label`."""
    if value is None:
        return html
    # `[^<]*` for the value keeps the match inside a single metric-box (it
    # cannot span tags), so patching h-index/i10 can't swallow earlier boxes.
    box = re.compile(
        r'(<div class="metric-box"><div class="metric-value">)([^<]*)'
        r'(</div><div class="metric-label">' + re.escape(label) + r'</div>)'
        r'(?:(<div class="metric-sublabel">\()([^<]*?)( since 2021\)</div>))?'
    )

    def repl(m: re.Match) -> str:
        out = m.group(1) + f"{value:,}" + m.group(3)
        if m.group(4) is not None:
            sub = f"{since:,}" if since is not None else m.group(5)
            out += m.group(4) + sub + m.group(6)
        return out

    return box.sub(repl, html, count=1)


def patch_badges(html: str, by_id: dict[str, int]) -> tuple[str, int]:
    """Replace each per-paper citation badge using the citation_id found in
    that pub-item's link. Returns (new_html, number_updated)."""
    parts = html.split('<div class="pub-item">')
    updated = 0
    for idx in range(1, len(parts)):
        seg = parts[idx]
        m_id = re.search(r"citation_for_view=" + re.escape(SCHOLAR_ID) + r":([^\"&]+)", seg)
        if not m_id:
            continue
        cid = f"{SCHOLAR_ID}:{m_id.group(1)}"
        if cid not in by_id:
            continue
        val = by_id[cid]
        new_seg, n = re.subn(
            r'(<span class="pub-cite-badge">)[\d,]+ citations(</span>)',
            lambda m: f"{m.group(1)}{val:,} citations{m.group(2)}",
            seg,
            count=1,
        )
        if n:
            parts[idx] = new_seg
            updated += 1
    return '<div class="pub-item">'.join(parts), updated


def main() -> None:
    key = os.environ.get("SERP_API_KEY", "").strip()
    if not key:
        warn_and_exit("SERP_API_KEY is not set; leaving the page unchanged.")
    if not INDEX.exists():
        warn_and_exit(f"{INDEX.name} not found; nothing to update.")

    try:
        first = fetch(key, 0)
    except (HTTPError, URLError, TimeoutError) as e:
        warn_and_exit(f"SerpAPI request failed ({e}); leaving the page unchanged.")
    if first.get("error"):
        warn_and_exit(f"SerpAPI error: {first['error']}; leaving the page unchanged.")

    metrics = get_metrics(first.get("cited_by", {}).get("table", []))

    # Gather every article (paginate) and key citations by citation_id.
    articles = list(first.get("articles", []))
    page, start = first, 100
    while page.get("serpapi_pagination", {}).get("next") and start <= 500:
        try:
            page = fetch(key, start)
        except (HTTPError, URLError, TimeoutError):
            break
        batch = page.get("articles", [])
        if not batch:
            break
        articles.extend(batch)
        start += 100

    by_id: dict[str, int] = {}
    for a in articles:
        cid = a.get("citation_id")
        val = a.get("cited_by", {}).get("value")
        if cid and isinstance(val, int):
            by_id[cid] = val

    # ── Patch the existing page in place ──
    html = INDEX.read_text(encoding="utf-8")
    html = patch_metric(html, "Citations", metrics["citations_all"], metrics["citations_2021"])
    html = patch_metric(html, "h-index", metrics["hindex_all"], metrics["hindex_2021"])
    html = patch_metric(html, "i10-index", metrics["i10_all"], metrics["i10_2021"])
    html, n_badges = patch_badges(html, by_id)
    INDEX.write_text(html, encoding="utf-8")

    # ── Also write the machine-readable data file (all publications) ──
    data = {
        "scholar_url": SCHOLAR_URL,
        "scholarId": SCHOLAR_ID,
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metrics": metrics,
        "publications": [
            {
                "citation_id": a.get("citation_id"),
                "title": a.get("title"),
                "year": a.get("year"),
                "citations": a.get("cited_by", {}).get("value"),
            }
            for a in articles
        ],
    }
    JSON_OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        f"Updated metrics (citations {metrics['citations_all']}, h {metrics['hindex_all']}, "
        f"i10 {metrics['i10_all']}); badges updated: {n_badges}; "
        f"articles from Scholar: {len(articles)}."
    )


if __name__ == "__main__":
    main()
