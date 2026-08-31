"""Deterministic Obsidian Vault renderer."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..models import Claim, Document, Person


def safe_filename(value: str, fallback: str = "untitled") -> str:
    value = re.sub(r"[\\/:*?\"<>|\n\r]+", " ", value).strip()
    value = re.sub(r"\s+", " ", value)
    return value[:120] or fallback


def _yaml_string(value: Optional[str]) -> str:
    if value is None:
        return "null"
    return json.dumps(str(value), ensure_ascii=False)


def _link_path(path: Path) -> str:
    return path.with_suffix("").as_posix()


class VaultExporter:
    def __init__(self, output_dir: str = "data/exports") -> None:
        self.output_dir = Path(output_dir)

    def _document_filename(self, document: Document) -> str:
        return "%s-%s.md" % (safe_filename(document.title), document.content_hash[:8])

    def render_document(self, document: Document) -> str:
        topics = document.topics or []
        entities = document.entities or []
        metadata = document.metadata or {}
        platform = document.metadata.get("platform")
        if not platform:
            platform = "youtube" if document.source_type == "video" else "web"
        frontmatter = [
            "---",
            "id: %s" % _yaml_string(document.id),
            "source_platform: %s" % _yaml_string(platform),
            "source_type: %s" % _yaml_string(document.source_type),
            "title: %s" % _yaml_string(document.title),
            "author: %s" % _yaml_string(document.author),
            "published_at: %s" % _yaml_string(document.published_at),
            "fetched_at: %s" % _yaml_string(document.fetched_at),
            "url: %s" % _yaml_string(document.source_url),
            "content_hash: %s" % _yaml_string(document.content_hash),
        ]
        if topics:
            frontmatter.append("topics:")
            frontmatter.extend("  - %s" % _yaml_string(topic) for topic in topics)
        else:
            frontmatter.append("topics: []")
        if entities:
            frontmatter.append("entities:")
            frontmatter.extend("  - %s" % _yaml_string(entity) for entity in entities)
        else:
            frontmatter.append("entities: []")
        frontmatter.extend(["---", "", "# %s" % document.title, ""])
        if document.summary:
            frontmatter.extend(["## Summary", "", document.summary, ""])
        frontmatter.extend(["## Source", "", "[%s](%s)" % (document.source_url, document.source_url), ""])
        if metadata.get("subtitle_language"):
            frontmatter.extend(["Subtitle language: %s" % metadata["subtitle_language"], ""])
        frontmatter.extend([document.content, ""])
        return "\n".join(frontmatter).strip() + "\n"

    def _render_home(
        self,
        person: Person,
        document_links: List[Tuple[Document, str]],
        claim_count: int,
    ) -> str:
        lines = [
            "# %s" % person.name,
            "",
            "> This vault organizes publicly available materials. AI-generated summaries, when present, are derived from cited sources and do not represent the individual.",
            "",
            "## Overview",
            "",
            "- Documents: %d" % len(document_links),
            "- Confirmed claims: %d" % claim_count,
            "- [[01 Timeline]]",
            "- [[02 Claims]]",
            "",
            "## Sources",
            "",
        ]
        for document, path in document_links:
            lines.append("- [[%s|%s]]" % (_link_path(Path(path)), document.title))
        if not document_links:
            lines.append("- No documents imported yet.")
        return "\n".join(lines) + "\n"

    def _render_claims(
        self,
        claims: List[Claim],
        document_links: List[Tuple[Document, str]],
    ) -> str:
        document_by_id = {
            document.id: (document, path) for document, path in document_links if document.id
        }
        lines = [
            "# Confirmed Claims",
            "",
            "> Only human-confirmed claims appear here. The quoted evidence remains verbatim; the claim statement may be an editorial paraphrase.",
            "",
        ]
        if not claims:
            lines.append("No claims have been confirmed yet.")
            return "\n".join(lines) + "\n"
        for index, claim in enumerate(claims, 1):
            lines.extend(
                [
                    "## %02d · %s" % (index, claim.statement),
                    "",
                    "- Type: `%s`" % claim.claim_type,
                    "- Speaker: %s" % claim.speaker,
                    "- Source role: `%s`" % claim.source_role,
                    "- Attribution confidence: `%s`" % claim.attribution_confidence,
                ]
            )
            linked = document_by_id.get(claim.document_id)
            if linked:
                document, path = linked
                lines.append("- Evidence document: [[%s|%s]]" % (_link_path(Path(path)), document.title))
                lines.append("- Original URL: [%s](%s)" % (document.source_url, document.source_url))
            if claim.start_time is not None:
                lines.append("- Locator: %.1fs–%.1fs" % (claim.start_time, claim.end_time or claim.start_time))
            else:
                lines.append("- Locator: characters %d–%d in evidence chunk" % (claim.start_char, claim.end_char))
            lines.extend(["", "> %s" % claim.evidence_quote.replace("\n", "\n> "), ""])
            if claim.review_note:
                lines.extend(["Review note: %s" % claim.review_note, ""])
        return "\n".join(lines) + "\n"

    def _render_timeline(self, document_links: List[Tuple[Document, str]]) -> str:
        lines = ["# Timeline", ""]
        dated = [item for item in document_links if item[0].published_at]
        undated = [item for item in document_links if not item[0].published_at]
        for document, path in sorted(dated, key=lambda item: item[0].published_at or "", reverse=True):
            date = (document.published_at or "")[:10] or "Unknown date"
            lines.append("- %s — [[%s|%s]]" % (date, _link_path(Path(path)), document.title))
        if undated:
            lines.extend(["", "## Undated", ""])
            for document, path in undated:
                lines.append("- [[%s|%s]]" % (_link_path(Path(path)), document.title))
        if not document_links:
            lines.append("No documents imported yet.")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _source_refs(urls: Iterable[str], source_links: Dict[str, Tuple[Document, str]]) -> str:
        refs = []
        for index, url in enumerate(urls, 1):
            linked = source_links.get(url)
            if linked:
                document, path = linked
                refs.append("[[%s|来源%d]]" % (_link_path(Path(path)), index))
        return " · ".join(refs)

    def _report_source_filename(self, document: Document) -> str:
        return "%s-%s.md" % (safe_filename(document.title, "公开来源"), document.content_hash[:8])

    def _render_report_source(self, document: Document, person: Person) -> str:
        platform = document.metadata.get("platform") or (
            "YouTube" if document.source_type == "video" else "Web"
        )
        lines = [
            "---",
            "title: %s" % _yaml_string(document.title),
            "person: %s" % _yaml_string(person.name),
            "platform: %s" % _yaml_string(str(platform)),
            "author: %s" % _yaml_string(document.author),
            "published_at: %s" % _yaml_string(document.published_at),
            "fetched_at: %s" % _yaml_string(document.fetched_at),
            "url: %s" % _yaml_string(document.source_url),
            "content_hash: %s" % _yaml_string(document.content_hash),
            "---",
            "",
            "# %s" % document.title,
            "",
            "- 人物：[[00 人物全景|%s]]" % person.name,
            "- 平台：%s" % platform,
            "- 作者：%s" % (document.author or "未标明"),
            "- 日期：%s" % (document.published_at or "未标明"),
            "- 原始网址：[%s](<%s>)" % (document.source_url, document.source_url),
            "",
            "## 正文",
            "",
            document.content,
            "",
        ]
        return "\n".join(lines)

    def _render_accomplishments(
        self, person: Person, report: Dict[str, Any], source_links: Dict[str, Tuple[Document, str]]
    ) -> str:
        lines = ["# %s做过的事情" % person.name, "", "[[00 人物全景|返回人物全景]]", ""]
        items = report.get("accomplishments", [])
        if not items:
            lines.append("现有公开资料不足以整理出明确条目。")
        for item in items:
            lines.extend(["## %s" % item["title"], ""])
            if item.get("period"):
                lines.extend(["**时间：** %s" % item["period"], ""])
            lines.extend([item.get("description") or "", ""])
        return "\n".join(lines).strip() + "\n"

    def _render_viewpoints(
        self,
        person: Person,
        report: Dict[str, Any],
        source_links: Dict[str, Tuple[Document, str]],
        topic_links: List[Tuple[str, str]],
    ) -> str:
        lines = ["# %s的核心观点" % person.name, "", "[[00 人物全景|返回人物全景]]", ""]
        if topic_links:
            lines.extend(["## 主题目录", ""])
            lines.extend("- [[%s|%s]]" % (path, name) for name, path in topic_links)
            lines.append("")
        topics = report.get("viewpoint_topics", [])
        if not topics:
            lines.append("现有公开资料不足以整理出明确的观点主题。")
        for topic in topics:
            lines.extend(["## %s" % topic["name"], "", topic.get("summary") or "", ""])
            for point in topic.get("points", []):
                lines.append("- **%s**" % point["statement"])
                if point.get("explanation"):
                    lines.append("  %s" % point["explanation"])
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _render_topic_note(
        self, person: Person, topic: Dict[str, Any], source_links: Dict[str, Tuple[Document, str]]
    ) -> str:
        lines = [
            "# %s" % topic["name"],
            "",
            "人物：[[00 人物全景|%s]] · [[03 核心观点|全部核心观点]]" % person.name,
            "",
            topic.get("summary") or "",
            "",
            "## 主要观点",
            "",
        ]
        for point in topic.get("points", []):
            lines.append("- **%s**" % point["statement"])
            if point.get("explanation"):
                lines.append("  %s" % point["explanation"])
        return "\n".join(lines).strip() + "\n"

    def _render_simple_report_section(
        self,
        title: str,
        home_label: str,
        items: List[Dict[str, Any]],
        source_links: Dict[str, Tuple[Document, str]],
        date_key: str,
        text_key: str,
    ) -> str:
        lines = ["# %s" % title, "", "[[00 人物全景|%s]]" % home_label, ""]
        if not items:
            lines.append("现有公开资料没有形成可单独列出的内容。")
        for item in items:
            label = item.get(date_key) or "时间不详"
            lines.append("- **%s** — %s" % (label, item.get(text_key) or ""))
        return "\n".join(lines).strip() + "\n"

    def _render_source_directory(
        self,
        person: Person,
        report: Dict[str, Any],
        source_links: Dict[str, Tuple[Document, str]],
    ) -> str:
        lines = [
            "# %s的公开信息源" % person.name,
            "",
            "[[00 人物全景|返回人物全景]]",
            "",
            "> 公开主页与本次实际收录的资料统一列在这里，不分散附在观点条目下。",
            "",
        ]
        profiles = report.get("public_profiles", [])
        if profiles:
            lines.extend(["## 公开主页", ""])
            for item in profiles:
                lines.append(
                    "- **%s**：[%s](<%s>)"
                    % (item.get("platform") or "主页", item.get("title") or item["url"], item["url"])
                )
            lines.extend(["", "## 本次收录资料", ""])
        for index, (url, (document, path)) in enumerate(source_links.items(), 1):
            platform = document.metadata.get("platform") or (
                "YouTube" if document.source_type == "video" else "Web"
            )
            lines.extend(
                [
                    "## %02d · %s" % (index, document.title),
                    "",
                    "- 平台：%s" % platform,
                    "- 作者：%s" % (document.author or "未标明"),
                    "- 日期：%s" % (document.published_at or "未标明"),
                    "- 来源笔记：[[%s|打开保存内容]]" % _link_path(Path(path)),
                    "- 原始网址：[%s](<%s>)" % (url, url),
                    "",
                ]
            )
        return "\n".join(lines).strip() + "\n"

    def _render_person_home(
        self,
        person: Person,
        report: Dict[str, Any],
        source_links: Dict[str, Tuple[Document, str]],
        topic_links: List[Tuple[str, str]],
    ) -> str:
        lines = [
            "---",
            "title: %s" % _yaml_string(report.get("title") or "%s 人物全景" % person.name),
            "person: %s" % _yaml_string(person.name),
            "aliases:",
            "  - %s" % _yaml_string(person.name),
            "tags:",
            "  - 人物知识库",
            "---",
            "",
            "# %s" % (report.get("title") or "%s 人物全景" % person.name),
            "",
            "> 这份档案根据公开可访问资料整理，重点回答：这个人做过什么，以及他表达过哪些主要观点。",
            "",
            "## 公开主页与信息源",
            "",
        ]
        profiles = report.get("public_profiles", [])
        for item in profiles:
            lines.append(
                "- **%s**：[%s](<%s>)"
                % (item.get("platform") or "主页", item.get("title") or item["url"], item["url"])
            )
        if profiles:
            lines.append("")
        for url, (document, path) in source_links.items():
            lines.append("- **收录资料**：[[%s|%s]] — [%s](<%s>)" % (_link_path(Path(path)), document.title, url, url))
        if not profiles and not source_links:
            lines.append("- 暂无可列出的公开信息源。")
        lines.extend(
            [
                "",
                "完整目录：[[公开信息源]]",
                "",
            ]
        )
        images = report.get("images", [])
        if images:
            lines.extend(["## 人物影像", ""])
            for item in images[:4]:
                image_url = str(item.get("url") or "").strip()
                source_url = str(item.get("source_url") or "").strip()
                if not image_url:
                    continue
                caption = str(item.get("caption") or "人物公开图片").replace("\n", " ")
                credit = " · ".join(
                    str(value).strip()
                    for value in (item.get("source_label"), item.get("author"), item.get("license"))
                    if str(value or "").strip()
                )
                lines.extend(["![%s](<%s>)" % (caption, image_url), ""])
                if source_url:
                    lines.extend(["[%s](<%s>)" % (credit or "查看图片出处与许可", source_url), ""])
        lines.extend(
            [
            "## 一句话认识",
            "",
            report.get("overview") or "现有资料不足以形成完整概览。",
            "",
            "## 他是谁",
            "",
            ]
        )
        identity = report.get("identity", [])
        lines.extend("- %s" % item for item in identity)
        if not identity:
            lines.append("- 现有资料没有形成独立身份条目。")

        lines.extend(["", "## 他做过什么", ""])
        accomplishments = report.get("accomplishments", [])
        for item in accomplishments:
            period = "（%s）" % item["period"] if item.get("period") else ""
            lines.append("### %s%s" % (item["title"], period))
            lines.extend(["", item.get("description") or "", ""])
        if not accomplishments:
            lines.append("现有资料不足以列出明确事项。")
        lines.extend(["详见：[[02 做过的事情]]", "", "## 他的核心观点", ""])

        topics = report.get("viewpoint_topics", [])
        for topic, (_, topic_path) in zip(topics, topic_links):
            lines.extend(["### [[%s|%s]]" % (topic_path, topic["name"]), "", topic.get("summary") or "", ""])
            for point in topic.get("points", []):
                lines.append("- **%s**" % point["statement"])
                if point.get("explanation"):
                    lines.append("  %s" % point["explanation"])
            lines.append("")
        if not topics:
            lines.append("现有资料不足以形成明确的观点主题。")
        lines.extend(["详见：[[03 核心观点]]", "", "## 观点如何变化", ""])

        evolution = report.get("viewpoint_evolution", [])
        for item in evolution:
            lines.append("- **%s** — %s" % (item.get("period") or "时间不详", item["summary"]))
        if not evolution:
            lines.append("现有资料不足以判断观点发生过明确变化。")
        lines.extend(["", "详见：[[04 观点演变]]", "", "## 外界如何评价他", ""])

        external = report.get("external_views", [])
        for item in external:
            lines.append("- %s" % item["summary"])
        if not external:
            lines.append("现有资料没有形成可单独归纳的外部评价。")
        lines.extend(["", "详见：[[05 外部评价]]", "", "## 关键时间线", ""])

        timeline = report.get("timeline", [])
        for item in timeline:
            lines.append("- **%s** — %s" % (item.get("date") or "日期不详", item["event"]))
        if not timeline:
            lines.append("现有资料没有形成可用时间线。")

        lines.extend(["", "详见：[[06 时间线]]", "", "## 在 Obsidian 中继续浏览", ""])
        lines.extend(
            [
                "- [[01 生平与经历]]",
                "- [[02 做过的事情]]",
                "- [[03 核心观点]]",
                "- [[04 观点演变]]",
                "- [[05 外部评价]]",
                "- [[06 时间线]]",
                "- [[公开信息源]]",
            ]
        )
        return "\n".join(lines).strip() + "\n"

    def _export_report(
        self, person: Person, documents: List[Document], report: Dict[str, Any]
    ) -> Tuple[Path, Path]:
        vault_dir = self.output_dir / (person.slug + "-人物知识库")
        (vault_dir / "观点").mkdir(parents=True, exist_ok=True)
        (vault_dir / "来源").mkdir(parents=True, exist_ok=True)

        source_links: Dict[str, Tuple[Document, str]] = {}
        for document in documents:
            relative = Path("来源") / self._report_source_filename(document)
            (vault_dir / relative).write_text(
                self._render_report_source(document, person), encoding="utf-8"
            )
            source_links[document.source_url] = (document, relative.as_posix())

        topic_links: List[Tuple[str, str]] = []
        used_topic_names = set()
        for index, topic in enumerate(report.get("viewpoint_topics", []), 1):
            base = safe_filename(topic["name"], "观点主题")
            filename = base
            if filename.casefold() in used_topic_names:
                filename = "%s-%02d" % (base, index)
            used_topic_names.add(filename.casefold())
            relative = Path("观点") / (filename + ".md")
            (vault_dir / relative).write_text(
                self._render_topic_note(person, topic, source_links), encoding="utf-8"
            )
            topic_links.append((topic["name"], _link_path(relative)))

        (vault_dir / "00 人物全景.md").write_text(
            self._render_person_home(person, report, source_links, topic_links), encoding="utf-8"
        )
        identity_lines = [
            "# %s的生平与经历" % person.name,
            "",
            "[[00 人物全景|返回人物全景]]",
            "",
        ]
        identity_lines.extend("- %s" % item for item in report.get("identity", []))
        if not report.get("identity"):
            identity_lines.append("现有公开资料不足以形成独立经历条目。")
        (vault_dir / "01 生平与经历.md").write_text(
            "\n".join(identity_lines).strip() + "\n", encoding="utf-8"
        )
        (vault_dir / "02 做过的事情.md").write_text(
            self._render_accomplishments(person, report, source_links), encoding="utf-8"
        )
        (vault_dir / "03 核心观点.md").write_text(
            self._render_viewpoints(person, report, source_links, topic_links), encoding="utf-8"
        )
        (vault_dir / "04 观点演变.md").write_text(
            self._render_simple_report_section(
                "%s的观点演变" % person.name,
                "返回人物全景",
                report.get("viewpoint_evolution", []),
                source_links,
                "period",
                "summary",
            ),
            encoding="utf-8",
        )
        (vault_dir / "05 外部评价.md").write_text(
            self._render_simple_report_section(
                "外界如何评价%s" % person.name,
                "返回人物全景",
                report.get("external_views", []),
                source_links,
                "period",
                "summary",
            ),
            encoding="utf-8",
        )
        (vault_dir / "06 时间线.md").write_text(
            self._render_simple_report_section(
                "%s时间线" % person.name,
                "返回人物全景",
                report.get("timeline", []),
                source_links,
                "date",
                "event",
            ),
            encoding="utf-8",
        )
        (vault_dir / "公开信息源.md").write_text(
            self._render_source_directory(person, report, source_links), encoding="utf-8"
        )

        zip_path = self.output_dir / (person.slug + ".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(vault_dir.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(self.output_dir).as_posix())
        return vault_dir, zip_path

    def export(
        self,
        person: Person,
        documents: Iterable[Document],
        claims: Iterable[Claim] = (),
        report: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Path, Path]:
        documents = list(documents)
        if report is not None:
            return self._export_report(person, documents, report)
        claims = [claim for claim in claims if claim.status == "accepted"]
        vault_dir = self.output_dir / (person.slug + "-vault")
        vault_dir.mkdir(parents=True, exist_ok=True)
        (vault_dir / "Sources" / "Web").mkdir(parents=True, exist_ok=True)
        (vault_dir / "Sources" / "Youtube").mkdir(parents=True, exist_ok=True)
        (vault_dir / "Topics").mkdir(parents=True, exist_ok=True)
        (vault_dir / "Entities").mkdir(parents=True, exist_ok=True)

        document_links = []  # type: List[Tuple[Document, str]]
        for document in documents:
            folder = "Youtube" if document.source_type == "video" else "Web"
            filename = self._document_filename(document)
            relative = Path("Sources") / folder / filename
            path = vault_dir / relative
            path.write_text(self.render_document(document), encoding="utf-8")
            document_links.append((document, relative.as_posix()))

        (vault_dir / "00 Home.md").write_text(
            self._render_home(person, document_links, len(claims)), encoding="utf-8"
        )
        (vault_dir / "01 Timeline.md").write_text(self._render_timeline(document_links), encoding="utf-8")
        (vault_dir / "02 Claims.md").write_text(
            self._render_claims(claims, document_links), encoding="utf-8"
        )
        (vault_dir / "Topics" / "README.md").write_text(
            "# Topics\n\nTopic pages will be generated after AI enrichment is enabled.\n", encoding="utf-8"
        )
        (vault_dir / "Entities" / "README.md").write_text(
            "# Entities\n\nEntity pages will be generated after enrichment is enabled.\n", encoding="utf-8"
        )

        zip_path = self.output_dir / (person.slug + ".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(vault_dir.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(self.output_dir).as_posix())
        return vault_dir, zip_path
