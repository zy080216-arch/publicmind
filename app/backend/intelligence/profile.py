"""Build a reader-facing person dossier from collected public documents."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Set

from ..models import Document, Person, Source
from .base import LLMProvider, LLMProviderError


PROFILE_SYSTEM = """你是一名严谨的人物研究编辑。你的任务不是模仿研究对象说话，而是根据提供的公开资料，回答两个问题：这个人做过什么；这个人发表过哪些主要观点。只使用输入资料，不补写常识，不虚构日期、经历或观点。输出纯 JSON。正文面向第一次了解此人的普通读者，清晰、全面、避免暴露内部评分、置信度、抓取或审核术语。"""


def _strings(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _source_urls(value: Any, allowed: Set[str]) -> List[str]:
    return [url for url in _strings(value) if url in allowed]


def validate_profile(raw: Dict[str, Any], allowed_urls: Iterable[str], person_name: str) -> Dict[str, Any]:
    allowed = set(allowed_urls)
    result: Dict[str, Any] = {
        "title": str(raw.get("title") or "%s 人物全景" % person_name).strip(),
        "overview": str(raw.get("overview") or "").strip(),
        "identity": _strings(raw.get("identity")),
        "accomplishments": [],
        "viewpoint_topics": [],
        "viewpoint_evolution": [],
        "timeline": [],
        "external_views": [],
    }
    for item in raw.get("accomplishments", []) if isinstance(raw.get("accomplishments"), list) else []:
        if not isinstance(item, dict) or not str(item.get("title", "")).strip():
            continue
        result["accomplishments"].append(
            {
                "title": str(item.get("title", "")).strip(),
                "description": str(item.get("description", "")).strip(),
                "period": str(item.get("period", "")).strip(),
                "source_urls": _source_urls(item.get("source_urls"), allowed),
            }
        )
    for topic in raw.get("viewpoint_topics", []) if isinstance(raw.get("viewpoint_topics"), list) else []:
        if not isinstance(topic, dict) or not str(topic.get("name", "")).strip():
            continue
        points = []
        for point in topic.get("points", []) if isinstance(topic.get("points"), list) else []:
            if not isinstance(point, dict) or not str(point.get("statement", "")).strip():
                continue
            points.append(
                {
                    "statement": str(point.get("statement", "")).strip(),
                    "explanation": str(point.get("explanation", "")).strip(),
                    "source_urls": _source_urls(point.get("source_urls"), allowed),
                }
            )
        result["viewpoint_topics"].append(
            {
                "name": str(topic.get("name", "")).strip(),
                "summary": str(topic.get("summary", "")).strip(),
                "points": points,
            }
        )
    for item in raw.get("timeline", []) if isinstance(raw.get("timeline"), list) else []:
        if not isinstance(item, dict) or not str(item.get("event", "")).strip():
            continue
        result["timeline"].append(
            {
                "date": str(item.get("date", "日期不详")).strip(),
                "event": str(item.get("event", "")).strip(),
                "source_urls": _source_urls(item.get("source_urls"), allowed),
            }
        )
    for item in raw.get("viewpoint_evolution", []) if isinstance(raw.get("viewpoint_evolution"), list) else []:
        if not isinstance(item, dict) or not str(item.get("summary", "")).strip():
            continue
        result["viewpoint_evolution"].append(
            {
                "period": str(item.get("period", "时间不详")).strip(),
                "summary": str(item.get("summary", "")).strip(),
                "source_urls": _source_urls(item.get("source_urls"), allowed),
            }
        )
    for item in raw.get("external_views", []) if isinstance(raw.get("external_views"), list) else []:
        if not isinstance(item, dict) or not str(item.get("summary", "")).strip():
            continue
        result["external_views"].append(
            {
                "summary": str(item.get("summary", "")).strip(),
                "source_urls": _source_urls(item.get("source_urls"), allowed),
            }
        )
    if not result["overview"] and not result["accomplishments"] and not result["viewpoint_topics"]:
        raise LLMProviderError("模型没有生成可用的人物报告内容")
    return result


class ProfileBuilder:
    def __init__(self, provider: LLMProvider, max_documents: int = 18, chars_per_document: int = 9000) -> None:
        self.provider = provider
        self.max_documents = max_documents
        self.chars_per_document = chars_per_document

    def build(
        self,
        person: Person,
        sources: List[Source],
        documents: List[Document],
        language_mode: str = "zh",
    ) -> Dict[str, Any]:
        if not documents:
            raise LLMProviderError("没有可用于生成人物报告的文档")
        selected = documents[: self.max_documents]
        corpus = []
        for index, document in enumerate(selected, 1):
            corpus.append(
                "\n".join(
                    [
                        "[DOCUMENT %d]" % index,
                        "TITLE: %s" % document.title,
                        "URL: %s" % document.source_url,
                        "AUTHOR: %s" % (document.author or "未知"),
                        "DATE: %s" % (document.published_at or "未知"),
                        "CONTENT:",
                        document.content[: self.chars_per_document],
                    ]
                )
            )
        schema = {
            "title": "%s 人物全景" % person.name,
            "overview": "两到四段人物概览",
            "identity": ["身份或经历要点"],
            "accomplishments": [
                {"title": "做过的事情", "description": "具体说明", "period": "时间", "source_urls": ["必须来自输入 URL"]}
            ],
            "viewpoint_topics": [
                {
                    "name": "观点主题",
                    "summary": "主题概述",
                    "points": [
                        {"statement": "主要观点", "explanation": "解释与上下文", "source_urls": ["必须来自输入 URL"]}
                    ],
                }
            ],
            "viewpoint_evolution": [
                {"period": "阶段或时间", "summary": "观点如何延续、调整或变化", "source_urls": ["必须来自输入 URL"]}
            ],
            "timeline": [{"date": "时间", "event": "事件", "source_urls": ["必须来自输入 URL"]}],
            "external_views": [{"summary": "媒体或第三方评价", "source_urls": ["必须来自输入 URL"]}],
        }
        language_instructions = {
            "zh": "所有编辑性内容使用简体中文。只翻译人物导读、经历、观点、时间线和关键评价，不翻译输入资料全文。",
            "en": "Write all editorial content in English. Preserve proper nouns and source URLs exactly.",
            "bilingual": "每个编辑性字段先写简体中文，再换行写对应英文。不要翻译输入资料全文，只生成结构化报告的双语内容。",
        }
        prompt = """研究对象：{name}
身份备注：{description}
输出语言：{language_instruction}

请生成完整人物全景报告数据，重点覆盖“做过什么”和“主要观点”。合并重复信息；本人观点与媒体评价分开；只有资料明确支持时间差异时才写观点演变；资料没有支持的内容不要写。source_urls 只能逐字使用文档中的 URL。即使某一部分资料不足，也返回空数组。严格遵守下面的 JSON 结构：
{schema}

资料：
{corpus}
""".format(
            name=person.name,
            description=person.description or "无",
            language_instruction=language_instructions.get(language_mode, language_instructions["zh"]),
            schema=json.dumps(schema, ensure_ascii=False),
            corpus="\n\n".join(corpus),
        )
        raw = self.provider.generate_json(PROFILE_SYSTEM, prompt)
        result = validate_profile(raw, [doc.source_url for doc in selected], person.name)
        result["language_mode"] = language_mode if language_mode in language_instructions else "zh"
        result["translation_scope"] = "structured_report_only"
        return result
