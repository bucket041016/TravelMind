"""知识库检索消费者：把 kb_retrieve 的返回绑定到高德候选上。

设计红线（docs/open-source-comparison.md 3.4 / target-architecture.md 第 7 节）：
- 知识库只补充背景知识与解释，不引入地点、坐标、票价、库存或班次；
- 因此本模块只往**既有高德候选**上挂可选字段，绝不新建候选、绝不改 place_source；
- 关闭开关时完全不发工具调用，规划路径与现状逐字段一致。

挂到候选上的字段：
- ``knowledge``：原始知识条目（highlights / suggested_duration / booking / ticket /
  indoor / rainy_alternative / note），供规划脑引用与前端展示；
- ``knowledge_detail``：拼好的事实性描述句，替代模型对景点详情的自由生成。
"""

from __future__ import annotations

import os
import re
from typing import Any

KNOWLEDGE_TOOL = "kb_retrieve"
KNOWLEDGE_ENTRY_LIMIT = 12


def knowledge_enabled() -> bool:
    """TRAVELMIND_KNOWLEDGE 开关，默认 off（灰度：可一键回退到现状路径）。"""
    return os.getenv("TRAVELMIND_KNOWLEDGE", "off").strip().lower() in {"1", "on", "true", "yes"}


def _normalize_name(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def knowledge_detail_text(entry: dict[str, Any]) -> str:
    """把一条知识条目拼成事实性描述句；空字段自动跳过。"""
    parts: list[str] = []
    duration = str(entry.get("suggested_duration") or "").strip()
    if duration:
        parts.append(f"建议游览 {duration}")
    best_time = str(entry.get("best_time") or "").strip()
    if best_time:
        parts.append(f"适合时段：{best_time}")
    booking = str(entry.get("booking") or "").strip()
    if booking:
        parts.append(f"预约与购票：{booking}")
    ticket = str(entry.get("ticket") or "").strip()
    if ticket:
        parts.append(f"票价参考：{ticket}")
    if entry.get("indoor"):
        parts.append("室内为主")
    if entry.get("rainy_alternative"):
        parts.append("可作为雨天替代")
    highlights = [str(item).strip() for item in entry.get("highlights") or [] if str(item).strip()]
    if highlights:
        parts.append("；".join(highlights))
    note = str(entry.get("note") or "").strip()
    if note:
        parts.append(note)
    return "；".join(parts)


def match_knowledge_entry(name: Any, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """按名称/别名把候选对到知识条目；精确名 > 别名 > 名称包含，保证结果确定。"""
    target = _normalize_name(name)
    if not target or not entries:
        return None

    for entry in entries:
        if _normalize_name(entry.get("name")) == target:
            return entry
    for entry in entries:
        aliases = {_normalize_name(alias) for alias in entry.get("aliases") or []}
        aliases.discard("")
        if target in aliases:
            return entry
    for entry in entries:
        entry_name = _normalize_name(entry.get("name"))
        if entry_name and (entry_name in target or target in entry_name):
            return entry
    return None


def _poi_groups(pois: dict[str, Any]) -> list[list[dict[str, Any]]]:
    return [
        [item for item in pois.get("attractions") or [] if isinstance(item, dict)],
        [item for item in pois.get("foods") or [] if isinstance(item, dict)],
        [item for item in pois.get("specialty_places") or [] if isinstance(item, dict)],
    ]


def _build_knowledge(self, prefs: dict[str, Any], pois: dict[str, Any]) -> dict[str, Any]:
    """检索目的地知识库并绑定到已入选的高德候选上（TRAVELMIND_KNOWLEDGE 开启时）。"""
    if not knowledge_enabled():
        return {}

    groups = _poi_groups(pois)
    candidates = [item for group in groups for item in group]
    if not candidates:
        return {}

    city = str(prefs.get("destinationCity") or "")
    result = self.toolbox.call_structured(KNOWLEDGE_TOOL, city=city, limit=KNOWLEDGE_ENTRY_LIMIT)
    data = getattr(result, "data", None)
    if not isinstance(data, dict):
        return {
            "provider_status": "unavailable",
            "city": city,
            "city_guide": None,
            "matched": {},
            "matched_count": 0,
            "candidate_count": len(candidates),
            "note": "知识库返回无法解析，已跳过知识检索。",
        }

    provider_status = str(data.get("provider_status") or "unavailable")
    if provider_status != "knowledge_base":
        return {
            "provider_status": provider_status,
            "city": city,
            "city_guide": None,
            "matched": {},
            "matched_count": 0,
            "candidate_count": len(candidates),
            "note": str(data.get("note") or "知识库未覆盖该目的地。"),
        }

    entries = [item for item in data.get("entries") or [] if isinstance(item, dict)]
    guide = data.get("city_guide") if isinstance(data.get("city_guide"), dict) else None
    matched: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        entry = match_knowledge_entry(candidate.get("name"), entries)
        if not entry:
            continue
        detail = knowledge_detail_text(entry)
        candidate["knowledge"] = entry
        if detail:
            candidate["knowledge_detail"] = detail
        candidate_id = str(candidate.get("id") or "")
        if candidate_id:
            matched[candidate_id] = {"entry": entry, "detail": detail}

    return {
        "provider_status": "knowledge_base",
        "city": str(data.get("city") or city),
        "city_guide": guide,
        "matched": matched,
        "matched_count": len(matched),
        "candidate_count": len(candidates),
        "note": str(data.get("note") or ""),
    }
