"""Question answering over one person's locally collected knowledge base."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Set
from urllib.parse import urlparse

from ..models import Document, Person
from .base import LLMProvider, LLMProviderError


QA_SYSTEM = """你是人物知识库的问询编辑。只根据提供的本地人物档案和资料片段回答，不使用模型自身记忆补充事实。直接回答用户的问题，不模仿人物本人说话。材料不足时明确说明当前知识库没有足够信息，并为补充研究生成少量精确的网页搜索词。输出纯 JSON，不显示内部检索、评分或置信度术语。"""


def _query_terms(question: str) -> List[str]:
    latin = [item.casefold() for item in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.+-]{1,}", question)]
    cjk_runs = re.findall(r"[\u3400-\u9fff]{2,}", question)
    cjk = []
    for run in cjk_runs:
        cjk.extend(run[index : index + 2] for index in range(len(run) - 1))
    return list(dict.fromkeys(latin + cjk))[:24]


def _document_score(document: Document, terms: List[str]) -> int:
    title = document.title.casefold()
    content = document.content.casefold()
    return sum((8 if term in title else 0) + min(content.count(term), 5) for term in terms)


def _excerpt(document: Document, terms: List[str], limit: int = 5200) -> str:
    content = document.content
    lower = content.casefold()
    positions = sorted({lower.find(term) for term in terms if lower.find(term) >= 0})
    if not positions:
        return content[:limit]
    pieces: List[str] = []
    remaining = limit
    for position in positions[:3]:
        start = max(0, position - 650)
        end = min(len(content), position + 1500, start + remaining)
        piece = content[start:end].strip()
        if piece:
            pieces.append(piece)
            remaining -= len(piece)
        if remaining <= 300:
            break
    return "\n…\n".join(pieces)[:limit]


def validate_answer(raw: Dict[str, Any], allowed_urls: Iterable[str]) -> Dict[str, Any]:
    allowed: Set[str] = set(allowed_urls)
    answer = str(raw.get("answer") or "").strip()
    if not answer:
        raise LLMProviderError("模型没有返回可用答案")
    urls = raw.get("source_urls", [])
    source_urls = []
    if isinstance(urls, list):
        source_urls = [str(url) for url in urls if str(url) in allowed]
    raw_queries = raw.get("search_queries", [])
    search_queries: List[str] = []
    if isinstance(raw_queries, list):
        for value in raw_queries:
            query = " ".join(str(value).split()).strip()
            if query and len(query) <= 220 and query not in search_queries:
                search_queries.append(query)
            if len(search_queries) >= 4:
                break
    return {
        "answer": answer,
        "source_urls": list(dict.fromkeys(source_urls)),
        "insufficient_knowledge": bool(raw.get("insufficient_knowledge", False)),
        "search_queries": search_queries,
    }


def fallback_research_queries(
    person: Person, report: Dict[str, Any], question: str
) -> List[str]:
    """Build conservative queries when the model flags a gap but omits a plan."""

    queries = ['"%s" %s' % (person.name, " ".join(question.split()))]
    for profile in report.get("public_profiles", []):
        if not isinstance(profile, dict):
            continue
        url = str(profile.get("url") or "")
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        handle = parsed.path.strip("/").split("/", 1)[0]
        if host in {"x.com", "twitter.com"} and handle:
            queries.insert(0, "site:x.com/%s %s" % (handle, " ".join(question.split())))
            break
    return queries[:3]


class KnowledgeAnswerer:
    def __init__(self, provider: LLMProvider, max_documents: int = 6) -> None:
        self.provider = provider
        self.max_documents = max_documents

    def answer(
        self,
        person: Person,
        report: Dict[str, Any],
        documents: List[Document],
        question: str,
    ) -> Dict[str, Any]:
        if not documents:
            raise LLMProviderError("这个人物知识库还没有可问询的原始资料")
        terms = _query_terms(question)
        ranked = sorted(
            documents,
            key=lambda document: (_document_score(document, terms), document.published_at or ""),
            reverse=True,
        )
        selected = ranked[: self.max_documents]
        corpus = []
        for index, document in enumerate(selected, 1):
            corpus.append(
                "\n".join(
                    [
                        "[SOURCE %d]" % index,
                        "TITLE: %s" % document.title,
                        "URL: %s" % document.source_url,
                        "CONTENT:",
                        _excerpt(document, terms),
                    ]
                )
            )
        prompt = """研究对象：{name}
用户问题：{question}

请用与用户问题相同的语言回答。先给结论，再解释相关背景。不要把外部评价写成研究对象本人的观点。若资料无法直接回答，明确说当前知识库未收录足够材料，并说明已经能确认到的最接近信息，同时把 insufficient_knowledge 设为 true。

仅当 insufficient_knowledge 为 true 时，生成 2 至 4 条 search_queries，用来继续查找这个人物对该问题的直接表达：
- 查询必须同时限定人物身份和问题中的关键概念；
- 中英文人物或问题可同时给出中文与英文查询；
- 若档案中已有 X、博客或其他本人主页，可优先生成 site: 限定查询；
- search_queries 是搜索词，不得编造具体网页 URL。

如果现有资料足够回答，把 search_queries 留空。source_urls 只能使用下面资料中逐字出现的 URL。

返回结构：
{schema}

已有结构化档案：
{report}

最相关的原始资料：
{corpus}
""".format(
            name=person.name,
            question=question,
            schema=json.dumps(
                {
                    "answer": "直接回答",
                    "source_urls": ["只能使用输入 URL"],
                    "insufficient_knowledge": False,
                    "search_queries": [],
                },
                ensure_ascii=False,
            ),
            report=json.dumps(report, ensure_ascii=False)[:14000],
            corpus="\n\n".join(corpus),
        )
        raw = self.provider.generate_json(QA_SYSTEM, prompt)
        return validate_answer(raw, [document.source_url for document in selected])
