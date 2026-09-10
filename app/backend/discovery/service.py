"""Discovery orchestration: query generation, deduplication, scoring and persistence."""

from __future__ import annotations

import re
from typing import List, Optional, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..models import Person, SourceCandidate
from ..store import Repository
from .base import SearchProvider, SearchProviderError
from .scoring import score_hit

try:
    from pypinyin import lazy_pinyin
except ImportError:  # pragma: no cover - dependency is installed with the application
    lazy_pinyin = None


INSTITUTION_ENGLISH_NAMES = {
    "中山大学": "Sun Yat-sen University",
    "昆士兰大学": "University of Queensland",
    "澳昆士兰大学": "University of Queensland",
    "清华大学": "Tsinghua University",
    "北京大学": "Peking University",
    "复旦大学": "Fudan University",
    "上海交通大学": "Shanghai Jiao Tong University",
    "浙江大学": "Zhejiang University",
    "中国科学院": "Chinese Academy of Sciences",
}

INSTITUTION_DOMAINS = {
    "中山大学": "sysu.edu.cn",
    "清华大学": "tsinghua.edu.cn",
    "北京大学": "pku.edu.cn",
    "复旦大学": "fudan.edu.cn",
    "上海交通大学": "sjtu.edu.cn",
    "浙江大学": "zju.edu.cn",
    "中国科学院": "cas.cn",
}


def _romanized_names(name: str) -> List[str]:
    chinese = "".join(re.findall(r"[\u3400-\u9fff]", name))
    if not chinese or lazy_pinyin is None:
        return []
    syllables = [part.capitalize() for part in lazy_pinyin(chinese) if part]
    if len(syllables) < 2:
        return []
    family_first = " ".join(syllables)
    given_first = " ".join(syllables[1:] + syllables[:1])
    return list(dict.fromkeys([family_first, given_first]))


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        )
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


class DiscoveryService:
    def __init__(
        self,
        repository: Repository,
        provider: SearchProvider,
        reference_provider: Optional[SearchProvider] = None,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.reference_provider = reference_provider

    @staticmethod
    def queries(person: Person, anchors: Sequence[str]) -> List[str]:
        anchor_text = " ".join(anchors[:4]).strip()
        base = '"%s"' % person.name
        queries = [
            "%s %s official" % (base, anchor_text),
            "%s %s X Twitter GitHub YouTube blog 官网 主页" % (base, anchor_text),
            "%s %s interview podcast 访谈" % (base, anchor_text),
            "%s %s profile analysis review 评论 报道" % (base, anchor_text),
        ]
        identity_text = "%s %s" % (person.name, anchor_text)
        if re.search(r"[\u3400-\u9fff]", identity_text):
            queries.extend(
                [
                    "%s %s 小红书 微信公众号 视频号" % (base, anchor_text),
                    "%s %s site:xiaohongshu.com OR site:mp.weixin.qq.com" % (base, anchor_text),
                    "%s %s site:channels.weixin.qq.com OR 视频号" % (base, anchor_text),
                    "%s %s 百度百科 百度采访 site:baike.baidu.com" % (base, anchor_text),
                    "%s %s 微博 知乎 B站 抖音" % (base, anchor_text),
                ]
            )
            institution_anchors = [
                anchor for anchor in anchors
                if re.search(r"大学|学院|研究院|实验室|医院|研究所", anchor)
            ]
            for institution in institution_anchors[:3]:
                queries.append('%s "%s" 教授 院长 导师 师资 官网' % (base, institution))
                domain = next(
                    (value for label, value in INSTITUTION_DOMAINS.items() if label in institution),
                    None,
                )
                if domain:
                    queries.append('%s site:%s' % (base, domain))

            english_institutions = list(dict.fromkeys(
                english
                for anchor in anchors
                for label, english in INSTITUTION_ENGLISH_NAMES.items()
                if label in anchor
            ))
            romanized = _romanized_names(person.name)
            for romanized_name in romanized:
                if english_institutions:
                    for institution in english_institutions[:2]:
                        queries.append('"%s" "%s" professor dean profile' % (romanized_name, institution))
                else:
                    queries.append('"%s" professor researcher profile' % romanized_name)
        return list(dict.fromkeys(query.strip() for query in queries if query.strip()))

    def discover(self, person: Person, anchors: Sequence[str], per_query: int = 8) -> List[SourceCandidate]:
        seen = set()
        candidates: List[SourceCandidate] = []
        if self.reference_provider is not None:
            reference_query = "%s biography career" % person.name
            for hit in self.reference_provider.search(person.name, count=4):
                normalized_url = canonical_url(hit.url)
                if normalized_url in seen:
                    continue
                seen.add(normalized_url)
                scored = score_hit(hit, person.name, anchors)
                candidate = SourceCandidate(
                    person_id=person.id or "",
                    url=normalized_url,
                    title=hit.title or normalized_url,
                    snippet=hit.snippet,
                    provider=self.reference_provider.name,
                    query=reference_query,
                    score=scored.score,
                    source_role=scored.source_role,
                    reasons=scored.reasons + ["百科生平基线"],
                    risks=scored.risks,
                )
                candidates.append(self.repository.upsert_candidate(candidate))
        for query in self.queries(person, anchors):
            for hit in self.provider.search(query, count=per_query):
                normalized_url = canonical_url(hit.url)
                if normalized_url in seen:
                    continue
                seen.add(normalized_url)
                scored = score_hit(hit, person.name, anchors)
                candidate = SourceCandidate(
                    person_id=person.id or "",
                    url=normalized_url,
                    title=hit.title or normalized_url,
                    snippet=hit.snippet,
                    provider=self.provider.name,
                    query=query,
                    score=scored.score,
                    source_role=scored.source_role,
                    reasons=scored.reasons,
                    risks=scored.risks,
                )
                candidates.append(self.repository.upsert_candidate(candidate))
        return sorted(candidates, key=lambda item: (-item.score, item.title.casefold()))

    def discover_targeted(
        self, person: Person, queries: Sequence[str], per_query: int = 6
    ) -> List[SourceCandidate]:
        """Discover sources for one concrete question without rerunning broad discovery."""

        seen = set()
        candidates: List[SourceCandidate] = []
        failures: List[Exception] = []
        for query in list(dict.fromkeys(queries))[:4]:
            try:
                hits = self.provider.search(query, count=per_query)
            except SearchProviderError as exc:
                failures.append(exc)
                continue
            for index, hit in enumerate(hits):
                normalized_url = canonical_url(hit.url)
                if normalized_url in seen:
                    continue
                seen.add(normalized_url)
                scored = score_hit(hit, person.name, [])
                candidate = SourceCandidate(
                    person_id=person.id or "",
                    url=normalized_url,
                    title=hit.title or normalized_url,
                    snippet=hit.snippet,
                    provider=self.provider.name,
                    query=query,
                    score=min(100, scored.score + max(0, 10 - index * 2)),
                    source_role=scored.source_role,
                    reasons=scored.reasons + ["针对当前问询补充检索"],
                    risks=scored.risks,
                )
                candidates.append(self.repository.upsert_candidate(candidate))
        if not candidates and failures:
            raise SearchProviderError(str(failures[-1]))
        return sorted(candidates, key=lambda item: (-item.score, item.title.casefold()))
