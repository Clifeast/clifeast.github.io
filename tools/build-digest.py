#!/usr/bin/env python3
"""Build the static JSON payload for the /digest/ page.

Only the two recent arXiv sections are active. Cross-run state is limited to
completed run dates.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import random
import re
import ssl
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[1]
SECTIONS_FILE = ROOT / "content" / "digest" / "sections.json"
DATA_DIR = ROOT / "data" / "digest"
STATE_FILE = DATA_DIR / "state.json"
DEBUG_DIR = DATA_DIR / "debug"
DIGEST_INDEX_FILE = DATA_DIR / "index.json"

ARXIV_API_URL = "https://export.arxiv.org/api/query"
DEFAULT_LLM_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_SCORE_MODEL = "qwen-plus"
DEFAULT_QWEN_ENRICH_MODEL = "qwen-long"
DEFAULT_TIMEZONE = "America/Los_Angeles"
USER_AGENT = "clifeast-digest/0.4 (+https://clifeast.github.io/digest/)"
PIPELINE_VERSION = "recent-arxiv-v3-score30"

ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

AI_SCORE_KEYS = ["importance", "horizonValue",
                 "clarity", "theoreticalDepth", "overall", "penalty"]
AGT_SCORE_KEYS = [
    "modelNaturalness",
    "theoreticalStrength",
    "guaranteeQuality",
    "readingValue",
    "penalty",
    "aiRelevance",
    "agtRelevance",
]
SCORE_LABELS = {
    "importance": "重要性",
    "horizonValue": "视野价值",
    "clarity": "清晰度",
    "theoreticalDepth": "理论深度",
    "overall": "整体判断",
    "modelNaturalness": "问题与模型自然性",
    "theoreticalStrength": "理论结果强度",
    "guaranteeQuality": "保证与假设质量",
    "readingValue": "相关性与阅读收益",
    "aiRelevance": "AI 相关度",
    "agtRelevance": "AGT/EconCS 相关度",
    "penalty": "惩罚",
    "baseTotal": "基础分",
    "bonus": "AI 相关奖励",
    "total": "总分",
}
SCORE_KEYS_BY_SECTION = {
    "recent-ai": AI_SCORE_KEYS,
    "recent-agt": AGT_SCORE_KEYS,
}
AI_SCORE_MAXIMA = {
    "importance": 6.0,
    "horizonValue": 6.0,
    "clarity": 6.0,
    "theoreticalDepth": 8.0,
    "overall": 4.0,
}
AGT_SCORE_MAXIMA = {
    "modelNaturalness": 8.0,
    "theoreticalStrength": 10.0,
    "guaranteeQuality": 6.0,
    "readingValue": 6.0,
    "aiRelevance": 10.0,
    "agtRelevance": 10.0,
}
SELECTION_MIN_SCORE = 16.0
SELECTION_MAX_ITEMS = 5

AI_CATEGORY_POOL = ["cs.AI", "cs.LG", "cs.CL",
                    "cs.CV", "cs.RO", "cs.IR", "cs.NE", "cs.MA"]
SUMMARY_SECTION_KEYS = [
    "backgroundAndQuestion",
    "modelAndSetup",
    "contributionsAndResults",
    "methodsAndTechniques",
    "limitationsAndReadingValue",
]
SUMMARY_SECTION_LABELS = {
    "backgroundAndQuestion": "背景与问题",
    "modelAndSetup": "模型与设定",
    "contributionsAndResults": "贡献与结果",
    "methodsAndTechniques": "方法与技术",
    "limitationsAndReadingValue": "局限与阅读价值",
}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False,
                    indent=2) + "\n", encoding="utf-8")


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_title(value: str | None) -> str:
    text = normalize_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return normalize_text(text)


def clamp_score(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if 0.0 <= number <= 10.0:
        number *= 10.0
    return round(min(100.0, max(0.0, number)), 1)


def clamp_range(value: Any, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = minimum
    return round(min(maximum, max(minimum, number)), 1)


def stable_rng(seed: str) -> random.Random:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def json_from_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("LLM response is not a JSON object")
    return payload


def open_url(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    timeout: int = 90,
) -> bytes:
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        url, data=data, headers=request_headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
        return response.read()


def fetch_text(url: str, *, timeout: int = 90) -> str:
    return open_url(url, timeout=timeout).decode("utf-8", errors="replace")


def download_pdf(url: str, directory: Path, filename: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-",
                       filename).strip("-") or "paper.pdf"
    if not safe_name.endswith(".pdf"):
        safe_name += ".pdf"
    path = directory / safe_name
    path.write_bytes(open_url(url, timeout=180))
    return path


def default_state() -> dict[str, Any]:
    return {"version": 2, "runs": {}}


def load_state() -> dict[str, Any]:
    raw = load_json(STATE_FILE, default_state())
    state = raw if isinstance(raw, dict) else {}
    runs = state.get("runs") if isinstance(state.get("runs"), dict) else {}
    return {"version": 2, "runs": runs}


def save_state(state: dict[str, Any]) -> None:
    write_json(STATE_FILE, {"version": 2, "runs": state.get(
        "runs", {}) if isinstance(state.get("runs"), dict) else {}})


def debug_section(debug: dict[str, Any], section_id: str) -> dict[str, Any]:
    sections = debug.setdefault("sections", {})
    section_debug = sections.setdefault(section_id, {})
    return section_debug


def paper_debug_summary(paper: dict[str, Any]) -> dict[str, Any]:
    ids = paper.get("ids") if isinstance(paper.get("ids"), dict) else {}
    metadata = paper.get("metadata") if isinstance(
        paper.get("metadata"), dict) else {}
    return {
        "title": paper.get("title", ""),
        "url": paper.get("url", ""),
        "arxivId": ids.get("arxiv", ""),
        "date": paper.get("date", ""),
        "source": paper.get("source", ""),
        "categories": metadata.get("categories", []),
    }


def merge_tags(content_tags: Any, paradigm_tags: Any) -> list[str]:
    tags: list[str] = []
    for group in (content_tags, paradigm_tags):
        if not isinstance(group, list):
            continue
        for tag in group:
            clean = normalize_text(str(tag))
            if clean and clean not in tags:
                tags.append(clean)
    return tags[:8]


def arxiv_id_from_value(value: str | None) -> str:
    match = re.search(r"(\d{4}\.\d{4,5})(?:v\d+)?", normalize_text(value))
    return match.group(1) if match else ""


def arxiv_pdf_url_for_paper(paper: dict[str, Any]) -> str:
    ids = paper.get("ids") if isinstance(paper.get("ids"), dict) else {}
    arxiv_id = normalize_text(str(ids.get("arxiv", "")))
    if not arxiv_id:
        arxiv_id = arxiv_id_from_value(str(paper.get("url", "")))
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else ""


def make_paper(
    *,
    title: str,
    authors: list[str] | None,
    date: str,
    source: str,
    url: str,
    abstract: str = "",
    ids: dict[str, str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title = normalize_text(title)
    abstract = normalize_text(abstract)
    return {
        "title": title,
        "authors": [normalize_text(author) for author in (authors or []) if normalize_text(author)],
        "date": normalize_text(date),
        "source": normalize_text(source),
        "url": normalize_text(url),
        "abstract": abstract,
        "summarySections": {},
        "researchParadigmTags": [],
        "contentTags": [],
        "tags": [],
        "scores": {"total": 0.0},
        "ids": ids or {},
        "metadata": metadata or {},
    }


def normalize_scores(raw: Any, section: dict[str, Any]) -> dict[str, float]:
    source = raw if isinstance(raw, dict) else {}
    section_id = str(section.get("id", ""))
    if section_id == "recent-agt":
        return normalize_agt_scores(source)
    return normalize_ai_scores(source)


def normalize_ai_scores(source: dict[str, Any]) -> dict[str, float]:
    scores = {key: clamp_range(source.get(key, 0.0), 0.0, maximum)
              for key, maximum in AI_SCORE_MAXIMA.items()}
    scores["penalty"] = clamp_range(source.get("penalty", 0.0), -5.0, 0.0)
    scores["baseTotal"] = round(sum(scores[key]
                                for key in AI_SCORE_MAXIMA) + scores["penalty"], 1)
    scores["total"] = round(max(0.0, scores["baseTotal"]), 1)
    return scores


def normalize_agt_scores(source: dict[str, Any]) -> dict[str, float]:
    scores = {key: clamp_range(source.get(key, 0.0), 0.0, maximum)
              for key, maximum in AGT_SCORE_MAXIMA.items()}
    scores["penalty"] = clamp_range(source.get("penalty", 0.0), -5.0, 0.0)
    if scores["agtRelevance"] < 6.0:
        return {key: 0.0 for key in [*AGT_SCORE_KEYS, "baseTotal", "bonus", "total"]}
    scores["agtRelevance"] = clamp_range(scores["agtRelevance"], 6.0, 10.0)
    base_total = round(
        scores["modelNaturalness"]
        + scores["theoreticalStrength"]
        + scores["guaranteeQuality"]
        + scores["readingValue"]
        + scores["penalty"],
        1,
    )
    scores["baseTotal"] = round(max(0.0, base_total), 1)
    scores["bonus"] = round(scores["baseTotal"] *
                            scores["aiRelevance"] / 30.0, 1)
    scores["total"] = round(
        (scores["baseTotal"] + scores["bonus"]) * scores["agtRelevance"] / 10.0, 1)
    return scores


def apply_score_result(paper: dict[str, Any], result: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
    updated = dict(paper)
    scores = normalize_scores(result.get("scores"), section)
    updated["scores"] = scores
    return updated


def normalize_enrichment_result(result: dict[str, Any]) -> dict[str, Any]:
    raw_sections = result.get("summarySections")
    if not isinstance(raw_sections, dict):
        raw_sections = {}
    summary_sections = {
        key: normalize_text(str(raw_sections.get(key, result.get(key, ""))))
        for key in SUMMARY_SECTION_KEYS
    }
    return {
        "researchParadigmTags": result.get("researchParadigmTags", []),
        "contentTags": result.get("contentTags", result.get("tags", [])),
        "summarySections": summary_sections,
    }


def apply_enrichment_result(paper: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    updated = dict(paper)
    content_tags = result.get("contentTags")
    paradigm_tags = result.get("researchParadigmTags")
    if isinstance(content_tags, list) and content_tags:
        updated["contentTags"] = [normalize_text(
            str(tag)) for tag in content_tags if normalize_text(str(tag))][:5]
    if isinstance(paradigm_tags, list) and paradigm_tags:
        updated["researchParadigmTags"] = [normalize_text(
            str(tag)) for tag in paradigm_tags if normalize_text(str(tag))][:5]
    summary_sections = result.get("summarySections")
    if isinstance(summary_sections, dict):
        updated["summarySections"] = {
            key: normalize_text(str(summary_sections.get(key, "")))
            for key in SUMMARY_SECTION_KEYS
            if normalize_text(str(summary_sections.get(key, "")))
        }
    updated["tags"] = merge_tags(updated.get(
        "contentTags", []), updated.get("researchParadigmTags", []))
    return updated


class MockRanker:
    def score_batch(
        self,
        papers: list[dict[str, Any]],
        section: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        raw_items = [self._score_result(index, paper, section)
                     for index, paper in enumerate(papers)]
        scored = [apply_score_result(paper, raw_items[index], section)
                  for index, paper in enumerate(papers)]
        return scored, {"provider": "mock", "items": raw_items}

    def enrich_paper(self, paper: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        summary_sections = self._summary_sections(paper)
        result = {
            "researchParadigmTags": [],
            "contentTags": [],
            "summarySections": summary_sections,
        }
        return apply_enrichment_result(paper, result), {"provider": "mock", **result}

    def _score_result(self, index: int, paper: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
        text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
        seed = normalize_title(str(paper.get("title", ""))) or str(index)
        jitter = stable_rng(seed).uniform(-0.7, 0.7)
        if str(section.get("id", "")) == "recent-agt":
            scores = normalize_scores({
                "modelNaturalness": 4.8 + 1.4 * any(word in text for word in ["mechanism", "auction", "market", "game", "agent"]) + jitter,
                "theoreticalStrength": 5.8 + 2.2 * any(word in text for word in ["theorem", "proof", "bound", "equilibrium", "impossibility"]) + jitter,
                "guaranteeQuality": 3.8 + 1.2 * any(word in text for word in ["guarantee", "tight", "optimal", "approximation"]) + jitter,
                "readingValue": 3.8 + 1.3 * any(word in text for word in ["algorithm", "characterization", "benchmark", "framework"]) + jitter,
                "penalty": -1.0,
                "aiRelevance": 6.5 + 2.0 * any(word in text for word in ["ai", "learning", "language model", "robot", "neural"]),
                "agtRelevance": 6.0 + 2.5 * any(word in text for word in ["mechanism", "auction", "market", "game", "equilibrium", "incentive"]),
            }, section)
        else:
            scores = normalize_scores({
                "importance": 3.8 + 1.3 * any(word in text for word in ["foundation", "large language", "agent", "safety", "robot"]) + jitter,
                "horizonValue": 3.7 + 1.2 * any(word in text for word in ["new", "novel", "first", "paradigm", "framework"]) + jitter,
                "clarity": 4.0 + 0.8 * any(word in text for word in ["propose", "introduce", "show", "demonstrate"]) + jitter,
                "theoreticalDepth": 3.8 + 2.2 * any(word in text for word in ["theorem", "proof", "complexity", "bound", "optimization"]) + jitter,
                "overall": 2.4 + 0.8 * any(word in text for word in ["state-of-the-art", "significant", "outperform", "guarantee"]),
                "penalty": -1.0 * any(word in text for word in ["benchmark", "leaderboard", "sota"]),
            }, section)
        return {
            "index": index,
            "scores": scores,
        }

    def _summary_sections(self, paper: dict[str, Any]) -> dict[str, str]:
        abstract = normalize_text(str(paper.get("abstract", "")))
        preview = abstract[:260].rstrip(
        ) + ("..." if len(abstract) > 260 else "")
        base = preview or "该论文暂无摘要。"
        return {
            "backgroundAndQuestion": base,
            "modelAndSetup": "Mock fallback 未读取完整论文，暂以摘要信息保守占位。",
            "contributionsAndResults": "Mock fallback 未生成贡献细节。",
            "methodsAndTechniques": "Mock fallback 未生成技术路线。",
            "limitationsAndReadingValue": "Mock fallback 未生成局限与阅读价值判断。",
        }


class LLMClient:
    def __init__(self, *, no_network: bool) -> None:
        self.no_network = no_network
        self.api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get(
            "QWEN_API_KEY") or os.environ.get("LLM_API_KEY")
        self.api_base = os.environ.get("QWEN_API_BASE", os.environ.get(
            "LLM_API_BASE", DEFAULT_LLM_API_BASE)).rstrip("/")
        self.score_model = os.environ.get("QWEN_SCORE_MODEL", os.environ.get(
            "LLM_SCORE_MODEL", DEFAULT_QWEN_SCORE_MODEL))
        self.enrich_model = os.environ.get("QWEN_ENRICH_MODEL", os.environ.get(
            "LLM_ENRICH_MODEL", DEFAULT_QWEN_ENRICH_MODEL))
        self.timeout_seconds = int(
            os.environ.get("LLM_TIMEOUT_SECONDS", "180"))
        self.batch_size = max(
            1, int(os.environ.get("DIGEST_SCORE_BATCH_SIZE", "25")))
        self.fallback = MockRanker()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) and not self.no_network

    def score_papers(
        self,
        papers: list[dict[str, Any]],
        section: dict[str, Any],
        section_debug: dict[str, Any],
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        batches = section_debug.setdefault("scoreBatches", [])
        for start in range(0, len(papers), self.batch_size):
            batch = papers[start:start + self.batch_size]
            batch_debug: dict[str, Any] = {
                "startIndex": start,
                "inputPapers": [paper_debug_summary(paper) | {"abstract": paper.get("abstract", "")} for paper in batch],
            }
            try:
                if self.enabled:
                    raw = self._chat_json(
                        model=self.score_model,
                        prompt=batch_score_prompt(batch, section),
                        temperature=0.05,
                    )
                    items = normalize_batch_score_result(raw, len(batch))
                    batch_scored = [apply_score_result(paper, items.get(
                        index, {}), section) for index, paper in enumerate(batch)]
                    batch_debug["provider"] = "qwen"
                    batch_debug["rawOutput"] = raw
                else:
                    batch_scored, raw = self.fallback.score_batch(
                        batch, section)
                    batch_debug["provider"] = "mock"
                    batch_debug["rawOutput"] = raw
            except Exception as error:
                warnings.append(f"LLM 批量粗排失败，使用 Mock fallback：{error}")
                batch_scored, raw = self.fallback.score_batch(batch, section)
                batch_debug["provider"] = "mock-after-error"
                batch_debug["error"] = str(error)
                batch_debug["rawOutput"] = raw
            batch_debug["scoredPapers"] = [
                paper_debug_summary(paper) | {
                    "scores": paper.get("scores", {}),
                }
                for paper in batch_scored
            ]
            batches.append(batch_debug)
            scored.extend(batch_scored)
        return scored

    def enrich_paper(
        self,
        paper: dict[str, Any],
        section: dict[str, Any],
        section_debug: dict[str, Any],
        warnings: list[str],
        *,
        pdf_path: Path | None = None,
    ) -> dict[str, Any]:
        enrich_debug = {
            "paper": paper_debug_summary(paper),
            "usedPdf": bool(pdf_path),
        }
        try:
            if self.enabled:
                if not pdf_path:
                    raise ValueError("missing PDF for second-stage reading")
                file_id = self._upload_pdf(pdf_path)
                raw = self._chat_json(
                    model=self.enrich_model,
                    prompt=enrichment_prompt(paper, section),
                    temperature=0.05,
                    file_id=file_id,
                )
                enriched = apply_enrichment_result(
                    paper, normalize_enrichment_result(raw))
                enrich_debug["provider"] = "qwen"
                enrich_debug["rawOutput"] = raw
            else:
                enriched, raw = self.fallback.enrich_paper(paper)
                enrich_debug["provider"] = "mock"
                enrich_debug["rawOutput"] = raw
        except Exception as error:
            warnings.append(
                f"LLM 精读生成失败，使用 Mock fallback：{paper.get('title', 'untitled')} ({error})")
            enriched, raw = self.fallback.enrich_paper(paper)
            enrich_debug["provider"] = "mock-after-error"
            enrich_debug["error"] = str(error)
            enrich_debug["rawOutput"] = raw
        enrich_debug["finalPaper"] = {
            "summarySections": enriched.get("summarySections", {}),
            "contentTags": enriched.get("contentTags", []),
            "researchParadigmTags": enriched.get("researchParadigmTags", []),
        }
        section_debug.setdefault("enrichOutputs", []).append(enrich_debug)
        return enriched

    def _chat_json(self, *, model: str, prompt: str, temperature: float, file_id: str = "") -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if file_id:
            messages.append(
                {"role": "system", "content": f"fileid://{file_id}"})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        raw = open_url(
            f"{self.api_base}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
            timeout=self.timeout_seconds,
        )
        response = json.loads(raw.decode("utf-8", errors="replace"))
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("chat response missing choices")
        message = choices[0].get("message", {}) if isinstance(
            choices[0], dict) else {}
        content = message.get("content") if isinstance(message, dict) else ""
        if isinstance(content, list):
            content = "\n".join(str(item.get("text", ""))
                                for item in content if isinstance(item, dict))
        if not isinstance(content, str) or not content.strip():
            raise ValueError("chat response missing content")
        return json_from_text(content)

    def _upload_pdf(self, path: Path | None) -> str:
        if not path:
            return ""
        boundary = f"----clifeast-digest-{hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:16]}"
        payload = path.read_bytes()
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="purpose"\r\n\r\n'
            "file-extract\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
        ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
        raw = open_url(
            f"{self.api_base}/files",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
            timeout=self.timeout_seconds,
        )
        response = json.loads(raw.decode("utf-8", errors="replace"))
        file_id = normalize_text(str(response.get("id", "")))
        if not file_id:
            raise ValueError("file upload response missing id")
        return file_id


def normalize_batch_score_result(result: dict[str, Any], count: int) -> dict[int, dict[str, Any]]:
    items = result.get("items")
    if not isinstance(items, list):
        items = result.get("papers")
    if not isinstance(items, list):
        items = []
    by_index: dict[int, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        if 0 <= index < count:
            by_index[index] = item
    return by_index


def batch_score_prompt(papers: list[dict[str, Any]], section: dict[str, Any]) -> str:
    payload = [
        {
            "index": index,
            "title": paper.get("title", ""),
            "abstract": paper.get("abstract", ""),
            "source": paper.get("source", ""),
            "date": paper.get("date", ""),
            "metadata": paper.get("metadata", {}),
        }
        for index, paper in enumerate(papers)
    ]
    section_id = str(section.get("id", ""))
    rubric = agt_score_rubric() if section_id == "recent-agt" else ai_score_rubric()
    return f"""
你是论文日报的批量筛选评分器。只能使用 title、abstract 和 metadata，不要虚构论文贡献。请输出严格 JSON，不要 Markdown。

栏目：{section.get("title", section.get("id", ""))}

{rubric}

硬性要求：
- 每篇论文只输出 index 和 scores。
- 不要输出总分、推荐语、解释、摘要、标签或任何额外判断。
- 所有分数需要整数。penalty 必须是 0 到 -5 的数。

输入 papers：
{json.dumps(payload, ensure_ascii=False)}

输出格式：
{score_output_schema(section_id)}
""".strip()


def ai_score_rubric() -> str:
    return """
recent-ai 评分，总基础分 30 分：
1. importance（0–6）：评估论文是否对应 AI 当前真正重要的趋势或问题。看它是否触及基础模型、agent、reasoning、alignment、data、evaluation、efficiency、multimodal、robotics、AI safety 等核心方向，或者是否解决现实中已经明显存在的痛点。若只是追热点、换场景、做小修补，分数应较低；若问题重要且有持续研究价值，给高分。
2. horizonValue（0–6）：评估论文是否能开拓视野。看它是否提出新问题、新设定、新任务、新 benchmark、新范式或新的理解角度。高分论文不一定马上最强，但应能让读者意识到一个值得关注的新方向。若题目模板化、生造任务、只是把已有方法套到冷门场景，分数应较低。
3. clarity（0–6）：评估问题、方法和贡献是否清楚。看摘要中是否能明确回答：它研究什么问题，为什么重要，提出了什么方法，得到什么结果。若 claim 清晰、贡献边界明确、和已有工作的区别明显，给高分；若表达含糊、堆术语、看不出具体贡献，给低分。
4. theoreticalDepth（0–8）：评估理论和技术深度。看是否有扎实的数学建模、定理、复杂度分析、收敛性证明、泛化分析、机制解释、信息论/优化/概率工具，或者对模型行为有非平凡理论解释。纯工程调参、经验堆叠、只报 benchmark 而无机制理解，分数较低。
5. overall（0–4）：给一个整体直觉判断，不必机械重复前几项。综合考虑论文是否值得点开、是否可能有长期影响、是否适合作为“每日 AI 视野拓展”材料。即使某些单项不高，但如果整体很有启发，可以适当给高；反之，单项看似不错但整体平庸，也可以压低。
6. penalty（0 到 -5）：扣除明显问题。若论文 buzzword 堆砌、纯刷榜、贡献边界不清、过度营销、实验不充分、只做很窄增量、任务设定牵强、标题宏大但摘要空泛，应扣分。轻微问题扣 -1/-2；如果核心贡献明显虚弱或像包装出来的题目，扣 -3 到 -5。
""".strip()


def agt_score_rubric() -> str:
    return """
recent-agt 评分：
先评定论文是否与 AGT/EconCS 强相关。如果关系很弱，scores 里所有字段都输出 0。
若强相关，agtRelevance 输出 6-10 分；否则输出 0。

基础分 30 分：
1. modelNaturalness（0–8）：评估问题和模型是否自然。看研究场景是否重要，是否真实存在 agents、信息、行动、偏好、约束和 incentive；模型是否抓住核心冲突，而不是为了套用博弈论而人为构造。若场景清楚、动机强、机制/市场/战略问题真实，给高分；若只是形式化包装或应用牵强，给低分。
2. theoreticalStrength（0–10）：评估理论贡献是否强。看主结果是否明确，是否给出有分量的 existence、algorithm、complexity、characterization、tight bound、impossibility、approximation guarantee 或 open problem resolution。结果越 sharp、越接近 tight、越能改变理解，分数越高；若只是简单推广、经验观察或结论模糊，分数较低。
3. guaranteeQuality（0–6）：评估保证和假设是否可靠。看 theorem 的 guarantee 是否强，适用范围是否广，假设是否自然、可检验、不过强。若在一般模型下给出清晰强保证，给高分；若依赖特殊分布、强对称性、过度简化、参数调优或不现实假设，降低分数。
4. readingValue（0–6）：评估读完是否有收获。看是否能学到可迁移的模型、技术、证明思路、算法框架、benchmark、related work 或新的研究问题。即使结果不是最强，只要方法有启发、和 AGT/EconCS/AI 研究有连接，也可给较高分；若读完只得到一个窄应用结论，分数较低。
5. penalty（0 到 -5）：扣除明显问题。若模型很人工、claim 夸大或含糊、假设过强、策略性只是装饰、实验/理论支撑不足、贡献只是小修小补或像 position paper，应扣分。轻微问题扣 -1/-2；核心设定或贡献明显不可靠扣 -3 到 -5。
6. aiRelevance：0-10 分。重点看：AI/LLM/agent 是否是论文的核心研究对象；AI 是否改变了原有的经济、博弈、市场、机制或信息结构；是否研究 AI agents 的战略行为，如协调、合谋、操纵、欺骗、议价、学习或竞争；结论是否对 AI 平台、AI 市场、AI 治理、安全、定价、合约或机制设计有直接意义；AI 是否作为核心研究工具，例如辅助证明、形式化、搜索、实验或 benchmark。若 AI 只是应用背景、实验工具或标题装饰，给 0–4 分；若 AI agents 的激励、市场、机制、战略行为或治理问题是核心，给 7–10 分；介于两者之间给 5–6 分。
7. agtRelevance（0 或 6–10）：评估论文与 AGT/EconCS 的强相关程度。若论文几乎不涉及 agents、incentives、strategic behavior、game theory、mechanism design、market design、auction、matching、fair division、social choice、equilibrium、pricing、information design、learning in games 等内容，直接给 0 分。若确实相关，则只能给 6–10 分：6-7 表示只是边缘相关或应用场景相关；8-9 表示有明确的博弈/机制/市场/均衡/激励结构；9–10 表示论文核心就是 AGT/EconCS 问题，模型、结果和贡献都围绕战略行为、机制设计、市场设计或经济计算展开。只输出原始相关度，不要用它计算最终分。
""".strip()


def score_output_schema(section_id: str) -> str:
    if section_id == "recent-agt":
        scores = {
            "modelNaturalness": 0,
            "theoreticalStrength": 0,
            "guaranteeQuality": 0,
            "readingValue": 0,
            "penalty": 0,
            "aiRelevance": 0,
            "agtRelevance": 0,
        }
    else:
        scores = {
            "importance": 0,
            "horizonValue": 0,
            "clarity": 0,
            "theoreticalDepth": 0,
            "overall": 0,
            "penalty": 0,
        }
    return json.dumps({"items": [{"index": 0, "scores": scores}]}, ensure_ascii=False, indent=2)


def enrichment_prompt(paper: dict[str, Any], section: dict[str, Any]) -> str:
    section_id = str(section.get("id", ""))
    rubric = agt_enrichment_rubric() if section_id == "recent-agt" else ai_enrichment_rubric()
    return f"""
你是论文日报的精读简介与标签生成器。请以附加的完整 PDF 为主要依据，只输出严格 JSON，不要 Markdown。

论文标题：{paper.get("title", "")}

有且仅有标题和 PDF 正文可供你参考。不要虚构 PDF 中没有的信息；如果 PDF 中没有足够证据支持某个判断，就保守表述，不要为了显得完整而补充常识性猜测。

{rubric}

输出要求：
- summarySections 是对象，包含且只包含 backgroundAndQuestion、modelAndSetup、contributionsAndResults、methodsAndTechniques、limitationsAndReadingValue 五个字段。
- 每个总结字段都用中文自然段输出，长度控制在 100-150 字左右，不要使用 Markdown、编号、列表或项目符号。
- 写作对象是“有基础但没读过这篇论文的读者”。每段都要先用通俗但准确的话讲清楚这一部分在回答什么问题，再引入必要的模型、术语和结果。不要把摘要写成论文摘要翻译、术语清单或评审表。
- 每段都应尽量形成清楚的解释链条：这篇文章为什么要研究这个问题、它如何把问题抽象成模型、结果说明了什么、作者为什么能证明或验证这些结果、读者能从中获得什么。重点不是复述原文，而是帮助读者快速理解论文的故事、逻辑和价值。
- 核心术语、机制名、模型名、均衡概念或算法名可以保留，但必须用简短语言说明它在论文中起什么作用。不要连续堆砌多个未解释的专业词。如果“完整覆盖术语”和“读者容易理解”发生冲突，优先保证读者容易理解，只保留理解论文主线必需的术语。
- 语言要自然、流畅、易读，不要过度口语化，也不要牺牲专业准确性。避免使用空泛模板句，例如“本文属于某某研究脉络”“具有重要理论意义”“实验充分证明”等；只有当这些判断有具体内容支撑时才写。
- researchParadigmTags：中文数组，最多 5 个，用来描述论文“怎么研究”，即研究范式或方法类型。优先使用稳定、可复用的标签，如理论推导、模型构建、机制设计、算法设计、复杂度分析、均衡分析、后悔分析、实验验证、基准评测、系统框架、数据集构建、综述/教程等。AGT/EconCS 论文重点关注理论、机制、均衡、算法与复杂度；AI/ML 论文重点关注模型、算法、实验、评测、数据与系统。
- contentTags：中文数组，最多 5 个，用来描述论文“研究什么”，即主题领域或问题对象。优先使用稳定、可复用的标签，如机制设计、拍卖理论、市场/匹配、公平性、信息设计、社会选择、博弈学习、多智能体系统、在线算法、大语言模型、生成式AI、强化学习、智能体、对齐、安全性、隐私/安全、鲁棒性、评测方法等。范式标签和内容标签不要混用；不确定时宁可少给，不要强行编造。
- Tag 的数量要适宜，首先需要囊括论文主线要点，但不要为了丰富而故意写多个。若论文只明显对应 2-3 个标签，就只输出 2-3 个。
- 不要输出其他额外字段。

输出格式：
{{
  "researchParadigmTags": ["..."],
  "contentTags": ["..."],
  "summarySections": {{
    "backgroundAndQuestion": "...",
    "modelAndSetup": "...",
    "contributionsAndResults": "...",
    "methodsAndTechniques": "...",
    "limitationsAndReadingValue": "..."
  }}
}}
""".strip()


def agt_enrichment_rubric() -> str:
    return """
请按 AGT / EconCS 论文口径组织五段。整体目标不是写评审表，而是帮助读者快速理解论文的核心问题、模型逻辑、主要结果和阅读价值。写作时可以保留必要的专业术语，但要优先保证读者能顺着论文的思路读下去。

1. 背景与问题：
这一段要回答“为什么要研究这个问题”。重点是讲清楚论文面对的理论现象、现实动机或已有研究缺口，而不是简单贴上“博弈论”“机制设计”“市场设计”等标签。可以说明它处在哪条研究脉络中，但应服务于理解问题本身。好的写法应让读者明白：作者为什么提出这个问题，它涉及什么激励、信息、策略互动、学习过程或资源分配困难，以及为什么这个问题不只是技术细节。

2. 模型与设定：
这一段要回答“作者如何把问题抽象成模型”。重点是让读者看见模型里的基本画面：有哪些参与者，他们掌握什么信息，可以采取什么行动，目标是什么，以及互动规则如何产生论文关心的困难。形式化元素如 agents、策略空间、效用函数、社会目标、机制规则、约束条件、均衡概念或学习过程都可以写，但不要只罗列定义。关键假设应说明其直观含义和建模作用。

3. 贡献与结果：
这一段要回答“论文真正证明或发现了什么”。重点不是列出所有定理，而是抓住最能代表论文新意的结果。可以包括新模型、新机制、新算法、新均衡刻画、近似保证、上下界、不可能性结果或 tight analysis。写作时应尽量说明这些结果为什么有意义：它们相比已有工作推进在哪里，是否揭示了反直觉现象，或者给出了新的经济、博弈或算法 insight。

4. 方法与技术：
这一段要回答“作者是怎么得到这些结果的”。重点是概括证明路线、技术直觉和关键分析结构，而不是复述推导细节。可以提到 LP/duality、potential function、reduction、fixed point、regret analysis、concentration、rounding、approximation、equilibrium analysis 等工具，但术语本身不是重点；更重要的是说明这些工具在论文中承担什么作用，例如刻画均衡、构造机制、证明存在性、建立界或处理不确定性。

5. 局限与阅读价值：
这一段要回答“这篇论文该如何评价、是否值得继续读”。局限应具体对应论文的核心模型和结果，而不是泛泛写“假设较强”或“适用范围有限”。可以讨论模型自然性、假设强度、结果适用范围、证明是否依赖特殊结构、机制是否容易实现、贡献是否偏增量等。最后应给出阅读价值判断，说明最值得读的是模型抽象、核心定理、证明技巧、机制设计、related work 还是开放问题。
""".strip()


def ai_enrichment_rubric() -> str:
    return """
请按 AI / ML 论文口径组织五段。整体目标不是翻译摘要或罗列实验结果，而是帮助读者快速理解论文解决什么问题、方法如何工作、结果说明什么，以及是否值得继续读。写作时可以保留必要的技术概念，但要避免把模型名、数据集名和指标堆成清单。

1. 背景与问题：
这一段要回答“为什么要做这篇论文”。重点是讲清楚论文面对的任务、现象或瓶颈，以及已有方法为什么还不够。可以说明它处在机器学习、生成式 AI、强化学习、表示学习、推理、对齐、评测或应用系统中的哪条脉络，但不要停留在领域归类。好的写法应让读者明白问题的真实难点来自哪里，例如数据、模型、训练、推理、泛化、评测、成本或安全性。

2. 模型与设定：
这一段要回答“论文具体研究了什么任务或实验设定”。重点是让读者理解输入是什么、输出是什么、模型或系统在训练和推理时大致做了什么，以及作者如何评价效果。可以写数据来源、模型结构、训练目标、推理流程、评价指标和实验环境，但不要只列名称。若论文改变了标准设定，例如提出新任务、新数据分布、新 benchmark 或新交互流程，应说明这种变化为什么重要。

3. 贡献与结果：
这一段要回答“论文带来了什么新东西”。重点是抓住最能代表论文价值的贡献，而不是平均罗列所有实验。可以包括新架构、新训练方法、新数据集、新 benchmark、新 scaling 现象、新评测结论或新系统设计。写作时应说明这些贡献解决了什么问题，主要结果是否有说服力，以及它们是否改变了我们对任务、模型、训练方法或评测方式的理解。

4. 方法与技术：
这一段要回答“作者的方法为什么可能有效”。重点是解释方法机制，而不是堆模块名。可以概括模型设计、训练目标、数据构造、优化策略、推理机制、实验协议和消融设计，但应尽量说明关键技术环节解决了什么瓶颈，和已有方法相比差别在哪里。对于实验论文，也要说明证据链如何支撑作者的 claim，而不是只写“实验表明效果更好”。

5. 局限与阅读价值：
这一段要回答“这篇论文的结论能信到什么程度，以及读者该读哪里”。局限应具体对应论文的核心 claim，而不是泛泛写“泛化性有限”或“实验不足”。可以讨论数据偏差、评测覆盖、baseline 强弱、消融是否充分、成本是否过高、适用场景是否有限、结论是否外推过度或安全风险是否遗漏。最后应给出阅读价值判断，说明最值得读的是问题设定、方法设计、实验分析、系统实现、benchmark、经验结论还是失败案例。
""".strip()


def parse_arxiv_entry(entry: ET.Element) -> dict[str, Any]:
    def text_at(path: str) -> str:
        found = entry.find(path, ARXIV_NS)
        return normalize_text(found.text if found is not None else "")

    url = text_at("atom:id").replace("http://", "https://")
    arxiv_id = arxiv_id_from_value(url)
    title = text_at("atom:title")
    abstract = text_at("atom:summary")
    published = text_at("atom:published")
    updated = text_at("atom:updated")
    authors = [normalize_text(author.findtext("atom:name", default="", namespaces=ARXIV_NS))
               for author in entry.findall("atom:author", ARXIV_NS)]
    categories = [normalize_text(category.attrib.get("term", ""))
                  for category in entry.findall("atom:category", ARXIV_NS)]
    primary = ""
    primary_node = entry.find("arxiv:primary_category", ARXIV_NS)
    if primary_node is not None:
        primary = normalize_text(primary_node.attrib.get("term", ""))
    return make_paper(
        title=title,
        authors=authors,
        date=published[:10],
        source="arXiv",
        url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else url,
        abstract=abstract,
        ids={"arxiv": arxiv_id} if arxiv_id else {},
        metadata={
            "provider": "arxiv",
            "categories": categories,
            "primaryCategory": primary,
            "published": published[:10],
            "updated": updated[:10],
        },
    )


def arxiv_query(category: str, digest_date: dt.date) -> str:
    target = digest_date - dt.timedelta(days=1)
    date_token = target.strftime("%Y%m%d")
    return f'cat:{category} AND submittedDate:"{date_token}0000 TO {date_token}2359"'


def fetch_arxiv_category(category: str, digest_date: dt.date, *, limit: int | None) -> tuple[int, list[dict[str, Any]], str]:
    query = arxiv_query(category, digest_date)
    page_size = 200 if limit is None else min(60, limit)
    fetched: list[dict[str, Any]] = []
    total = 0
    start = 0
    while True:
        max_results = page_size if limit is None else min(
            page_size, limit - len(fetched))
        if max_results <= 0:
            break
        params = urllib.parse.urlencode({
            "search_query": query,
            "start": start,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        })
        xml_text = fetch_text(f"{ARXIV_API_URL}?{params}", timeout=120)
        root = ET.fromstring(xml_text.encode("utf-8"))
        total_node = root.find("opensearch:totalResults", ARXIV_NS)
        if total_node is not None and total_node.text and total_node.text.isdigit():
            total = int(total_node.text)
        entries = [parse_arxiv_entry(entry)
                   for entry in root.findall("atom:entry", ARXIV_NS)]
        fetched.extend(entries)
        if not entries or (total and len(fetched) >= total) or (limit is not None and len(fetched) >= limit):
            break
        start += len(entries)
    return total or len(fetched), fetched, query


def fetch_arxiv_candidates(
    categories: list[str],
    digest_date: dt.date,
    *,
    limit: int | None,
) -> tuple[int, list[dict[str, Any]], dict[str, Any]]:
    fetched_by_category: dict[str, Any] = {}
    combined: list[dict[str, Any]] = []
    remaining = limit
    for category in categories:
        category_limit = remaining if limit is not None else None
        if category_limit is not None and category_limit <= 0:
            fetched_by_category[category] = {
                "query": "",
                "totalResults": 0,
                "fetchedCount": 0,
                "skippedBecauseLimitReached": True,
            }
            continue
        total, papers, query = fetch_arxiv_category(
            category, digest_date, limit=category_limit)
        fetched_by_category[category] = {
            "query": query,
            "totalResults": total,
            "fetchedCount": len(papers),
        }
        combined.extend(papers)
        if remaining is not None:
            remaining -= len(papers)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for paper in combined:
        arxiv_id = str(paper.get("ids", {}).get("arxiv", "")
                       ) if isinstance(paper.get("ids"), dict) else ""
        key = arxiv_id or normalize_title(str(paper.get("title", "")))
        if key and key not in seen:
            seen.add(key)
            deduped.append(paper)

    debug_payload = {
        "perCategory": fetched_by_category,
        "dedupedCount": len(deduped),
    }
    return sum(int(info.get("totalResults", 0)) for info in fetched_by_category.values()), deduped, debug_payload


def categories_for_section(section: dict[str, Any], digest_date: dt.date) -> tuple[list[str], str]:
    section_id = str(section.get("id", ""))
    if section_id == "recent-agt":
        raw_categories = section.get("categories")
        categories = [normalize_text(str(item)) for item in raw_categories] if isinstance(
            raw_categories, list) else []
        return categories or ["cs.GT", "econ.TH"], "all"
    raw_pool = section.get("categoryPool")
    pool = [normalize_text(str(item)) for item in raw_pool] if isinstance(
        raw_pool, list) else []
    if not pool:
        pool = AI_CATEGORY_POOL
    category = stable_rng(
        f"{digest_date.isoformat()}:{section_id}:category").choice(pool)
    return [category], category


def select_for_output(scored: list[dict[str, Any]], section: dict[str, Any]) -> list[dict[str, Any]]:
    scored = sorted(
        scored,
        key=lambda paper: float(paper.get("scores", {}).get(
            "total", 0.0)) if isinstance(paper.get("scores"), dict) else 0.0,
        reverse=True,
    )
    eligible = [
        paper for paper in scored
        if isinstance(paper.get("scores"), dict)
        and float(paper.get("scores", {}).get("total", 0.0)) >= SELECTION_MIN_SCORE
    ]
    return eligible[:SELECTION_MAX_ITEMS]


def build_recent_arxiv_section(
    section: dict[str, Any],
    digest_date: dt.date,
    llm: LLMClient,
    debug: dict[str, Any],
    warnings: list[str],
    *,
    no_network: bool,
) -> list[dict[str, Any]]:
    section_id = str(section.get("id", "recent-arxiv"))
    section_debug = debug_section(debug, section_id)
    categories, category_note = categories_for_section(section, digest_date)
    limit = None if section_id == "recent-agt" else int(
        section.get("fetchLimit", 50))
    target_date = (digest_date - dt.timedelta(days=1)).isoformat()
    if section_id == "recent-ai" and category_note != "all":
        section["_renderTitle"] = f"{section.get('title', section_id)}（{category_note}）"
    print(
        f"[digest] {section_id}: categories {', '.join(categories)}; target {target_date}")
    section_debug.update({
        "targetDate": target_date,
        "categories": categories,
        "categorySelection": category_note,
        "fetchLimit": limit,
    })
    if no_network:
        warnings.append(
            f"{section.get('title', section_id)} 跳过：--no-network 下不抓取 arXiv")
        return []
    try:
        total, candidates, fetch_debug = fetch_arxiv_candidates(
            categories, digest_date, limit=limit)
    except Exception as error:
        warnings.append(
            f"{section.get('title', section_id)} arXiv 抓取失败：{error}")
        return []
    section_debug["arxivFetch"] = fetch_debug
    section_debug["arxivTotalResults"] = total
    section_debug["fetchedCount"] = len(candidates)
    section_debug["fetchedPapers"] = [paper_debug_summary(
        paper) | {"abstract": paper.get("abstract", "")} for paper in candidates]
    if not candidates:
        print(f"[digest] {section_id}: no arXiv papers")
        return []

    scored = llm.score_papers(candidates, section, section_debug, warnings)
    section_debug["allScoredPapers"] = [
        paper_debug_summary(paper) | {
            "scores": paper.get("scores", {}),
        }
        for paper in scored
    ]
    selected = select_for_output(scored, section)
    section_debug["selectedForOutput"] = [
        paper_debug_summary(paper) | {
            "scores": paper.get("scores", {}),
        }
        for paper in selected
    ]
    print(
        f"[digest] {section_id}: fetched {len(candidates)}, selected {len(selected)}")
    enriched: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="clifeast-digest-pdf-") as temp_dir:
        temp_path = Path(temp_dir)
        for paper in selected:
            pdf_path = None
            if llm.enabled:
                pdf_url = arxiv_pdf_url_for_paper(paper)
                if pdf_url:
                    try:
                        pdf_path = download_pdf(
                            pdf_url, temp_path, f"{arxiv_id_from_value(pdf_url) or 'arxiv'}.pdf")
                    except Exception as error:
                        warnings.append(
                            f"PDF 下载失败，第二阶段改用标题生成：{paper.get('title', 'untitled')} ({error})")
                else:
                    warnings.append(
                        f"缺少 arXiv PDF URL，第二阶段改用标题生成：{paper.get('title', 'untitled')}")
            enriched.append(llm.enrich_paper(
                paper, section, section_debug, warnings, pdf_path=pdf_path))
    return enriched


def validate_sections(payload: Any, warnings: list[str]) -> list[dict[str, Any]]:
    raw_sections = payload.get("sections") if isinstance(
        payload, dict) else None
    if not isinstance(raw_sections, list):
        warnings.append("content/digest/sections.json missing sections list")
        return []
    sections = [
        section for section in raw_sections if isinstance(section, dict)]
    allowed = {"recent-agt", "recent-ai"}
    filtered = [section for section in sections if str(
        section.get("id", "")) in allowed]
    skipped = [str(section.get("id", "")) for section in sections if str(
        section.get("id", "")) not in allowed]
    if skipped:
        warnings.append(f"已忽略非 recent arXiv 栏目：{', '.join(skipped)}")
    return filtered


def build_payload(
    digest_date: dt.date,
    *,
    no_network: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    warnings: list[str] = []
    sections = validate_sections(
        load_json(SECTIONS_FILE, {"sections": []}), warnings)
    debug: dict[str, Any] = {
        "date": digest_date.isoformat(),
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sections": {},
        "warnings": warnings,
    }
    llm = LLMClient(no_network=no_network)
    rendered_sections: list[dict[str, Any]] = []

    for section in sections:
        section_id = str(section.get("id", ""))
        try:
            papers = build_recent_arxiv_section(
                section, digest_date, llm, debug, warnings, no_network=no_network)
        except Exception as error:
            title = str(section.get("title", section_id or "Untitled section"))
            warnings.append(f"{title} 生成失败：{error}")
            papers = []
        title = str(section.get("_renderTitle") or section.get(
            "title", section_id or "Untitled section"))
        rendered_sections.append({
            "id": section_id,
            "title": title,
            "source": "arxiv-llm-ranked",
            "papers": papers,
        })

    payload = {
        "date": digest_date.isoformat(),
        "pipelineVersion": PIPELINE_VERSION,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "warnings": warnings,
        "llm": {
            "enabled": llm.enabled,
            "provider": "qwen" if llm.enabled else "mock",
            "scoreModel": llm.score_model if llm.enabled else "mock",
            "enrichModel": llm.enrich_model if llm.enabled else "mock",
        },
        "scoreLabels": SCORE_LABELS,
        "sections": rendered_sections,
    }
    debug["warnings"] = warnings
    debug["sectionCounts"] = {section["id"]: len(
        section["papers"]) for section in rendered_sections}
    return payload, debug


def configured_section_ids() -> set[str]:
    sections = load_json(SECTIONS_FILE, {"sections": []}).get("sections", [])
    if not isinstance(sections, list):
        return set()
    return {str(section.get("id", "")) for section in sections if isinstance(section, dict)}


def output_matches_current_config(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    sections = payload.get("sections")
    if not isinstance(sections, list):
        return False
    if payload.get("pipelineVersion") != PIPELINE_VERSION:
        return False
    current = configured_section_ids()
    return {str(section.get("id", "")) for section in sections if isinstance(section, dict)} == current


def write_digest(payload: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dated_path = DATA_DIR / f"{payload['date']}.json"
    today_path = DATA_DIR / "today.json"
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    dated_path.write_text(rendered, encoding="utf-8")
    today_path.write_text(rendered, encoding="utf-8")
    print(f"[digest] wrote {dated_path.relative_to(ROOT)}")
    print(f"[digest] wrote {today_path.relative_to(ROOT)}")
    for warning in payload.get("warnings", []):
        print(f"[digest] warning: {warning}")


def write_debug(debug: dict[str, Any], digest_date: dt.date) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    write_json(DEBUG_DIR / f"run-{digest_date.isoformat()}.json", debug)


def write_digest_index() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dates = sorted(
        path.stem
        for path in DATA_DIR.glob("*.json")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem)
    )
    write_json(DIGEST_INDEX_FILE, {"dates": dates[::-1]})


def build_digest(
    digest_date: dt.date,
    *,
    force: bool = False,
    no_network: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    state = load_state()
    date_key = digest_date.isoformat()
    dated_path = DATA_DIR / f"{date_key}.json"
    run_state = state.get("runs", {}).get(
        date_key) if isinstance(state.get("runs"), dict) else None

    if not force and isinstance(run_state, dict) and run_state.get("status") == "completed" and dated_path.exists():
        payload = load_json(dated_path, {})
        if output_matches_current_config(payload):
            if not dry_run:
                (DATA_DIR / "today.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            print(
                f"[digest] {date_key} already completed; reused existing JSON. Use --force to rebuild.")
            return payload
        print(
            f"[digest] {date_key} completed output is stale; rebuilding with current sections.")

    payload, debug = build_payload(digest_date, no_network=no_network)

    if dry_run:
        print(f"[digest] dry-run complete for {date_key}: " +
              ", ".join(f"{section['id']}={len(section['papers'])}" for section in payload.get("sections", [])))
        return payload

    write_digest(payload)
    write_digest_index()
    try:
        write_debug(debug, digest_date)
    except Exception as error:
        print(f"[digest] warning: debug write failed: {error}")
    runs = state.setdefault("runs", {})
    runs[date_key] = {
        "status": "completed",
        "completedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sectionCounts": {section["id"]: len(section["papers"]) for section in payload.get("sections", [])},
    }
    save_state(state)
    print(f"[digest] wrote {STATE_FILE.relative_to(ROOT)}")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the static /digest/ JSON payload.")
    parser.add_argument(
        "--date", default="", help="Digest date in YYYY-MM-DD format. Defaults to today in --timezone.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE,
                        help=f"IANA timezone used when --date is omitted. Defaults to {DEFAULT_TIMEZONE}.")
    parser.add_argument("--force", action="store_true",
                        help="Re-run a completed date and rebuild JSON/state.")
    parser.add_argument("--no-network", action="store_true",
                        help="Do not perform HTTP requests; useful for smoke tests.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build in memory without writing JSON, debug, or state files.")
    return parser.parse_args()


def date_from_args(args: argparse.Namespace) -> dt.date:
    if args.date:
        return dt.date.fromisoformat(args.date)
    try:
        timezone = ZoneInfo(args.timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"Unknown timezone: {args.timezone}") from error
    return dt.datetime.now(timezone).date()


def main() -> None:
    args = parse_args()
    build_digest(
        date_from_args(args),
        force=args.force,
        no_network=args.no_network,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
