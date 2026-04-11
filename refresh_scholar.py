#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scholarly import scholarly

SCHOLAR_ID = "zy1UxxUAAAAJ"
SCHOLAR_URL = f"https://scholar.google.com/citations?user={SCHOLAR_ID}&hl=en"

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "template.html"
OUT = ROOT / "index.html"
JSON_OUT = ROOT / "scholar-data.json"

def safe(value: object, default: str = "—") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default

def interests_html(interests: list[str]) -> str:
    if not interests:
        return "<li>Research profile</li>"
    return "\n        ".join(f"<li>{item}</li>" for item in interests)

def pubs_html(publications: list[dict]) -> str:
    chunks = []
    for pub in publications:
        title = safe(pub.get("title"))
        year = safe(pub.get("year"))
        authors = safe(pub.get("author"))
        venue = safe(pub.get("venue"))
        chunks.append(
            f'''<article class="pub">
        <h3>{title}</h3>
        <div class="muted">{authors}</div>
        <div class="muted">{venue} · {year}</div>
      </article>'''
        )
    return "\n      ".join(chunks) if chunks else "<p>No publications found in this refresh.</p>"

def main() -> None:
    author = scholarly.search_author_id(SCHOLAR_ID)
    author = scholarly.fill(author, sections=["basics", "indices", "publications"])

    name = safe(author.get("name"))
    affiliation = safe(author.get("affiliation"))
    interests = author.get("interests", []) or []

    citedby = safe(author.get("citedby"))
    hindex = safe(author.get("hindex"))
    i10index = safe(author.get("i10index"))

    pubs = []
    for pub in (author.get("publications") or [])[:10]:
        bib = pub.get("bib", {}) or {}
        pubs.append({
            "title": safe(bib.get("title")),
            "author": safe(bib.get("author")),
            "venue": safe(bib.get("venue")),
            "year": safe(bib.get("pub_year") or bib.get("year")),
        })

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    data = {
        "scholar_url": SCHOLAR_URL,
        "name": name,
        "affiliation": affiliation,
        "interests": interests,
        "citations_all": citedby,
        "hindex_all": hindex,
        "i10_all": i10index,
        "last_updated": updated,
        "publications": pubs,
    }
    JSON_OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    tpl = TEMPLATE.read_text(encoding="utf-8")
    rendered = (
        tpl.replace("{{NAME}}", name)
           .replace("{{AFFILIATION}}", affiliation)
           .replace("{{INTERESTS}}", interests_html(interests))
           .replace("{{SCHOLAR_URL}}", SCHOLAR_URL)
           .replace("{{CITATIONS_ALL}}", citedby)
           .replace("{{HINDEX_ALL}}", hindex)
           .replace("{{I10_ALL}}", i10index)
           .replace("{{LAST_UPDATED}}", updated)
           .replace("{{PUBLICATIONS}}", pubs_html(pubs))
    )
    OUT.write_text(rendered, encoding="utf-8")

if __name__ == "__main__":
    main()
