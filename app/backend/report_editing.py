"""Deterministic, local edits to a generated report."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Tuple


def _remove_from_sourced_items(items: Any, removed_url: str) -> Tuple[List[Dict[str, Any]], int]:
    kept: List[Dict[str, Any]] = []
    removed_count = 0
    for raw in items if isinstance(items, list) else []:
        if not isinstance(raw, dict):
            continue
        item = deepcopy(raw)
        original = item.get("source_urls")
        if not isinstance(original, list) or removed_url not in original:
            kept.append(item)
            continue
        item["source_urls"] = [url for url in original if url != removed_url]
        if item["source_urls"]:
            kept.append(item)
        else:
            removed_count += 1
    return kept, removed_count


def prune_report_by_source(content: Dict[str, Any], removed_url: str) -> Tuple[Dict[str, Any], int]:
    """Remove only report statements whose last supporting source was removed."""

    result = deepcopy(content)
    removed_count = 0
    removed_was_report_source = any(
        isinstance(item, dict) and item.get("url") == removed_url
        for item in result.get("public_sources", [])
    )

    for key in (
        "biography",
        "accomplishments",
        "viewpoint_evolution",
        "external_views",
        "timeline",
    ):
        result[key], count = _remove_from_sourced_items(result.get(key), removed_url)
        removed_count += count

    topics: List[Dict[str, Any]] = []
    for raw_topic in result.get("viewpoint_topics", []) if isinstance(result.get("viewpoint_topics"), list) else []:
        if not isinstance(raw_topic, dict):
            continue
        topic = deepcopy(raw_topic)
        topic["points"], count = _remove_from_sourced_items(topic.get("points"), removed_url)
        removed_count += count
        summary_urls = topic.get("summary_source_urls")
        if isinstance(summary_urls, list) and removed_url in summary_urls:
            topic["summary_source_urls"] = [url for url in summary_urls if url != removed_url]
            if not topic["summary_source_urls"]:
                topic["summary"] = ""
        if topic.get("points") or str(topic.get("summary", "")).strip():
            topics.append(topic)
        else:
            removed_count += 1
    result["viewpoint_topics"] = topics

    identity_sources = result.get("identity_source_urls")
    if isinstance(identity_sources, list):
        kept_identity_sources, count = _remove_from_sourced_items(identity_sources, removed_url)
        removed_count += count
        result["identity_source_urls"] = kept_identity_sources
        supported_text = {str(item.get("text", "")) for item in kept_identity_sources}
        removed_text = {
            str(item.get("text", ""))
            for item in identity_sources
            if isinstance(item, dict)
            and removed_url in item.get("source_urls", [])
            and not [url for url in item.get("source_urls", []) if url != removed_url]
        }
        result["identity"] = [
            text for text in result.get("identity", [])
            if text not in removed_text or text in supported_text
        ]
    elif removed_was_report_source:
        removed_count += len(result.get("identity", []))
        result["identity"] = []

    overview_urls = result.get("overview_source_urls")
    if isinstance(overview_urls, list) and removed_url in overview_urls:
        result["overview_source_urls"] = [url for url in overview_urls if url != removed_url]
        if not result["overview_source_urls"]:
            result["overview"] = ""
            removed_count += 1
    elif "overview_source_urls" not in result and removed_was_report_source and result.get("overview"):
        result["overview"] = ""
        removed_count += 1

    before_images = result.get("images", []) if isinstance(result.get("images"), list) else []
    result["images"] = [item for item in before_images if item.get("source_url") != removed_url]
    removed_count += len(before_images) - len(result["images"])
    for key in ("public_sources", "public_profiles"):
        result[key] = [
            item for item in result.get(key, []) if item.get("url") != removed_url
        ]
    result.pop("needs_rebuild", None)
    return result, removed_count
