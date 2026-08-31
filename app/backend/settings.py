"""Local-only runtime settings for API credentials.

Secrets are written beside the SQLite database with owner-only permissions and
are never returned by the API. Environment variables remain supported for
headless use.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def settings_path(database: str) -> Path:
    explicit = os.getenv("PUBLICMIND_SETTINGS_FILE")
    if explicit:
        return Path(explicit)
    value = database
    if value.startswith("sqlite:///"):
        value = value[len("sqlite:///") :]
    elif value.startswith("sqlite://"):
        value = value[len("sqlite://") :]
    if value == ":memory:" or "://" in value:
        return Path("data/settings.json")
    return Path(value).parent / "settings.json"


def load_local_settings(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if value}


def save_local_settings(
    path: Path,
    brave_api_key: Optional[str] = None,
    deepseek_api_key: Optional[str] = None,
) -> Dict[str, str]:
    current = load_local_settings(path)
    if brave_api_key is not None:
        value = brave_api_key.strip()
        if value:
            current["brave_api_key"] = value
    if deepseek_api_key is not None:
        value = deepseek_api_key.strip()
        if value:
            current["deepseek_api_key"] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return current


def configuration_status(path: Path) -> Dict[str, Any]:
    local = load_local_settings(path)
    return {
        "search_configured": bool(local.get("brave_api_key") or os.getenv("BRAVE_SEARCH_API_KEY")),
        "llm_configured": bool(
            local.get("deepseek_api_key")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("PUBLICMIND_LLM_API_KEY")
        ),
        "llm_provider": "DeepSeek",
        "llm_model": os.getenv("PUBLICMIND_LLM_MODEL") or "deepseek-v4-flash",
    }
