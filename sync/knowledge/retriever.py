"""目的地知识库检索：对人工策展的 JSON 语料做纯 Python 关键词打分。

设计约束（见 docs/open-source-comparison.md 3.4 与 target-architecture.md 第 7 节）：
- 知识库只补充背景知识与解释，不生成地点、坐标、票价、库存或班次；
- 零第三方依赖，检索结果完全确定，离线评测不需要 fixture 化网络；
- 检索器是接口，后续要换向量后端只需新增一个实现，工具契约不变。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CORPUS_DIR = Path(__file__).resolve().parent / "cities"

# 无查询时条目也有分，保证"取前 N 条"的结果稳定可复现。
_UNRANKED_SCORE = 1

_SCORE_EXACT_NAME = 1000
_SCORE_EXACT_ALIAS = 800
_SCORE_NAME_OVERLAP = 500
_SCORE_ALIAS_OVERLAP = 200
_SCORE_KEYWORD_HIT = 60
_SCORE_BODY_HIT = 30


def normalize_city_name(city: str) -> str:
    """城市名归一：去空白与"市/市区"后缀，供语料索引键复用。"""
    text = re.sub(r"\s+", "", str(city or ""))
    return text.removesuffix("市区").removesuffix("市")


def _normalize_query(query: str) -> str:
    """查询词归一：只去空白。地点名里可能带"市"，不能按城市规则剥。"""
    return re.sub(r"\s+", "", str(query or ""))


def _entry_score(query: str, entry: dict[str, Any]) -> int:
    """名称精确命中 > alias 命中 > 名称包含 > alias 包含 > 关键词 > 正文。"""
    text = _normalize_query(query)
    if not text:
        return _UNRANKED_SCORE

    name = _normalize_query(entry.get("name"))
    if text == name:
        return _SCORE_EXACT_NAME

    aliases = [_normalize_query(alias) for alias in entry.get("aliases") or []]
    if text in aliases:
        return _SCORE_EXACT_ALIAS

    score = 0
    if name and (text in name or name in text):
        score += _SCORE_NAME_OVERLAP
    for alias in aliases:
        if alias and (alias in text or text in alias):
            score += _SCORE_ALIAS_OVERLAP

    for keyword in entry.get("keywords") or []:
        keyword_text = _normalize_query(keyword)
        if keyword_text and keyword_text in text:
            score += _SCORE_KEYWORD_HIT

    body = " ".join(
        [
            str(entry.get("district") or ""),
            str(entry.get("note") or ""),
            *(str(item) for item in entry.get("highlights") or []),
        ]
    )
    if text and text in _normalize_query(body):
        score += _SCORE_BODY_HIT
    return score


class KnowledgeRetriever:
    """检索接口：换向量后端时实现同一方法即可，工具契约不变。"""

    def retrieve(self, city: str, query: str = "", limit: int = 8) -> dict[str, Any]:
        raise NotImplementedError


class KeywordRetriever(KnowledgeRetriever):
    """对 CORPUS_DIR 下的策展 JSON 做词项打分；进程内懒加载并缓存索引。"""

    def __init__(self, corpus_dir: Path | None = None):
        self._corpus_dir = corpus_dir or CORPUS_DIR
        self._index: dict[str, dict[str, Any]] | None = None

    def _load_index(self) -> dict[str, dict[str, Any]]:
        if self._index is not None:
            return self._index

        index: dict[str, dict[str, Any]] = {}
        for path in sorted(self._corpus_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            keys = {normalize_city_name(data.get("city") or "")}
            keys.update(normalize_city_name(alias) for alias in data.get("aliases") or [])
            keys.discard("")
            for key in keys:
                index.setdefault(key, data)

        self._index = index
        return index

    def _city_data(self, city: str) -> dict[str, Any] | None:
        index = self._load_index()
        key = normalize_city_name(city)
        if not key:
            return None
        if key in index:
            return index[key]
        for known, data in index.items():
            if known and (known in key or key in known):
                return data
        return None

    def city_guide(self, city: str) -> dict[str, Any] | None:
        data = self._city_data(city)
        if not data:
            return None
        return {
            "city": str(data.get("city") or city),
            "summary": str(data.get("summary") or ""),
            "districts": [item for item in data.get("districts") or [] if isinstance(item, dict)],
            "practical_tips": [str(item) for item in data.get("practical_tips") or []],
            "seasonal": [item for item in data.get("seasonal") or [] if isinstance(item, dict)],
        }

    def entries(self, city: str, query: str = "", limit: int = 8) -> list[dict[str, Any]]:
        data = self._city_data(city)
        if not data:
            return []

        attractions = [item for item in data.get("attractions") or [] if isinstance(item, dict)]
        if _normalize_query(query):
            # 语料顺序作为同分稳定键，保证检索结果可复现。
            ranked = [
                item
                for _, item in sorted(
                    enumerate(attractions),
                    key=lambda pair: (-_entry_score(query, pair[1]), pair[0]),
                )
                if _entry_score(query, item) > 0
            ]
        else:
            ranked = list(attractions)
        return ranked[: max(0, int(limit))]

    def retrieve(self, city: str, query: str = "", limit: int = 8) -> dict[str, Any]:
        data = self._city_data(city)
        if not data:
            return {
                "provider_status": "not_covered",
                "city": str(city or ""),
                "query": str(query or ""),
                "city_guide": None,
                "entries": [],
                "coverage": "none",
                "note": "本地知识库暂未覆盖该目的地，已跳过知识检索；行程事实仍以高德候选为准。",
            }

        guide = self.city_guide(city)
        entries = self.entries(city, query=query, limit=limit)
        if entries:
            coverage = "full"
        elif guide and (guide.get("summary") or guide.get("practical_tips")):
            coverage = "partial"
        else:
            coverage = "none"

        return {
            "provider_status": "knowledge_base",
            "city": str(data.get("city") or city),
            "query": str(query or ""),
            "city_guide": guide,
            "entries": entries,
            "coverage": coverage,
            "note": (
                "知识库为人工策展的背景知识，仅用于补充景点详情与本地规则；"
                "实时价格、库存、班次与营业状态以官方渠道为准。"
            ),
        }
