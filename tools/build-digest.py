#!/usr/bin/env python3
"""Build the static JSON payload for the /digest/ page.

The digest pipeline is intentionally small:
- no long-lived request, PDF, or LLM caches
- only data/digest/state.json persists cross-run business state
- data/digest/debug/run-YYYY-MM-DD.json is diagnostic only
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import html
import json
import os
import random
import re
import ssl
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[1]
SECTIONS_FILE = ROOT / "content" / "digest" / "sections.json"
DATA_DIR = ROOT / "data" / "digest"
STATE_FILE = DATA_DIR / "state.json"
DEBUG_DIR = DATA_DIR / "debug"

ARXIV_API_URL = "https://export.arxiv.org/api/query"
OPENALEX_API_URL = "https://api.openalex.org/works"
DEFAULT_LLM_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_SCORE_MODEL = "qwen-plus"
DEFAULT_QWEN_ENRICH_MODEL = "qwen-long"
DEFAULT_TIMEZONE = "America/Los_Angeles"
USER_AGENT = "clifeast-digest/0.3 (+https://clifeast.github.io/digest/)"

ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}

SCORE_KEYS = [
    "relevance",
    "novelty",
    "theoreticalDepth",
    "readability",
    "potentialImpact",
]
SCORE_LABELS = {
    "relevance": "相关性",
    "novelty": "新颖性",
    "theoreticalDepth": "理论深度",
    "readability": "可读性",
    "potentialImpact": "重要性/潜在影响",
    "total": "总分",
}
RECOMMENDATIONS = {"strong_read", "read", "skim", "skip"}
RECOMMENDATION_BY_SCORE = [
    (8.2, "strong_read"),
    (6.8, "read"),
    (5.2, "skim"),
    (0.0, "skip"),
]

DEFAULT_SCORE_WEIGHTS = {
    "relevance": 0.25,
    "novelty": 0.15,
    "theoreticalDepth": 0.30,
    "readability": 0.10,
    "potentialImpact": 0.20,
}

DEFAULT_ARXIV_POOLS = {
    "recent-agt": ["cs.GT", "cs.MA", "cs.AI"],
    "recent-ai": ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.RO", "cs.IR", "cs.NE", "cs.MA"],
}

CONTENT_TAG_RULES: list[tuple[str, list[str]]] = [
    ("机制设计", ["mechanism", "incentive", "truthful", "strategy-proof", "contract"]),
    ("拍卖/定价", ["auction", "bid", "pricing", "price", "reserve"]),
    ("均衡/博弈", ["equilibrium", "game", "nash", "zero-sum"]),
    ("市场/匹配", ["market", "matching", "allocation", "assignment"]),
    ("公平性/社会选择", ["fair", "fairness", "voting", "social choice", "committee"]),
    ("信息设计", ["information design", "persuasion", "signaling", "disclosure"]),
    ("在线学习", ["online learning", "bandit", "regret", "reinforcement learning"]),
    ("大语言模型", ["llm", "large language model", "language model", "transformer", "prompt"]),
    ("机器学习理论", ["learning theory", "sample complexity", "generalization", "optimization"]),
    ("深度学习", ["deep learning", "neural", "representation", "pre-training", "pretraining"]),
    ("隐私/安全", ["privacy", "security", "auditing", "synthetic data"]),
    ("多智能体", ["multi-agent", "multiagent", "agent", "agents"]),
]

PARADIGM_TAG_RULES: list[tuple[str, list[str]]] = [
    ("理论推导", ["theorem", "proof", "hardness", "complexity", "bound", "lower bound"]),
    ("算法设计", ["algorithm", "method", "framework", "optimization", "solver", "protocol"]),
    ("实验验证", ["experiment", "empirical", "benchmark", "simulation", "evaluation"]),
    ("系统框架", ["system", "platform", "toolkit", "architecture", "pipeline"]),
    ("综述/教程", ["survey", "review", "tutorial", "introduction", "primer"]),
]

AGT_ECONCS_HINTS = [
    "mechanism", "auction", "equilibrium", "game", "market", "matching",
    "fair division", "social choice", "incentive", "pricing", "allocation",
    "voting", "contract", "prophet", "secretary", "econcs", "econ cs",
]


class PageTextExtractor(HTMLParser):
    BLOCK_TAGS = {
        "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
        "figcaption", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
        "header", "li", "main", "nav", "ol", "p", "pre", "section",
        "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    }

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._lines: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.BLOCK_TAGS:
            self._flush()
        if tag == "li":
            self._chunks.append("* ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        text = html.unescape(data)
        if text.strip():
            self._chunks.append(text)

    def _flush(self) -> None:
        text = normalize_text(" ".join(self._chunks))
        self._chunks = []
        if text:
            self._lines.append(text)

    def get_lines(self) -> list[str]:
        self._flush()
        return self._lines


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    return round(min(10.0, max(0.0, number)), 1)


def recommendation_for_score(total: float) -> str:
    for threshold, recommendation in RECOMMENDATION_BY_SCORE:
        if total >= threshold:
            return recommendation
    return "skip"


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


def open_url(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None,
             method: str = "GET", timeout: int = 90) -> bytes:
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        return response.read()


def fetch_text(url: str, *, timeout: int = 90) -> str:
    return open_url(url, timeout=timeout).decode("utf-8", errors="replace")


def download_pdf(url: str, directory: Path, filename: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", filename).strip("-") or "paper.pdf"
    if not safe_name.endswith(".pdf"):
        safe_name += ".pdf"
    path = directory / safe_name
    path.write_bytes(open_url(url, timeout=180))
    return path


def default_state() -> dict[str, Any]:
    return {
        "version": 1,
        "classicAI": {"seenIds": []},
        "conferenceAGT": {"venues": {}},
        "runs": {},
    }


def normalize_state(value: Any) -> dict[str, Any]:
    state = value if isinstance(value, dict) else {}
    base = default_state()
    base.update(state)
    if not isinstance(base.get("classicAI"), dict):
        base["classicAI"] = {"seenIds": []}
    if not isinstance(base["classicAI"].get("seenIds"), list):
        base["classicAI"]["seenIds"] = []
    if not isinstance(base.get("conferenceAGT"), dict):
        base["conferenceAGT"] = {"venues": {}}
    if not isinstance(base["conferenceAGT"].get("venues"), dict):
        base["conferenceAGT"]["venues"] = {}
    if not isinstance(base.get("runs"), dict):
        base["runs"] = {}
    return base


def load_state() -> dict[str, Any]:
    return normalize_state(load_json(STATE_FILE, default_state()))


def save_state(state: dict[str, Any]) -> None:
    write_json(STATE_FILE, normalize_state(state))


def debug_event(debug: dict[str, Any], event: str, **fields: Any) -> None:
    debug.setdefault("events", []).append({"event": event, **fields})


def infer_rule_tags(text: str, rules: list[tuple[str, list[str]]], limit: int = 4) -> list[str]:
    lowered = text.lower()
    tags = [label for label, keywords in rules if any(keyword in lowered for keyword in keywords)]
    return tags[:limit]


def infer_content_tags(title: str, abstract: str) -> list[str]:
    return infer_rule_tags(f"{title} {abstract}", CONTENT_TAG_RULES) or ["AI/理论"]


def infer_paradigm_tags(title: str, abstract: str) -> list[str]:
    return infer_rule_tags(f"{title} {abstract}", PARADIGM_TAG_RULES) or ["方法研究"]


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


def abstract_preview(abstract: str, *, limit: int = 160) -> str:
    text = normalize_text(abstract)
    if not text:
        return "该条目暂无摘要，简介只能基于题目和来源做保守判断。"
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def normalize_doi(value: str | None) -> str:
    text = normalize_text(value).lower()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
    return text


def arxiv_id_from_value(value: str | None) -> str:
    text = normalize_text(value)
    match = re.search(r"(\d{4}\.\d{4,5})(?:v\d+)?", text)
    return match.group(1) if match else ""


def pdf_url_from_url(url: str) -> str:
    arxiv_id = arxiv_id_from_value(url)
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    if url.lower().endswith(".pdf"):
        return url
    return ""


def paper_identity_keys(paper: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    ids = paper.get("ids") if isinstance(paper.get("ids"), dict) else {}
    for key, prefix in (("arxiv", "arxiv"), ("openalex", "openalex"), ("doi", "doi")):
        value = normalize_text(str(ids.get(key, "")))
        if value:
            keys.append(f"{prefix}:{normalize_doi(value) if key == 'doi' else value}")
    url = normalize_text(str(paper.get("url", "")))
    if url:
        keys.append(f"url:{url.lower()}")
    title = normalize_title(str(paper.get("title", "")))
    if title:
        keys.append(f"title:{title}")
    return keys


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
    content_tags = infer_content_tags(title, abstract)
    paradigm_tags = infer_paradigm_tags(title, abstract)
    return {
        "title": title,
        "authors": [normalize_text(author) for author in (authors or []) if normalize_text(author)],
        "date": normalize_text(date),
        "source": normalize_text(source),
        "url": normalize_text(url),
        "abstract": abstract,
        "summaryZh": "",
        "reasonZh": "",
        "recommendation": "skim",
        "researchParadigmTags": paradigm_tags,
        "contentTags": content_tags,
        "tags": merge_tags(content_tags, paradigm_tags),
        "scores": {key: 0.0 for key in [*SCORE_KEYS, "total"]},
        "ids": ids or {},
        "metadata": metadata or {},
    }


def score_weights(section: dict[str, Any]) -> dict[str, float]:
    raw = section.get("scoreWeights") if isinstance(section.get("scoreWeights"), dict) else {}
    weights = dict(DEFAULT_SCORE_WEIGHTS)
    for key in SCORE_KEYS:
        if key in raw:
            try:
                weights[key] = float(raw[key])
            except (TypeError, ValueError):
                pass
    total = sum(weights.values()) or 1.0
    return {key: weights[key] / total for key in SCORE_KEYS}


def weighted_total(scores: dict[str, Any], section: dict[str, Any]) -> float:
    weights = score_weights(section)
    return clamp_score(sum(clamp_score(scores.get(key, 0)) * weights[key] for key in SCORE_KEYS))


def normalize_scores(raw: Any, section: dict[str, Any]) -> dict[str, float]:
    source = raw if isinstance(raw, dict) else {}
    if "potentialImpact" not in source and "importance" in source:
        source = {**source, "potentialImpact": source.get("importance")}
    scores = {key: clamp_score(source.get(key, 0.0)) for key in SCORE_KEYS}
    if "total" in source:
        scores["total"] = clamp_score(source.get("total"))
    else:
        scores["total"] = weighted_total(scores, section)
    if "importance" in source:
        scores["importance"] = clamp_score(source.get("importance"))
    return scores


def apply_score_result(paper: dict[str, Any], result: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
    updated = dict(paper)
    scores = normalize_scores(result.get("scores"), section)
    recommendation = normalize_text(str(result.get("recommendation", "")))
    if recommendation not in RECOMMENDATIONS:
        recommendation = recommendation_for_score(float(scores.get("total", 0.0)))
    updated["scores"] = scores
    updated["reasonZh"] = normalize_text(str(result.get("reasonZh", "")))
    updated["recommendation"] = recommendation
    if "isAGTOrEconCS" in result:
        metadata = dict(updated.get("metadata", {})) if isinstance(updated.get("metadata"), dict) else {}
        metadata["isAGTOrEconCS"] = bool(result.get("isAGTOrEconCS"))
        updated["metadata"] = metadata
    return updated


def apply_enrichment_result(paper: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    updated = dict(paper)
    content_tags = result.get("contentTags")
    paradigm_tags = result.get("researchParadigmTags")
    if isinstance(content_tags, list) and content_tags:
        updated["contentTags"] = [normalize_text(str(tag)) for tag in content_tags if normalize_text(str(tag))][:5]
    if isinstance(paradigm_tags, list) and paradigm_tags:
        updated["researchParadigmTags"] = [normalize_text(str(tag)) for tag in paradigm_tags if normalize_text(str(tag))][:5]
    summary = normalize_text(str(result.get("summaryZh", "")))
    reason = normalize_text(str(result.get("reasonZh", "")))
    if summary:
        updated["summaryZh"] = summary
    if reason:
        updated["reasonZh"] = reason
    updated["tags"] = merge_tags(updated.get("contentTags", []), updated.get("researchParadigmTags", []))
    return updated


class MockRanker:
    def score_batch(
        self,
        papers: list[dict[str, Any]],
        section: dict[str, Any],
        source_kind: str,
        *,
        include_agt_flag: bool = False,
    ) -> list[dict[str, Any]]:
        return [apply_score_result(paper, self._score_result(paper, section, include_agt_flag), section)
                for paper in papers]

    def enrich_paper(
        self,
        paper: dict[str, Any],
        section: dict[str, Any],
        source_kind: str,
        *,
        pdf_path: Path | None = None,
    ) -> dict[str, Any]:
        result = {
            "researchParadigmTags": infer_paradigm_tags(str(paper.get("title", "")), str(paper.get("abstract", ""))),
            "contentTags": infer_content_tags(str(paper.get("title", "")), str(paper.get("abstract", ""))),
            "summaryZh": self._summary(paper, source_kind, bool(pdf_path)),
            "reasonZh": self._reason(paper),
        }
        return apply_enrichment_result(paper, result)

    def _score_result(self, paper: dict[str, Any], section: dict[str, Any], include_agt_flag: bool) -> dict[str, Any]:
        text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
        seed = "|".join(paper_identity_keys(paper)) or normalize_title(str(paper.get("title", "")))
        jitter = stable_rng(seed).uniform(-0.4, 0.4)
        theory = 6.0 + 1.8 * any(word in text for word in ["theorem", "proof", "complexity", "bound", "equilibrium"])
        relevance = 6.0 + 1.3 * any(word in text for word in ["ai", "learning", "agent", "mechanism", "game", "market"])
        novelty = 6.2 + 0.8 * any(word in text for word in ["new", "novel", "first", "introduce"])
        readability = 7.0 - 0.8 * any(word in text for word in ["hardness", "ppad", "np-hard"])
        impact = 6.4 + 1.0 * any(word in text for word in ["foundation", "large language", "market", "privacy", "safety"])
        scores = normalize_scores({
            "relevance": relevance + jitter,
            "novelty": novelty + jitter,
            "theoreticalDepth": theory + jitter,
            "readability": readability,
            "potentialImpact": impact + jitter,
        }, section)
        result: dict[str, Any] = {
            "scores": scores,
            "reasonZh": "Mock 评分基于题目、摘要和少量启发式特征，仅用于无 LLM 时保持流程可运行。",
            "recommendation": recommendation_for_score(float(scores["total"])),
        }
        if include_agt_flag:
            result["isAGTOrEconCS"] = any(hint in text for hint in AGT_ECONCS_HINTS)
        return result

    def _summary(self, paper: dict[str, Any], source_kind: str, has_pdf: bool) -> str:
        title = normalize_text(str(paper.get("title", "")))
        abstract = abstract_preview(str(paper.get("abstract", "")), limit=240)
        if source_kind == "classic":
            return f"这是一篇适合作为经典 AI 阅读材料的论文。可从问题背景、核心方法、实验或理论贡献以及后续影响四个角度阅读。当前简介基于元数据生成：{abstract}"
        if source_kind == "conference":
            return f"会议条目《{title}》暂无完整论文内容时，只能根据题目和来源做初步介绍。建议后续以正式论文版本为准。"
        note = "PDF 已下载但当前使用 Mock fallback。" if has_pdf else "当前未读取 PDF。"
        return f"{abstract} {note}"

    def _reason(self, paper: dict[str, Any]) -> str:
        total = float(paper.get("scores", {}).get("total", 0.0)) if isinstance(paper.get("scores"), dict) else 0.0
        return f"该条目总分约 {total:.1f}，适合作为本栏目的候选阅读；无 LLM 时请把判断视为保守占位。"


class LLMClient:
    def __init__(self, *, no_network: bool) -> None:
        self.no_network = no_network
        self.api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_API_KEY") or os.environ.get("LLM_API_KEY")
        self.api_base = os.environ.get("QWEN_API_BASE", os.environ.get("LLM_API_BASE", DEFAULT_LLM_API_BASE)).rstrip("/")
        self.score_model = os.environ.get("QWEN_SCORE_MODEL", os.environ.get("LLM_SCORE_MODEL", DEFAULT_QWEN_SCORE_MODEL))
        self.enrich_model = os.environ.get("QWEN_ENRICH_MODEL", os.environ.get("LLM_ENRICH_MODEL", DEFAULT_QWEN_ENRICH_MODEL))
        self.timeout_seconds = int(os.environ.get("LLM_TIMEOUT_SECONDS", "180"))
        self.fallback = MockRanker()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) and not self.no_network

    def score_batch(
        self,
        papers: list[dict[str, Any]],
        section: dict[str, Any],
        source_kind: str,
        *,
        include_agt_flag: bool = False,
        warnings: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not papers:
            return []
        if not self.enabled:
            return self.fallback.score_batch(papers, section, source_kind, include_agt_flag=include_agt_flag)
        try:
            result = self._chat_json(
                model=self.score_model,
                prompt=batch_score_prompt(papers, section, source_kind, include_agt_flag=include_agt_flag),
                temperature=0.05,
            )
            by_index = normalize_batch_score_result(result, len(papers))
            scored = []
            for index, paper in enumerate(papers):
                scored.append(apply_score_result(paper, by_index.get(index, {}), section))
            return scored
        except Exception as error:
            if warnings is not None:
                warnings.append(f"LLM 批量粗排失败，使用 Mock fallback：{error}")
            return self.fallback.score_batch(papers, section, source_kind, include_agt_flag=include_agt_flag)

    def enrich_paper(
        self,
        paper: dict[str, Any],
        section: dict[str, Any],
        source_kind: str,
        *,
        pdf_path: Path | None = None,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return self.fallback.enrich_paper(paper, section, source_kind, pdf_path=pdf_path)
        try:
            file_id = self._upload_pdf(pdf_path) if pdf_path else ""
            result = self._chat_json(
                model=self.enrich_model,
                prompt=enrichment_prompt(paper, section, source_kind, has_pdf=bool(file_id)),
                temperature=0.05,
                file_id=file_id,
            )
            return apply_enrichment_result(paper, normalize_enrichment_result(result))
        except Exception as error:
            if warnings is not None:
                warnings.append(f"LLM 精读生成失败，使用 Mock fallback：{paper.get('title', 'untitled')} ({error})")
            return self.fallback.enrich_paper(paper, section, source_kind, pdf_path=pdf_path)

    def _chat_json(self, *, model: str, prompt: str, temperature: float, file_id: str = "") -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if file_id:
            messages.append({"role": "system", "content": f"fileid://{file_id}"})
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
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = message.get("content") if isinstance(message, dict) else ""
        if isinstance(content, list):
            content = "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
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


def normalize_enrichment_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "researchParadigmTags": result.get("researchParadigmTags", []),
        "contentTags": result.get("contentTags", result.get("tags", [])),
        "summaryZh": normalize_text(str(result.get("summaryZh", ""))),
        "reasonZh": normalize_text(str(result.get("reasonZh", ""))),
    }


def batch_score_prompt(
    papers: list[dict[str, Any]],
    section: dict[str, Any],
    source_kind: str,
    *,
    include_agt_flag: bool,
) -> str:
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
    agt_line = (
        "- 同时输出 isAGTOrEconCS: boolean，判断是否属于 algorithmic game theory、market design、mechanism design、social choice、econ-CS 或相邻理论方向。"
        if include_agt_flag else ""
    )
    return f"""
你是论文日报的第一阶段批量粗排器。只能使用 title 和 abstract/metadata，不要虚构贡献。请输出严格 JSON，不要 Markdown。

栏目：{section.get("title", section.get("id", ""))}
来源类型：{source_kind}
评分口径：专业读者/审稿人偏好。重视可读性、重要性、理论深度、新颖性和与栏目的契合度；理论贡献扎实的论文优先。
{agt_line}

每篇论文输出：
- index: 输入中的 index
- scores: relevance, novelty, theoreticalDepth, readability, potentialImpact, total，均为 0 到 10 分
- recommendation: strong_read / read / skim / skip
- reasonZh: 中文 1 句，说明评分依据

输入 papers：
{json.dumps(payload, ensure_ascii=False)}

输出格式：
{{
  "items": [
    {{
      "index": 0,
      "isAGTOrEconCS": true,
      "scores": {{
        "relevance": 0,
        "novelty": 0,
        "theoreticalDepth": 0,
        "readability": 0,
        "potentialImpact": 0,
        "total": 0
      }},
      "recommendation": "read",
      "reasonZh": "..."
    }}
  ]
}}
""".strip()


def enrichment_prompt(paper: dict[str, Any], section: dict[str, Any], source_kind: str, *, has_pdf: bool) -> str:
    material_note = "已附完整 PDF，请以 PDF 为主要依据。" if has_pdf else "未附 PDF，请只基于题目、摘要和元数据做保守介绍。"
    summary_requirement = "summaryZh 约 300 字中文，准确说明问题、方法、主要贡献和适合如何阅读。"
    if source_kind == "conference" and not paper.get("abstract"):
        summary_requirement = "summaryZh 用中文保守说明：会议列表暂无摘要，只能根据题目和来源初步判断，不要编造结果。"
    return f"""
你是论文日报的第二阶段精读介绍生成器。只输出严格 JSON，不要 Markdown。

栏目：{section.get("title", section.get("id", ""))}
来源类型：{source_kind}
材料说明：{material_note}
标题：{paper.get("title", "")}
作者：{", ".join(str(author) for author in paper.get("authors", []))}
日期：{paper.get("date", "")}
来源：{paper.get("source", "")}
URL：{paper.get("url", "")}
摘要：{paper.get("abstract", "") or "[abstract missing]"}
已有评分：{json.dumps(paper.get("scores", {}), ensure_ascii=False)}
元数据：{json.dumps(paper.get("metadata", {}), ensure_ascii=False)}

输出要求：
- {summary_requirement}
- reasonZh 用中文 1-2 句，说明为什么值得展示或阅读。
- researchParadigmTags 中文数组，最多 5 个，例如 理论推导、实验验证、算法设计、系统框架、综述/教程。
- contentTags 中文数组，最多 5 个，例如 机制设计、公平性、信息设计、市场/匹配、大语言模型、隐私/安全。
- 不要输出 scores，不要改变已有评分。

输出格式：
{{
  "researchParadigmTags": ["..."],
  "contentTags": ["..."],
  "summaryZh": "...",
  "reasonZh": "..."
}}
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
    pdf_url = ""
    for link in entry.findall("atom:link", ARXIV_NS):
        if link.attrib.get("type") == "application/pdf":
            pdf_url = normalize_text(link.attrib.get("href", "")).replace("http://", "https://")
            break
    if not pdf_url and arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return make_paper(
        title=title,
        authors=authors,
        date=published[:10],
        source=f"arXiv {primary or (categories[0] if categories else '')}".strip(),
        url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else url,
        abstract=abstract,
        ids={"arxiv": arxiv_id} if arxiv_id else {},
        metadata={
            "provider": "arxiv",
            "categories": categories,
            "primaryCategory": primary,
            "published": published[:10],
            "updated": updated[:10],
            "pdfUrl": pdf_url,
        },
    )


def fetch_arxiv_previous_day(category: str, digest_date: dt.date) -> tuple[int, list[dict[str, Any]]]:
    target = digest_date - dt.timedelta(days=1)
    date_token = target.strftime("%Y%m%d")
    query = f'cat:{category} AND submittedDate:"{date_token}0000 TO {date_token}2359"'
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": 500,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    xml_text = fetch_text(f"{ARXIV_API_URL}?{params}", timeout=120)
    root = ET.fromstring(xml_text.encode("utf-8"))
    total_node = root.find("opensearch:totalResults", ARXIV_NS)
    total = int(total_node.text) if total_node is not None and total_node.text and total_node.text.isdigit() else 0
    papers = [parse_arxiv_entry(entry) for entry in root.findall("atom:entry", ARXIV_NS)]
    return total or len(papers), papers


def choose_arxiv_category(section: dict[str, Any], digest_date: dt.date) -> str:
    raw_pool = section.get("categoryPool")
    pool = [normalize_text(str(item)) for item in raw_pool] if isinstance(raw_pool, list) else []
    if not pool:
        pool = DEFAULT_ARXIV_POOLS.get(str(section.get("id", "")), ["cs.AI"])
    return stable_rng(f"{digest_date.isoformat()}:{section.get('id', '')}:category").choice(pool)


def build_recent_arxiv_section(
    section: dict[str, Any],
    digest_date: dt.date,
    llm: LLMClient,
    debug: dict[str, Any],
    warnings: list[str],
    *,
    no_network: bool,
) -> list[dict[str, Any]]:
    section_id = str(section.get("id", "recent"))
    category = choose_arxiv_category(section, digest_date)
    debug_event(debug, "recent_arxiv_category", sectionId=section_id, category=category)
    print(f"[digest] {section_id}: arXiv category {category}, date {digest_date - dt.timedelta(days=1)}")
    if no_network:
        warnings.append(f"{section.get('title', section_id)} 跳过：--no-network 下不抓取 arXiv")
        return []
    try:
        candidate_count, candidates = fetch_arxiv_previous_day(category, digest_date)
    except Exception as error:
        warnings.append(f"{section.get('title', section_id)} arXiv 抓取失败：{error}")
        return []
    debug_event(debug, "recent_arxiv_candidates", sectionId=section_id, category=category,
                candidateCount=candidate_count, fetchedCount=len(candidates))
    if not candidates:
        print(f"[digest] {section_id}: no papers; likely arXiv quiet day for {category}")
        return []

    sample_threshold = int(section.get("sampleThreshold", 100))
    sample_size = max(50, min(100, int(section.get("sampleSize", 75))))
    sampled = list(candidates)
    if candidate_count > sample_threshold and len(candidates) > sample_size:
        rng = stable_rng(f"{digest_date.isoformat()}:{section_id}:sample")
        sampled = rng.sample(candidates, sample_size)
    debug_event(debug, "recent_arxiv_sampled", sectionId=section_id, sampledCount=len(sampled))

    scored = llm.score_batch(sampled, section, "arxiv", warnings=warnings)
    scored.sort(key=lambda paper: (
        float(paper.get("scores", {}).get("total", 0.0)) if isinstance(paper.get("scores"), dict) else 0.0,
        recommendation_rank(str(paper.get("recommendation", ""))),
    ), reverse=True)

    max_items = max(1, int(section.get("maxItems", 3)))
    min_score = float(section.get("minScore", 0.0))
    selected = [
        paper for paper in scored
        if str(paper.get("recommendation", "")) != "skip"
        and float(paper.get("scores", {}).get("total", 0.0)) >= min_score
    ][:max_items]
    print(f"[digest] {section_id}: selected {len(selected)} / {len(sampled)}")
    debug_event(debug, "recent_arxiv_selected", sectionId=section_id,
                selected=[paper.get("title", "") for paper in selected])

    enriched: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="clifeast-digest-pdf-") as temp_dir:
        temp_path = Path(temp_dir)
        for paper in selected:
            pdf_path = None
            pdf_url = normalize_text(str(paper.get("metadata", {}).get("pdfUrl", ""))) if isinstance(paper.get("metadata"), dict) else ""
            if pdf_url:
                try:
                    pdf_path = download_pdf(pdf_url, temp_path, f"{arxiv_id_from_value(pdf_url) or 'arxiv'}.pdf")
                except Exception as error:
                    warnings.append(f"PDF 下载失败，改用元数据简介：{paper.get('title', 'untitled')} ({error})")
            enriched.append(llm.enrich_paper(paper, section, "arxiv", pdf_path=pdf_path, warnings=warnings))
    return enriched


def recommendation_rank(value: str) -> int:
    return {"strong_read": 3, "read": 2, "skim": 1, "skip": 0}.get(value, 0)


def abstract_from_openalex(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    positions: dict[int, str] = {}
    for word, indexes in value.items():
        if not isinstance(indexes, list):
            continue
        for index in indexes:
            if isinstance(index, int):
                positions[index] = str(word)
    return normalize_text(" ".join(positions[index] for index in sorted(positions)))


def parse_openalex_work(work: dict[str, Any]) -> dict[str, Any] | None:
    title = normalize_text(str(work.get("display_name") or work.get("title") or ""))
    if not title:
        return None
    authors: list[str] = []
    for authorship in work.get("authorships", []) if isinstance(work.get("authorships"), list) else []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") if isinstance(authorship.get("author"), dict) else {}
        name = normalize_text(str(author.get("display_name", "")))
        if name:
            authors.append(name)
    doi = normalize_doi(str(work.get("doi", "")))
    primary = work.get("primary_location") if isinstance(work.get("primary_location"), dict) else {}
    pdf_url = normalize_text(str(primary.get("pdf_url", "")))
    landing_url = normalize_text(str(primary.get("landing_page_url", "")))
    source = "OpenAlex"
    source_obj = primary.get("source") if isinstance(primary.get("source"), dict) else {}
    if source_obj.get("display_name"):
        source = normalize_text(str(source_obj.get("display_name")))
    return make_paper(
        title=title,
        authors=authors,
        date=normalize_text(str(work.get("publication_date") or work.get("publication_year") or "")),
        source=source,
        url=landing_url or (f"https://doi.org/{doi}" if doi else normalize_text(str(work.get("id", "")))),
        abstract=abstract_from_openalex(work.get("abstract_inverted_index")),
        ids={
            "openalex": normalize_text(str(work.get("id", ""))),
            **({"doi": doi} if doi else {}),
        },
        metadata={
            "provider": "openalex",
            "citedByCount": work.get("cited_by_count", 0),
            "publicationYear": work.get("publication_year", ""),
            "pdfUrl": pdf_url,
        },
    )


def openalex_url(section: dict[str, Any], query: str) -> str:
    settings = section.get("openalex") if isinstance(section.get("openalex"), dict) else {}
    min_year = int(settings.get("minYear", 1950))
    max_year = int(settings.get("maxYear", dt.date.today().year))
    min_citations = int(settings.get("minCitations", 500))
    per_page = int(settings.get("perPage", 80))
    filters = [
        f"cited_by_count:>{min_citations}",
        f"default.search:{query}",
        f"publication_year:{min_year}-{max_year}",
        "type:article|review",
    ]
    params = {
        "filter": ",".join(filters),
        "sort": "cited_by_count:desc",
        "select": "id,doi,title,display_name,publication_date,publication_year,authorships,primary_location,cited_by_count,abstract_inverted_index,type,keywords,topics",
        "per_page": str(per_page),
    }
    mailto = os.environ.get("OPENALEX_MAILTO")
    api_key = os.environ.get("OPENALEX_API_KEY")
    if mailto:
        params["mailto"] = mailto
    if api_key:
        params["api_key"] = api_key
    return f"{OPENALEX_API_URL}?{urllib.parse.urlencode(params)}"


def fetch_openalex_candidates(section: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    queries = section.get("queries") if isinstance(section.get("queries"), list) else []
    for query in queries:
        url = openalex_url(section, normalize_text(str(query)))
        payload = json.loads(fetch_text(url, timeout=120))
        for work in payload.get("results", []) if isinstance(payload.get("results"), list) else []:
            if not isinstance(work, dict):
                continue
            paper = parse_openalex_work(work)
            if not paper:
                continue
            key = normalize_title(str(paper.get("title", "")))
            if key in seen_titles:
                continue
            seen_titles.add(key)
            candidates.append(paper)
        time.sleep(0.2)
    candidates.sort(key=lambda paper: int(paper.get("metadata", {}).get("citedByCount", 0))
                    if isinstance(paper.get("metadata"), dict) else 0, reverse=True)
    return candidates


def parse_curated_paper(value: dict[str, Any]) -> dict[str, Any] | None:
    title = normalize_text(str(value.get("title", "")))
    if not title:
        return None
    url = normalize_text(str(value.get("url", "")))
    arxiv_id = arxiv_id_from_value(url)
    return make_paper(
        title=title,
        authors=[str(author) for author in value.get("authors", [])] if isinstance(value.get("authors"), list) else [],
        date=normalize_text(str(value.get("date") or value.get("publicationYear") or "")),
        source=normalize_text(str(value.get("source", "Curated AI"))),
        url=url,
        abstract=normalize_text(str(value.get("abstract", ""))),
        ids={"arxiv": arxiv_id} if arxiv_id else {},
        metadata={
            "provider": "curated",
            "priority": value.get("priority", 0),
            "citedByCount": value.get("citedByCount", 0),
            "publicationYear": value.get("publicationYear", ""),
            "pdfUrl": pdf_url_from_url(url),
        },
    )


def curated_candidates(section: dict[str, Any]) -> list[dict[str, Any]]:
    raw = section.get("curatedPapers") if isinstance(section.get("curatedPapers"), list) else []
    papers = [paper for item in raw if isinstance(item, dict) for paper in [parse_curated_paper(item)] if paper]
    papers.sort(key=lambda paper: int(paper.get("metadata", {}).get("priority", 0))
                if isinstance(paper.get("metadata"), dict) else 0, reverse=True)
    return papers


def build_classic_ai_section(
    section: dict[str, Any],
    state: dict[str, Any],
    llm: LLMClient,
    debug: dict[str, Any],
    warnings: list[str],
    *,
    no_network: bool,
) -> list[dict[str, Any]]:
    seen_ids = state.setdefault("classicAI", {}).setdefault("seenIds", [])
    seen = set(str(item) for item in seen_ids)
    candidates: list[dict[str, Any]] = []
    openalex_error = ""
    if not no_network:
        try:
            candidates = fetch_openalex_candidates(section)
            debug_event(debug, "classic_openalex_candidates", count=len(candidates))
        except Exception as error:
            openalex_error = str(error)
            warnings.append(f"classic-ai OpenAlex 失败，改用 curated list：{error}")
    if not candidates:
        candidates = curated_candidates(section)
        debug_event(debug, "classic_curated_candidates", count=len(candidates), openalexError=openalex_error)

    selected: dict[str, Any] | None = None
    selected_keys: list[str] = []
    for paper in candidates:
        keys = paper_identity_keys(paper)
        if keys and not any(key in seen for key in keys):
            selected = paper
            selected_keys = keys
            break
    if not selected:
        print("[digest] classic-ai: no unseen paper")
        return []

    scores = normalize_scores({
        "relevance": 9.0,
        "novelty": 6.5,
        "theoreticalDepth": 8.0,
        "readability": 7.5,
        "potentialImpact": 9.5,
        "total": 8.4,
    }, section)
    selected["scores"] = scores
    selected["recommendation"] = "strong_read"
    selected["reasonZh"] = "经典论文轮换条目，优先考虑影响力和入门阅读价值。"

    with tempfile.TemporaryDirectory(prefix="clifeast-digest-pdf-") as temp_dir:
        pdf_path = None
        pdf_url = normalize_text(str(selected.get("metadata", {}).get("pdfUrl", ""))) if isinstance(selected.get("metadata"), dict) else ""
        if pdf_url and not no_network:
            try:
                pdf_path = download_pdf(pdf_url, Path(temp_dir), f"{selected_keys[0].split(':', 1)[-1]}.pdf")
            except Exception as error:
                warnings.append(f"classic-ai PDF 下载失败，改用元数据简介：{selected.get('title', 'untitled')} ({error})")
        selected = llm.enrich_paper(selected, section, "classic", pdf_path=pdf_path, warnings=warnings)

    for key in selected_keys:
        if key not in seen:
            seen_ids.append(key)
            seen.add(key)
    debug_event(debug, "classic_selected", title=selected.get("title", ""), seenKeys=selected_keys)
    print(f"[digest] classic-ai: selected {selected.get('title', '')}")
    return [selected]


def html_lines(markup: str) -> list[str]:
    parser = PageTextExtractor()
    parser.feed(markup)
    return [line for line in parser.get_lines() if line and not is_navigation_line(line)]


def is_navigation_line(line: str) -> bool:
    lowered = line.lower()
    ignored = {
        "menu", "close", "home", "program", "calls", "committees", "sponsorship",
        "participation", "register", "schedule", "privacy policy",
    }
    return lowered in ignored or lowered.startswith("skip to content")


def strip_affiliations(value: str) -> str:
    text = normalize_text(value)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\([^()]*\)", "", text)
    text = re.sub(r"\bAuthors?:", "", text, flags=re.IGNORECASE)
    return normalize_text(text)


def split_authors(value: str) -> list[str]:
    without_affiliations = strip_affiliations(value)
    parts = re.split(r"\s*;\s*|\s*,\s*", without_affiliations)
    authors: list[str] = []
    for part in parts:
        name = normalize_text(re.sub(r"\s+and\s+", " ", part))
        if name and not re.search(r"^(authors?|accepted papers)$", name, re.I):
            authors.append(name)
    return authors[:20]


def first_heading_index(lines: list[str], heading: str) -> int:
    heading_lower = normalize_text(heading).lower()
    if not heading_lower:
        return 0
    for index, line in enumerate(lines):
        if heading_lower in line.lower():
            return index + 1
    return 0


def looks_like_authors(line: str) -> bool:
    if not line or len(line) > 500:
        return False
    if re.match(r"^\d+\.", line) or line.startswith("* "):
        return False
    if re.search(r"\b(university|institute|college|research|google|microsoft|mit|stanford|berkeley)\b", line, re.I):
        return True
    return bool(re.search(r"[A-Z][a-z]+ [A-Z]", line))


def conference_paper(title: str, authors: list[str], venue: dict[str, Any]) -> dict[str, Any]:
    venue_name = normalize_text(str(venue.get("name", "Conference")))
    year = normalize_text(str(venue.get("year", "")))
    url = normalize_text(str(venue.get("url", "")))
    return make_paper(
        title=title,
        authors=authors,
        date=year,
        source=f"{venue_name} {year} accepted papers".strip(),
        url=url,
        abstract="",
        metadata={
            "provider": "conference-list",
            "venue": venue_name,
            "year": year,
            "listingUrl": url,
        },
    )


def parse_numbered_author_lines(lines: list[str], venue: dict[str, Any]) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    index = first_heading_index(lines, str(venue.get("heading", "")))
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^\d+\.\s+(.+)$", line)
        if not match:
            index += 1
            continue
        title = normalize_text(match.group(1))
        authors_line = ""
        if index + 1 < len(lines) and re.match(r"^Authors?:", lines[index + 1], re.I):
            authors_line = lines[index + 1]
            index += 1
        papers.append(conference_paper(title, split_authors(authors_line), venue))
        index += 1
    return papers


def parse_bullet_author_lines(lines: list[str], venue: dict[str, Any]) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    index = first_heading_index(lines, str(venue.get("heading", "")))
    while index < len(lines):
        line = lines[index]
        if not line.startswith("* "):
            index += 1
            continue
        title = normalize_text(line[2:])
        authors_line = lines[index + 1] if index + 1 < len(lines) and not lines[index + 1].startswith("* ") else ""
        papers.append(conference_paper(title, split_authors(authors_line), venue))
        index += 2
    return papers


def parse_pair_lines(lines: list[str], venue: dict[str, Any]) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    index = first_heading_index(lines, str(venue.get("heading", "")))
    stop_words = ["sponsors", "organizers", "important dates", "registration"]
    while index + 1 < len(lines):
        title = normalize_text(lines[index])
        if any(word in title.lower() for word in stop_words):
            break
        if not title or title.startswith("(") or title.startswith("#") or re.match(r"^\d+\.", title):
            index += 1
            continue
        authors_line = normalize_text(lines[index + 1])
        if looks_like_authors(authors_line):
            papers.append(conference_paper(title, split_authors(authors_line), venue))
            index += 2
        else:
            index += 1
    return papers


CONFERENCE_PARSERS: dict[str, Callable[[list[str], dict[str, Any]], list[dict[str, Any]]]] = {
    "numbered-author-lines": parse_numbered_author_lines,
    "bullet-author-lines": parse_bullet_author_lines,
    "pair-lines": parse_pair_lines,
}


def venue_group(venue: dict[str, Any]) -> str:
    explicit = normalize_text(str(venue.get("group", ""))).lower()
    if explicit:
        return explicit
    name = normalize_text(str(venue.get("name", ""))).upper()
    if name in {"EC", "WINE"}:
        return "market"
    if name in {"STOC", "FOCS", "SODA"}:
        return "tcs"
    if name in {"ICML", "ICLR", "NEURIPS", "NIPS"}:
        return "ai"
    return "tcs"


def choose_conference_venue(section: dict[str, Any], digest_date: dt.date) -> dict[str, Any] | None:
    venues = [
        venue for venue in section.get("venues", [])
        if isinstance(venue, dict) and venue.get("enabled", True) and normalize_text(str(venue.get("url", "")))
    ] if isinstance(section.get("venues"), list) else []
    if not venues:
        return None
    groups: dict[str, list[dict[str, Any]]] = {"market": [], "tcs": [], "ai": []}
    for venue in venues:
        groups.setdefault(venue_group(venue), []).append(venue)
    weights = [("market", 0.50), ("tcs", 0.25), ("ai", 0.25)]
    available = [(group, weight) for group, weight in weights if groups.get(group)]
    if not available:
        return stable_rng(f"{digest_date.isoformat()}:conference:any").choice(venues)
    rng = stable_rng(f"{digest_date.isoformat()}:conference:group")
    total = sum(weight for _, weight in available)
    pick = rng.random() * total
    upto = 0.0
    chosen_group = available[-1][0]
    for group, weight in available:
        upto += weight
        if pick <= upto:
            chosen_group = group
            break
    return stable_rng(f"{digest_date.isoformat()}:conference:{chosen_group}").choice(groups[chosen_group])


def fetch_conference_papers(venue: dict[str, Any]) -> list[dict[str, Any]]:
    parser_name = normalize_text(str(venue.get("parser", "pair-lines")))
    parser = CONFERENCE_PARSERS.get(parser_name)
    if parser is None:
        raise ValueError(f"unknown parser: {parser_name}")
    markup = fetch_text(str(venue.get("url", "")), timeout=120)
    return parser(html_lines(markup), venue)


def build_conference_section(
    section: dict[str, Any],
    digest_date: dt.date,
    state: dict[str, Any],
    llm: LLMClient,
    debug: dict[str, Any],
    warnings: list[str],
    *,
    no_network: bool,
) -> list[dict[str, Any]]:
    venue = choose_conference_venue(section, digest_date)
    if not venue:
        warnings.append("conference-agt 没有可用 venue")
        return []
    venue_name = normalize_text(str(venue.get("name", "Conference")))
    print(f"[digest] conference-agt: venue {venue_name}")
    if no_network:
        warnings.append("conference-agt 跳过：--no-network 下不抓取会议页面")
        return []
    try:
        papers = fetch_conference_papers(venue)
    except Exception as error:
        warnings.append(f"conference-agt 抓取 {venue_name} 失败：{error}")
        return []
    debug_event(debug, "conference_candidates", venue=venue_name, count=len(papers))
    if not papers:
        return []

    venue_states = state.setdefault("conferenceAGT", {}).setdefault("venues", {})
    venue_state = venue_states.setdefault(venue_name, {"cursor": 0})
    cursor = int(venue_state.get("cursor", 0))
    max_items = max(1, int(section.get("maxItems", 1)))
    max_explore = max(1, int(section.get("maxExplorePerRun", 12)))
    min_score = float(section.get("minScore", 0.0))
    direct = venue_group(venue) == "market" or bool(venue.get("includeAll"))
    selected: list[dict[str, Any]] = []
    explored = 0

    while cursor < len(papers) and len(selected) < max_items and (direct or explored < max_explore):
        paper = papers[cursor]
        cursor += 1
        explored += 1
        if direct:
            scored = llm.score_batch([paper], section, "conference", warnings=warnings)[0]
            selected.append(llm.enrich_paper(scored, section, "conference", warnings=warnings))
            continue

        scored = llm.score_batch([paper], section, "conference", include_agt_flag=True, warnings=warnings)[0]
        metadata = scored.get("metadata") if isinstance(scored.get("metadata"), dict) else {}
        is_relevant = bool(metadata.get("isAGTOrEconCS"))
        total = float(scored.get("scores", {}).get("total", 0.0)) if isinstance(scored.get("scores"), dict) else 0.0
        debug_event(debug, "conference_explored", venue=venue_name, title=scored.get("title", ""),
                    isAGTOrEconCS=is_relevant, total=total)
        if not is_relevant:
            continue
        if total < min_score:
            continue
        selected.append(llm.enrich_paper(scored, section, "conference", warnings=warnings))

    venue_state["cursor"] = cursor
    venue_state["updatedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    debug_event(debug, "conference_selected", venue=venue_name, cursor=cursor,
                explored=explored, selected=[paper.get("title", "") for paper in selected])
    print(f"[digest] conference-agt: selected {len(selected)}, cursor {cursor}/{len(papers)}")
    return selected


def validate_sections(payload: Any, warnings: list[str]) -> list[dict[str, Any]]:
    raw_sections = payload.get("sections") if isinstance(payload, dict) else None
    if not isinstance(raw_sections, list):
        warnings.append("content/digest/sections.json missing sections list")
        return []
    sections = [section for section in raw_sections if isinstance(section, dict)]
    if len(sections) != len(raw_sections):
        warnings.append("部分 digest section 不是对象，已忽略")
    return sections


def build_payload(
    digest_date: dt.date,
    *,
    state: dict[str, Any],
    no_network: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    warnings: list[str] = []
    sections = validate_sections(load_json(SECTIONS_FILE, {"sections": []}), warnings)
    debug: dict[str, Any] = {
        "date": digest_date.isoformat(),
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "events": [],
    }
    llm = LLMClient(no_network=no_network)
    rendered_sections: list[dict[str, Any]] = []

    for section in sections:
        section_id = str(section.get("id", ""))
        source = str(section.get("source", ""))
        title = str(section.get("title", section_id or "Untitled section"))
        try:
            if source == "arxiv-llm-ranked" or section_id in {"recent-agt", "recent-ai"}:
                papers = build_recent_arxiv_section(section, digest_date, llm, debug, warnings, no_network=no_network)
            elif source == "classic-ai" or section_id in {"classic-ai", "authoritative-ai"}:
                papers = build_classic_ai_section(section, state, llm, debug, warnings, no_network=no_network)
            elif source == "conference-list" or section_id == "conference-agt":
                papers = build_conference_section(section, digest_date, state, llm, debug, warnings, no_network=no_network)
            else:
                warnings.append(f'栏目 "{section_id}" 使用未知来源：{source}')
                papers = []
        except Exception as error:
            warnings.append(f"{title} 生成失败：{error}")
            papers = []
        rendered_sections.append({
            "id": section_id,
            "title": title,
            "source": source,
            "papers": papers,
        })

    payload = {
        "date": digest_date.isoformat(),
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "warnings": warnings,
        "llm": {
            "enabled": llm.enabled,
            "provider": "qwen" if llm.enabled else "mock",
            "scoreModel": llm.score_model if llm.enabled else "mock",
            "enrichModel": llm.enrich_model if llm.enabled else "mock",
            "cache": "disabled",
        },
        "scoreLabels": SCORE_LABELS,
        "sections": rendered_sections,
    }
    debug["warnings"] = warnings
    debug["sectionCounts"] = {section["id"]: len(section["papers"]) for section in rendered_sections}
    return payload, debug


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
    run_state = state.get("runs", {}).get(date_key) if isinstance(state.get("runs"), dict) else None

    if not force and isinstance(run_state, dict) and run_state.get("status") == "completed" and dated_path.exists():
        payload = load_json(dated_path, {})
        if not dry_run:
            (DATA_DIR / "today.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(f"[digest] {date_key} already completed; reused existing JSON. Use --force to advance state again.")
        return payload

    working_state = copy.deepcopy(state)
    payload, debug = build_payload(digest_date, state=working_state, no_network=no_network)

    if dry_run:
        print(f"[digest] dry-run complete for {date_key}: " +
              ", ".join(f"{section['id']}={len(section['papers'])}" for section in payload.get("sections", [])))
        return payload

    write_digest(payload)
    try:
        write_debug(debug, digest_date)
    except Exception as error:
        print(f"[digest] warning: debug write failed: {error}")
    runs = working_state.setdefault("runs", {})
    runs[date_key] = {
        "status": "completed",
        "completedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sectionCounts": {section["id"]: len(section["papers"]) for section in payload.get("sections", [])},
    }
    save_state(working_state)
    print(f"[digest] wrote {STATE_FILE.relative_to(ROOT)}")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the static /digest/ JSON payload.")
    parser.add_argument("--date", default="", help="Digest date in YYYY-MM-DD format. Defaults to today in --timezone.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help=f"IANA timezone used when --date is omitted. Defaults to {DEFAULT_TIMEZONE}.")
    parser.add_argument("--force", action="store_true", help="Re-run a completed date and allow state to advance again.")
    parser.add_argument("--no-network", action="store_true", help="Do not perform HTTP requests; useful for smoke tests.")
    parser.add_argument("--dry-run", action="store_true", help="Build in memory without writing JSON, debug, or state files.")
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
