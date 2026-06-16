#!/usr/bin/env python3
"""Build the static JSON payload for the /digest/ page."""

from __future__ import annotations

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


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "digest" / "data"
ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

CONFERENCE_AGT_KEYWORDS = [
    "STOC",
    "FOCS",
    "EC",
    "WINE",
    "SODA",
    "ICALP",
    "auction",
    "mechanism",
    "equilibrium",
    "market",
]

MATCHING_PHRASES = [
    "online matching",
    "stable matching",
    "matching market",
    "matching markets",
    "bipartite matching",
]

AI_KEYWORDS = [
    "LLM",
    "large language model",
    "agent",
    "reasoning",
    "reinforcement learning",
    "alignment",
]

TAG_KEYWORDS = [
    "mechanism design",
    "auction",
    "equilibrium",
    "market",
    "matching",
    "LLM",
    "large language model",
    "agent",
    "reasoning",
    "reinforcement learning",
    "alignment",
]

CLASSIC_AI_PAPERS = [
    {
        "title": "Attention Is All You Need",
        "authors": [
            "Ashish Vaswani",
            "Noam Shazeer",
            "Niki Parmar",
            "Jakob Uszkoreit",
            "Llion Jones",
            "Aidan N. Gomez",
            "Lukasz Kaiser",
            "Illia Polosukhin",
        ],
        "date": "2017-06-12",
        "source": "Classic AI",
        "url": "https://arxiv.org/abs/1706.03762",
        "abstract": (
            "The Transformer paper introduced a sequence transduction architecture "
            "based entirely on attention mechanisms, becoming a foundation for "
            "modern large language models."
        ),
        "tags": ["transformer", "LLM", "attention"],
    },
    {
        "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "authors": ["Jacob Devlin", "Ming-Wei Chang", "Kenton Lee", "Kristina Toutanova"],
        "date": "2018-10-11",
        "source": "Classic AI",
        "url": "https://arxiv.org/abs/1810.04805",
        "abstract": (
            "BERT showed how bidirectional Transformer pre-training can produce "
            "strong language representations for a wide range of NLP tasks."
        ),
        "tags": ["transformer", "pretraining", "NLP"],
    },
    {
        "title": "Deep Residual Learning for Image Recognition",
        "authors": ["Kaiming He", "Xiangyu Zhang", "Shaoqing Ren", "Jian Sun"],
        "date": "2015-12-10",
        "source": "Classic AI",
        "url": "https://arxiv.org/abs/1512.03385",
        "abstract": (
            "ResNet introduced residual connections that made it practical to train "
            "very deep neural networks, reshaping modern computer vision."
        ),
        "tags": ["deep learning", "computer vision", "resnet"],
    },
    {
        "title": "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models",
        "authors": [
            "Jason Wei",
            "Xuezhi Wang",
            "Dale Schuurmans",
            "Maarten Bosma",
            "Fei Xia",
            "Ed Chi",
            "Quoc V. Le",
            "Denny Zhou",
        ],
        "date": "2022-01-28",
        "source": "Classic AI",
        "url": "https://arxiv.org/abs/2201.11903",
        "abstract": (
            "This paper popularized chain-of-thought prompting as a simple way to "
            "elicit multi-step reasoning behavior from sufficiently large language models."
        ),
        "tags": ["LLM", "reasoning", "prompting"],
    },
]


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def text_at(entry: ET.Element, path: str) -> str:
    found = entry.find(path, ARXIV_NS)
    return normalize_text(found.text if found is not None else "")


def keyword_matches(text: str, keyword: str) -> bool:
    if keyword.isupper() and len(keyword) <= 5:
        return re.search(rf"\b{re.escape(keyword.lower())}\b", text.lower()) is not None
    return keyword.lower() in text.lower()


def paper_matches(paper: dict, keywords: list[str]) -> bool:
    haystack = " ".join(
        [
            paper.get("title", ""),
            paper.get("abstract", ""),
            paper.get("source", ""),
            " ".join(paper.get("tags", [])),
        ]
    )
    return any(keyword_matches(haystack, keyword) for keyword in keywords)


def conference_agt_matches(paper: dict) -> bool:
    haystack = " ".join(
        [
            paper.get("title", ""),
            paper.get("abstract", ""),
            paper.get("source", ""),
            " ".join(paper.get("tags", [])),
        ]
    )
    haystack_lower = haystack.lower()
    return any(keyword_matches(haystack, keyword) for keyword in CONFERENCE_AGT_KEYWORDS) or any(
        phrase in haystack_lower for phrase in MATCHING_PHRASES
    )


def infer_tags(title: str, abstract: str, categories: list[str]) -> list[str]:
    text = f"{title} {abstract}"
    tags: list[str] = []
    for category in categories[:2]:
        if category not in tags:
            tags.append(category)
    for keyword in TAG_KEYWORDS:
        if keyword_matches(text, keyword) and keyword not in tags:
            tags.append(keyword)
    return tags[:5]


def arxiv_url_for(entry: ET.Element) -> str:
    for link in entry.findall("atom:link", ARXIV_NS):
        if link.attrib.get("rel") == "alternate" and link.attrib.get("href"):
            return link.attrib["href"]
    return text_at(entry, "atom:id")


def parse_arxiv_entry(entry: ET.Element) -> dict:
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
        "tags": infer_tags(title, abstract, categories),
    }


def fetch_arxiv(search_query: str, max_results: int = 30) -> list[dict]:
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
    return [parse_arxiv_entry(entry) for entry in root.findall("atom:entry", ARXIV_NS)]


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


def dedupe_and_limit(papers: list[dict], limit: int, seen_urls: set[str]) -> list[dict]:
    selected = []
    for paper in papers:
        url = paper.get("url", "")
        if url in seen_urls:
            continue
        selected.append(paper)
        if url:
            seen_urls.add(url)
        if len(selected) >= limit:
            break
    return selected


def choose_classic_ai(today: dt.date) -> dict:
    index = today.toordinal() % len(CLASSIC_AI_PAPERS)
    return CLASSIC_AI_PAPERS[index]


def build_digest(today: dt.date) -> dict:
    seen_urls: set[str] = set()

    game_theory = dedupe_and_limit(
        fetch_arxiv("cat:cs.GT", max_results=20),
        limit=2,
        seen_urls=seen_urls,
    )
    time.sleep(1)

    conference_candidates = fetch_arxiv("(cat:cs.GT OR cat:cs.DS)", max_results=50)
    conference_agt = dedupe_and_limit(
        [paper for paper in conference_candidates if conference_agt_matches(paper)],
        limit=2,
        seen_urls=seen_urls,
    )
    time.sleep(1)

    ai_candidates = fetch_arxiv("(cat:cs.AI OR cat:cs.LG OR cat:cs.CL)", max_results=50)
    recent_ai = dedupe_and_limit(
        [paper for paper in ai_candidates if paper_matches(paper, AI_KEYWORDS)],
        limit=1,
        seen_urls=seen_urls,
    )

    return {
        "date": today.isoformat(),
        "sections": [
            {
                "id": "arxiv-game-theory",
                "title": "New arXiv Game Theory",
                "papers": game_theory,
            },
            {
                "id": "conference-agt",
                "title": "Conference-flavored AGT",
                "papers": conference_agt,
            },
            {
                "id": "classic-ai",
                "title": "Classic AI Paper",
                "papers": [choose_classic_ai(today)],
            },
            {
                "id": "ai-paper",
                "title": "Recent AI Paper",
                "papers": recent_ai,
            },
        ],
    }


def write_digest(payload: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dated_path = DATA_DIR / f"{payload['date']}.json"
    today_path = DATA_DIR / "today.json"
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    dated_path.write_text(rendered, encoding="utf-8")
    today_path.write_text(rendered, encoding="utf-8")
    print(f"Wrote {dated_path.relative_to(ROOT)}")
    print(f"Wrote {today_path.relative_to(ROOT)}")


def main() -> None:
    today = dt.date.today()
    payload = build_digest(today)
    write_digest(payload)


if __name__ == "__main__":
    main()
