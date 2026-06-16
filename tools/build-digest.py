#!/usr/bin/env python3
"""Build the static JSON payload for the /digest/ page."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "content" / "digest"
SECTIONS_FILE = CONFIG_DIR / "sections.json"
CLASSIC_AI_FILE = CONFIG_DIR / "classic-ai.json"
DATA_DIR = ROOT / "data" / "digest"
ARXIV_API_URL = "https://export.arxiv.org/api/query"
REQUEST_DELAY_SECONDS = 1
ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Missing digest config: {path.relative_to(ROOT)}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {path.relative_to(ROOT)}: {error}") from error


def require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def text_at(entry: ET.Element, path: str) -> str:
    found = entry.find(path, ARXIV_NS)
    return normalize_text(found.text if found is not None else "")


def keyword_matches(text: str, keyword: str) -> bool:
    if keyword.isupper() and len(keyword) <= 5:
        return re.search(rf"\b{re.escape(keyword.lower())}\b", text.lower()) is not None
    return keyword.lower() in text.lower()


def paper_haystack(paper: dict[str, Any]) -> str:
    return " ".join(
        [
            str(paper.get("title", "")),
            str(paper.get("abstract", "")),
            str(paper.get("source", "")),
            " ".join(str(tag) for tag in paper.get("tags", [])),
        ]
    )


def paper_matches_filters(paper: dict[str, Any], filters: dict[str, Any]) -> bool:
    keywords = [str(keyword) for keyword in filters.get("keywords", [])]
    phrases = [str(phrase).lower() for phrase in filters.get("phrases", [])]

    if not keywords and not phrases:
        return True

    haystack = paper_haystack(paper)
    haystack_lower = haystack.lower()
    return any(keyword_matches(haystack, keyword) for keyword in keywords) or any(
        phrase in haystack_lower for phrase in phrases
    )


def infer_tags(title: str, abstract: str, categories: list[str], tag_keywords: list[str]) -> list[str]:
    text = f"{title} {abstract}"
    tags: list[str] = []

    for category in categories[:2]:
        if category not in tags:
            tags.append(category)

    for keyword in tag_keywords:
        if keyword_matches(text, keyword) and keyword not in tags:
            tags.append(keyword)

    return tags[:5]


def arxiv_url_for(entry: ET.Element) -> str:
    for link in entry.findall("atom:link", ARXIV_NS):
        if link.attrib.get("rel") == "alternate" and link.attrib.get("href"):
            return link.attrib["href"]
    return text_at(entry, "atom:id")


def parse_arxiv_entry(entry: ET.Element, tag_keywords: list[str]) -> dict[str, Any]:
    title = text_at(entry, "atom:title")
    abstract = text_at(entry, "atom:summary")
    authors = [
        text_at(author, "atom:name")
        for author in entry.findall("atom:author", ARXIV_NS)
        if text_at(author, "atom:name")
    ]
    categories = [
        category.attrib["term"]
        for category in entry.findall("atom:category", ARXIV_NS)
        if category.attrib.get("term")
    ]
    primary = entry.find("arxiv:primary_category", ARXIV_NS)
    primary_category = primary.attrib.get("term") if primary is not None else ""
    source_category = primary_category or (categories[0] if categories else "arXiv")

    return {
        "title": title,
        "authors": authors,
        "date": text_at(entry, "atom:published")[:10],
        "source": f"arXiv {source_category}",
        "url": arxiv_url_for(entry),
        "abstract": abstract,
        "tags": infer_tags(title, abstract, categories, tag_keywords),
    }


def fetch_arxiv(search_query: str, tag_keywords: list[str], max_results: int = 30) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    request = urllib.request.Request(
        f"{ARXIV_API_URL}?{params}",
        headers={"User-Agent": "clifeast-digest/0.1"},
    )

    with open_arxiv_request(request) as response:
        xml_bytes = response.read()

    root = ET.fromstring(xml_bytes)
    return [parse_arxiv_entry(entry, tag_keywords) for entry in root.findall("atom:entry", ARXIV_NS)]


def open_arxiv_request(request: urllib.request.Request):
    try:
        return urllib.request.urlopen(request, timeout=30)
    except urllib.error.URLError as error:
        if not isinstance(error.reason, ssl.SSLCertVerificationError):
            raise

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        print("Warning: local certificate verification failed; retrying arXiv request without TLS verification.")
        return urllib.request.urlopen(request, timeout=30, context=context)


def dedupe_and_limit(papers: list[dict[str, Any]], limit: int, seen_urls: set[str]) -> list[dict[str, Any]]:
    selected = []

    for paper in papers:
        url = str(paper.get("url", ""))
        if url in seen_urls:
            continue

        selected.append(paper)

        if url:
            seen_urls.add(url)

        if len(selected) >= limit:
            break

    return selected


def choose_classic_ai(today: dt.date, papers: list[Any]) -> dict[str, Any]:
    if not papers:
        raise ValueError(f"{CLASSIC_AI_FILE.relative_to(ROOT)} must contain at least one paper")

    index = today.toordinal() % len(papers)
    paper = papers[index]

    if not isinstance(paper, dict):
        raise ValueError(f"{CLASSIC_AI_FILE.relative_to(ROOT)} contains a non-object paper entry")

    return paper


def build_arxiv_section(
    section: dict[str, Any],
    tag_keywords: list[str],
    seen_urls: set[str],
) -> list[dict[str, Any]]:
    query = section.get("query")
    if not isinstance(query, str) or not query:
        raise ValueError(f'Digest section "{section.get("id", "unknown")}" is missing query')

    max_results = int(section.get("maxResults", 30))
    limit = int(section.get("limit", 1))
    filters = section.get("filters", {})

    if not isinstance(filters, dict):
        raise ValueError(f'Digest section "{section.get("id", "unknown")}" filters must be an object')

    candidates = fetch_arxiv(query, tag_keywords=tag_keywords, max_results=max_results)
    filtered = [paper for paper in candidates if paper_matches_filters(paper, filters)]
    return dedupe_and_limit(filtered, limit=limit, seen_urls=seen_urls)


def build_digest(today: dt.date) -> dict[str, Any]:
    config = load_json(SECTIONS_FILE)
    sections = require_list(config.get("sections"), f"{SECTIONS_FILE.relative_to(ROOT)} sections")
    tag_keywords = [str(keyword) for keyword in config.get("tagKeywords", [])]
    classic_papers = require_list(load_json(CLASSIC_AI_FILE), str(CLASSIC_AI_FILE.relative_to(ROOT)))
    seen_urls: set[str] = set()
    rendered_sections: list[dict[str, Any]] = []
    has_fetched_arxiv = False

    for section in sections:
        if not isinstance(section, dict):
            raise ValueError(f"{SECTIONS_FILE.relative_to(ROOT)} contains a non-object section")

        source = section.get("source")
        if source == "arxiv":
            if has_fetched_arxiv:
                time.sleep(REQUEST_DELAY_SECONDS)
            papers = build_arxiv_section(section, tag_keywords=tag_keywords, seen_urls=seen_urls)
            has_fetched_arxiv = True
        elif source == "classic-ai":
            papers = [choose_classic_ai(today, classic_papers)]
        else:
            raise ValueError(f'Digest section "{section.get("id", "unknown")}" has unknown source: {source}')

        rendered_sections.append(
            {
                "id": section.get("id", ""),
                "title": section.get("title", "Untitled section"),
                "papers": papers,
            }
        )

    return {
        "date": today.isoformat(),
        "sections": rendered_sections,
    }


def write_digest(payload: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dated_path = DATA_DIR / f"{payload['date']}.json"
    today_path = DATA_DIR / "today.json"
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    dated_path.write_text(rendered, encoding="utf-8")
    today_path.write_text(rendered, encoding="utf-8")
    print(f"Wrote {dated_path.relative_to(ROOT)}")
    print(f"Wrote {today_path.relative_to(ROOT)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the static /digest/ JSON payload.")
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Digest date in YYYY-MM-DD format. Defaults to today.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    today = dt.date.fromisoformat(args.date)
    payload = build_digest(today)
    write_digest(payload)


if __name__ == "__main__":
    main()
