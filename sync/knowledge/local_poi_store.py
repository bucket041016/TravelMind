"""本地高德离线 POI 语料库（SQLite）只读查询模块。

由 scripts/collect_amap_pois.py 离线采集并维护的 data/amap_poi_corpus.db 提供数据：
- 当高德实时 Web API 未配置 Key、触发 QPS/日配额限流、超时或返回空结果时，
  作为毫秒级离线兜底检索源，返回与高德 /v3/place/text 完全兼容的 POI 结构（含真实经纬度、地址、评分、人均）。
- 位于 sync/knowledge/ 包内，零第三方重型依赖，可供 MCP Server 与规划器直接安全导入。
- 若本地数据库文件不存在，或环境变量 TRAVELMIND_LOCAL_POI_DB=off，则静默返回空结果，不影响默认运行与单测。
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import sqlite3
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCAL_POI_DB = PROJECT_ROOT / "data" / "amap_poi_corpus.db"


def _resolve_db_path(db_path: Path | str | None = None) -> Path | None:
    if db_path is not None:
        raw = str(db_path).strip()
        if not raw or raw.lower() in {"off", "0", "false", "none"}:
            return None
        path = Path(raw)
        return path if path.exists() else None

    env_val = (os.getenv("TRAVELMIND_LOCAL_POI_DB") or "").strip()
    if env_val.lower() in {"off", "0", "false", "none"}:
        return None
    path = Path(env_val) if env_val else DEFAULT_LOCAL_POI_DB
    return path if path.exists() else None


def _normalize_city(city: str) -> str:
    clean = re.sub(r"\s+", "", str(city or "")).strip()
    if len(clean) > 2 and clean.endswith(("市", "地区")):
        clean = clean[:-1] if clean.endswith("市") else clean[:-2]
    return clean


def _row_to_amap_poi(row: sqlite3.Row) -> dict[str, Any]:
    lng = row["lng"]
    lat = row["lat"]
    location = f"{lng},{lat}" if lng is not None and lat is not None else ""
    biz_ext: dict[str, Any] = {}
    if row["rating"] is not None:
        biz_ext["rating"] = str(row["rating"])
    if row["cost"] is not None:
        biz_ext["cost"] = str(row["cost"])
    return {
        "id": row["poi_id"] or "",
        "name": row["name"] or "",
        "type": row["type_name"] or row["category_label"] or "",
        "typecode": row["typecode"] or "",
        "pname": row["pname"] or "",
        "cityname": row["cityname"] or row["city"] or "",
        "adname": row["adname"] or "",
        "business_area": row["business_area"] or "",
        "address": row["address"] or "",
        "location": location,
        "tel": row["tel"] or "",
        "tag": row["tag"] or "",
        "biz_ext": biz_ext,
        "local_category": row["category"] or "",
        "source": "local_amap_corpus",
    }


def _keyword_score(row: sqlite3.Row, terms: list[str]) -> float:
    if not terms:
        return 0.0
    name = str(row["name"] or "")
    adname = str(row["adname"] or "")
    biz_area = str(row["business_area"] or "")
    type_name = str(row["type_name"] or "")
    address = str(row["address"] or "")
    tag = str(row["tag"] or "")
    score = 0.0
    for term in terms:
        if term == name:
            score += 10.0
        elif term in name:
            score += 6.0
        if term in tag:
            score += 3.5
        if term in biz_area or term in adname:
            score += 3.0
        if term in type_name:
            score += 2.0
        if term in address:
            score += 1.5
    return score


def _split_terms(text: str) -> list[str]:
    clean = str(text or "").strip()
    if not clean:
        return []
    parts = [p.strip() for p in re.split(r"[\s,，、/|;；]+", clean) if len(p.strip()) >= 1]
    if clean not in parts:
        parts.insert(0, clean)
    return parts[:8]


def has_local_corpus(db_path: Path | str | None = None) -> bool:
    return _resolve_db_path(db_path) is not None


def corpus_stats(db_path: Path | str | None = None) -> dict[str, Any]:
    path = _resolve_db_path(db_path)
    if path is None:
        return {"available": False, "total_pois": 0, "city_count": 0}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        total = int(conn.execute("SELECT COUNT(*) FROM pois").fetchone()[0])
        cities = int(conn.execute("SELECT COUNT(DISTINCT city) FROM pois").fetchone()[0])
        conn.close()
        return {"available": total > 0, "total_pois": total, "city_count": cities, "db_path": str(path)}
    except Exception:
        return {"available": False, "total_pois": 0, "city_count": 0}


def search_local_pois(
    city: str,
    *,
    categories: list[str] | tuple[str, ...] | None = None,
    keywords: str = "",
    limit: int = 12,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """按城市、分类与可选关键词从本地离线 SQLite 高德库检索 POI。"""
    path = _resolve_db_path(db_path)
    clean_city = _normalize_city(city)
    if path is None or not clean_city:
        return []

    bounded_limit = max(1, min(int(limit or 12), 40))
    terms = _split_terms(keywords)

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM pois WHERE (city = ? OR cityname LIKE ?)"
        params: list[Any] = [clean_city, f"{clean_city}%"]
        if categories:
            placeholders = ",".join("?" for _ in categories)
            sql += f" AND category IN ({placeholders})"
            params.extend(categories)
        sql += " ORDER BY COALESCE(rating, 0) DESC, name ASC LIMIT 400"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
    except Exception:
        return []

    if not rows:
        return []

    scored: list[tuple[float, float, str, sqlite3.Row]] = []
    for row in rows:
        kw_score = _keyword_score(row, terms)
        if terms and kw_score <= 0:
            continue
        rating = float(row["rating"]) if row["rating"] is not None else 0.0
        scored.append((kw_score, rating, str(row["name"] or ""), row))

    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [_row_to_amap_poi(item[3]) for item in scored[:bounded_limit]]


def search_local_hotels(
    city: str,
    *,
    hotel_level: str = "舒适",
    near: str = "",
    limit: int = 6,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """按住宿档位与就近地标从本地离线高德库检索酒店候选。"""
    path = _resolve_db_path(db_path)
    clean_city = _normalize_city(city)
    if path is None or not clean_city:
        return []

    bounded_limit = max(1, min(int(limit or 6), 20))
    level = str(hotel_level or "舒适").strip()
    near_terms = _split_terms(near)

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM pois WHERE (city = ? OR cityname LIKE ?) AND category = 'hotel' "
            "ORDER BY COALESCE(rating, 0) DESC, name ASC LIMIT 250",
            (clean_city, f"{clean_city}%"),
        ).fetchall()
        conn.close()
    except Exception:
        return []

    if not rows:
        return []

    is_luxury = bool(re.search(r"高端|豪华|五星", level))
    is_budget = bool(re.search(r"经济|省钱|便宜|学生", level))

    scored: list[tuple[float, float, str, sqlite3.Row]] = []
    for row in rows:
        name = str(row["name"] or "")
        type_name = str(row["type_name"] or "")
        blob = f"{name} {type_name}"
        cost = float(row["cost"]) if row["cost"] is not None else 0.0
        rating = float(row["rating"]) if row["rating"] is not None else 4.0

        level_score = 0.0
        if is_luxury:
            if re.search(r"五星|豪华|洲际|万豪|希尔顿|凯悦|丽思|香格里拉|威斯汀|瑞吉|柏悦|华尔道夫|大酒店|度假酒店", blob):
                level_score += 5.0
            if cost >= 550:
                level_score += 3.0
            if re.search(r"青年旅舍|青旅|招待所|如家|汉庭|7天|七天|快捷", blob):
                level_score -= 6.0
        elif is_budget:
            if re.search(r"经济|快捷|如家|汉庭|7天|格林豪泰|全季|桔子|维也纳|轻居|民宿", blob):
                level_score += 3.0
            if 0 < cost <= 320:
                level_score += 4.0
            elif cost >= 700:
                level_score -= 4.0
        else:
            if re.search(r"全季|亚朵|美居|智选假日|欢朋|万枫|维也纳|桔子|商务|精选", blob):
                level_score += 3.5
            if 240 <= cost <= 620:
                level_score += 3.0
            if re.search(r"青年旅舍|青旅|招待所|旅馆", blob):
                level_score -= 5.0

        near_score = _keyword_score(row, near_terms) * 0.8 if near_terms else 0.0
        total_score = level_score + near_score + rating
        scored.append((total_score, rating, name, row))

    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [_row_to_amap_poi(item[3]) for item in scored[:bounded_limit]]
