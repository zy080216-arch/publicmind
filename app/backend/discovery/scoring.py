"""Deterministic source-role classification and explainable scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Sequence
from urllib.parse import urlparse

from .base import SearchHit


@dataclass
class ScoreResult:
    score: int
    source_role: str
    reasons: List[str]
    risks: List[str]


SOCIAL_HOSTS = {
    "x.com",
    "twitter.com",
    "youtube.com",
    "youtu.be",
    "linkedin.com",
    "github.com",
    "substack.com",
    "medium.com",
    "weibo.com",
    "bilibili.com",
    "zhihu.com",
}
AGGREGATOR_MARKERS = ("转载", "转自", "摘编", "repost", "转载自", "聚合")
INTERVIEW_MARKERS = ("访谈", "专访", "对话", "采访", "interview", "podcast", "问答")
COMMENTARY_MARKERS = (
    "评论",
    "评价",
    "解读",
    "批评",
    "分析",
    "review",
    "analysis",
    "critique",
    "opinion",
)
REPORT_MARKERS = ("报道", "消息", "记者", "news", "report", "profile", "人物志")
OFFICIAL_MARKERS = ("official", "官方网站", "官网", "个人主页", "主页")


def _normalize(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def _contains_any(text: str, markers: Sequence[str]) -> bool:
    lowered = text.casefold()
    return any(marker.casefold() in lowered for marker in markers)


def classify_source(hit: SearchHit, person_name: str) -> str:
    text = "%s %s" % (hit.title, hit.snippet)
    host = (urlparse(hit.url).hostname or "").lower().removeprefix("www.")
    path = urlparse(hit.url).path.casefold()
    person_token = _normalize(person_name)

    if _contains_any(text, AGGREGATOR_MARKERS):
        return "aggregator_repost"
    if _contains_any(text, OFFICIAL_MARKERS):
        return "subject_official"
    if _contains_any(text, INTERVIEW_MARKERS):
        return "subject_interview"
    if _contains_any(text, COMMENTARY_MARKERS):
        return "third_party_commentary"
    if _contains_any(text, REPORT_MARKERS):
        return "media_report"
    if host in SOCIAL_HOSTS and person_token and person_token in _normalize(path + host):
        return "subject_official"
    return "unclassified"


def score_hit(hit: SearchHit, person_name: str, anchors: Sequence[str]) -> ScoreResult:
    text = "%s %s" % (hit.title, hit.snippet)
    normalized_text = _normalize(text)
    normalized_name = _normalize(person_name)
    host = (urlparse(hit.url).hostname or "").lower().removeprefix("www.")
    role = classify_source(hit, person_name)
    reasons: List[str] = []
    risks: List[str] = []

    identity = 0
    if normalized_name and normalized_name in normalized_text:
        identity = 35
        reasons.append("标题或摘要明确出现人物姓名")
    elif normalized_name and normalized_name in _normalize(hit.url):
        identity = 25
        reasons.append("网址路径与人物姓名一致")
    else:
        risks.append("搜索摘要未直接确认人物身份")

    anchor_matches = [anchor for anchor in anchors if _normalize(anchor) in normalized_text]
    topic = min(15, len(anchor_matches) * 5)
    if anchor_matches:
        reasons.append("匹配身份线索：%s" % "、".join(anchor_matches[:3]))

    official = 0
    first_party = 0
    if role == "subject_official":
        official, first_party = 20, 15
        reasons.append("疑似人物本人账号或主页")
    elif role == "subject_interview":
        official, first_party = 10, 12
        reasons.append("疑似包含人物本人直接表达的访谈")
    elif role in {"media_report", "third_party_commentary"}:
        official, first_party = 5, 0
        reasons.append("属于外部报道或评价，应与本人观点分开")
    elif role == "aggregator_repost":
        risks.append("疑似转载或聚合，需追溯原始出处")

    quality = 8 if host and "." in host else 2
    if host.endswith((".gov", ".edu", ".org")):
        quality = 10
        reasons.append("机构型域名提供较强来源线索")
    access = 5 if urlparse(hit.url).scheme == "https" else 2

    penalty = 0
    if role == "aggregator_repost":
        penalty += 20
    if not hit.title:
        penalty += 5
        risks.append("缺少标题")
    if not hit.snippet:
        penalty += 5
        risks.append("缺少摘要，难以预判内容")
    if not anchor_matches and identity < 35:
        penalty += 10
        risks.append("同名歧义风险较高")

    score = max(0, min(100, identity + official + first_party + topic + quality + access - penalty))
    return ScoreResult(score=score, source_role=role, reasons=reasons, risks=risks)
