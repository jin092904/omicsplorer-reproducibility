"""Identifier and text normalization shared by all service adapters."""
from __future__ import annotations

import html
import re
from typing import Any

_GSE_RE = re.compile(r"(?i)\bGSE\s*0*([0-9]+)\b")
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def canonical_geo_series(value: str) -> str | None:
    """Return canonical uppercase GSE accession, or ``None`` for non-Series IDs."""
    match = _GSE_RE.search(value or "")
    if not match:
        return None
    return f"GSE{int(match.group(1))}"


def plain_text(value: Any, *, limit: int = 20_000) -> str:
    """Strip simple HTML from public metadata and normalize whitespace."""
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = _TAG_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()[:limit]


def unique_strings(values: list[Any]) -> list[str]:
    """Stable, case-insensitive de-duplication for display metadata."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = plain_text(value, limit=500)
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out
