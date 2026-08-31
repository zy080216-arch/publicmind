"""Conservative, deterministic claim candidate extraction.

This module deliberately proposes review items rather than asserting that a
sentence belongs to the researched person. It can later be replaced by an LLM
provider without changing the stored evidence contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

from ..models import Chunk, Claim, Document, Person, Source


ASSERTION_MARKERS = (
    "认为",
    "指出",
    "表示",
    "主张",
    "强调",
    "建议",
    "应该",
    "必须",
    "意味着",
    "believe",
    "argue",
    "said",
    "says",
    "should",
    "must",
    "suggest",
    "means",
)
QUOTE_MARKERS = ('“', '”', '「', '」', '"')


@dataclass
class SentenceCandidate:
    chunk: Chunk
    text: str
    start_char: int
    end_char: int
    score: int


def _sentences(text: str) -> Iterable[Tuple[str, int, int]]:
    pattern = re.compile(r"[^。！？!?\n]+(?:[。！？!?]+|$)|[^\n]+$")
    for match in pattern.finditer(text):
        sentence = re.sub(r"\s+", " ", match.group(0)).strip(" -\t\r\n")
        if sentence:
            yield sentence, match.start(), match.end()


def _candidate_score(text: str, person_name: str) -> int:
    lowered = text.casefold()
    score = 0
    if any(marker.casefold() in lowered for marker in ASSERTION_MARKERS):
        score += 4
    if any(marker in text for marker in QUOTE_MARKERS):
        score += 3
    if person_name.casefold() in lowered:
        score += 2
    if 55 <= len(text) <= 240:
        score += 2
    elif 30 <= len(text) <= 360:
        score += 1
    if re.search(r"https?://|^#+\s|^[\W_]+$", text):
        score -= 5
    return score


def _attribution(source_role: str, person: Person) -> Tuple[str, str, str, str]:
    if source_role == "subject_official":
        return (
            "subject_claim_candidate",
            person.name,
            "medium",
            "来源疑似本人官方，但句子归属仍需人工确认",
        )
    if source_role == "subject_interview":
        return (
            "subject_claim_candidate",
            person.name,
            "medium",
            "访谈可能混有提问者文字，需核对上下文和说话人",
        )
    if source_role == "third_party_commentary":
        return (
            "external_evaluation",
            "外部评论者",
            "high",
            "来源已标记为第三方评论，不应当作人物本人观点",
        )
    if source_role == "media_report":
        return (
            "media_description",
            "媒体或记者",
            "high",
            "来源已标记为媒体报道，可能包含转述而非本人原话",
        )
    if source_role == "aggregator_repost":
        return (
            "insufficient_evidence",
            "待追溯原作者",
            "low",
            "转载聚合需先找到原始出处",
        )
    return (
        "unverified_attribution",
        "待确认",
        "low",
        "来源角色尚未确认，不能推断表达者",
    )


class ClaimExtractor:
    def __init__(self, max_candidates: int = 12) -> None:
        self.max_candidates = max_candidates

    def propose(
        self,
        person: Person,
        source: Source,
        document: Document,
        chunks: Sequence[Chunk],
    ) -> List[Claim]:
        ranked: List[SentenceCandidate] = []
        for chunk in chunks:
            if not chunk.id:
                continue
            for sentence, local_start, local_end in _sentences(chunk.content):
                if not 30 <= len(sentence) <= 420:
                    continue
                score = _candidate_score(sentence, person.name)
                if score < 2:
                    continue
                ranked.append(
                    SentenceCandidate(
                        chunk=chunk,
                        text=sentence,
                        start_char=local_start,
                        end_char=local_end,
                        score=score,
                    )
                )

        selected = sorted(
            sorted(ranked, key=lambda item: item.score, reverse=True)[: self.max_candidates],
            key=lambda item: (item.chunk.index, item.start_char),
        )
        claim_type, speaker, confidence, rationale = _attribution(source.source_role, person)
        return [
            Claim(
                person_id=person.id or "",
                document_id=document.id or "",
                source_id=source.id or "",
                chunk_id=item.chunk.id or "",
                statement=item.text,
                evidence_quote=item.text,
                claim_type=claim_type,
                speaker=speaker,
                attribution_confidence=confidence,
                source_role=source.source_role,
                start_char=item.start_char,
                end_char=item.end_char,
                start_time=item.chunk.start_time,
                end_time=item.chunk.end_time,
                rationale=rationale,
            )
            for item in selected
        ]
