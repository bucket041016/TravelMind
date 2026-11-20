r"""全国重点旅游城市高德官方 Web 服务 POI 离线采集与导出工具。

功能特性：
1. 调用高德开放平台官方 /v3/place/text 接口（复用项目 .env 中的高德 Key），完全合规。
2. 主存储采用 SQLite（data/amap_poi_corpus.db）：按 poi_id 唯一去重、自带任务状态表，
   支持任意中断后的断点续传，绝不重复消耗配额。
3. 内置 QPS 限速、QPS 触发退避重试（infocode=10021）、日配额触顶自动保存并优雅停机（infocode=10003）。
4. 支持一键导出：城市结构化 JSON、全量合并 CSV，以及可直接导入 TravelMind RAG 知识库的城市片区 Markdown。

常用命令示例：
  # 先试跑 3 个城市（或指定城市），每个分类拉取前 2 页
  .\.venv\Scripts\python.exe scripts\collect_amap_pois.py run --cities 深圳,成都,西安 --pages-per-category 2

  # 按全国 30 个重点旅游城市分批跑（带每日请求上限，配额用完自动暂停，次日重跑自动续传）
  .\.venv\Scripts\python.exe scripts\collect_amap_pois.py run --pages-per-category 5 --max-requests 800

  # 查看本地采集统计与进度
  .\.venv\Scripts\python.exe scripts\collect_amap_pois.py stats

  # 导出为 JSON、CSV 与 RAG Markdown 笔记
  .\.venv\Scripts\python.exe scripts\collect_amap_pois.py export
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any

from dotenv import load_dotenv
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "amap_poi_corpus.db"
DEFAULT_EXPORT_DIR = PROJECT_ROOT / "data" / "exports"
AMAP_TEXT_SEARCH_URL = "https://restapi.amap.com/v3/place/text"

# 全国 30 个重点旅游城市（覆盖热门一线、新一线、历史文化、海滨海岛、山水古镇与西北/西南目的地）
TOP_TOURIST_CITIES: list[str] = [
    "北京", "上海", "广州", "深圳", "成都", "重庆",
    "杭州", "西安", "南京", "苏州", "厦门", "三亚",
    "青岛", "长沙", "武汉", "桂林", "丽江", "大理",
    "昆明", "哈尔滨", "拉萨", "福州", "扬州", "洛阳",
    "敦煌", "珠海", "宁波", "大连", "贵阳", "乌鲁木齐",
]

# 分类采集配置：按高德标准 POI 分类码（types）拆分，覆盖景点、室内场馆、美食与酒店
CATEGORY_SPECS: dict[str, dict[str, str]] = {
    "scenic": {
        "label": "风景名胜",
        "types": "110000",
        "keywords": "",
    },
    "indoor_culture": {
        "label": "博物馆与室内文化",
        "types": "140100|140200|140600",
        "keywords": "",
    },
    "food_local": {
        "label": "热门餐饮与地方菜",
        "types": "050100|050400",
        "keywords": "特色菜|老字号|美食",
    },
    "hotel": {
        "label": "酒店与住宿",
        "types": "100100|100200",
        "keywords": "",
    },
    "transport_hub": {
        "label": "交通枢纽（高铁/机场/码头）",
        "types": "150200|150104|150300",
        "keywords": "火车站|高铁站|机场|客运港|码头",
    },
}

QUOTA_EXCEEDED_CODES = {"10003", "10004", "10044"}
QPS_LIMIT_CODES = {"10019", "10020", "10021"}


class QuotaExceededError(RuntimeError):
    """高德 API 日配额耗尽异常，用于触发断点保存并优雅退出。"""


def _load_amap_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    for env_name in ("AMAP_MAPS_API_KEY", "AMAP_API_KEY", "GAODE_API_KEY"):
        val = (os.getenv(env_name) or "").strip()
        if val and not val.startswith("your_"):
            return val
    return ""


def _clean_text(value: Any) -> str:
    if value is None or isinstance(value, (list, dict)):
        return ""
    return str(value).strip()


def _parse_float(value: Any) -> float | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_location(loc: Any) -> tuple[float | None, float | None]:
    text = _clean_text(loc)
    if "," not in text:
        return None, None
    parts = text.split(",", 1)
    return _parse_float(parts[0]), _parse_float(parts[1])


def _init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pois (
            poi_id TEXT PRIMARY KEY,
            city TEXT NOT NULL,
            category TEXT NOT NULL,
            category_label TEXT NOT NULL,
            name TEXT NOT NULL,
            type_name TEXT,
            typecode TEXT,
            pname TEXT,
            cityname TEXT,
            adname TEXT,
            business_area TEXT,
            address TEXT,
            lng REAL,
            lat REAL,
            rating REAL,
            cost REAL,
            tel TEXT,
            tag TEXT,
            raw_json TEXT,
            fetched_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_pois_city_cat ON pois(city, category);
        CREATE INDEX IF NOT EXISTS idx_pois_rating ON pois(rating DESC);
        CREATE INDEX IF NOT EXISTS idx_pois_adname ON pois(city, adname);

        CREATE TABLE IF NOT EXISTS crawl_tasks (
            city TEXT NOT NULL,
            category TEXT NOT NULL,
            page INTEGER NOT NULL,
            status TEXT NOT NULL,
            returned_count INTEGER NOT NULL DEFAULT 0,
            error_msg TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (city, category, page)
        );
        """
    )
    conn.commit()
    return conn


def _fetch_amap_page(
    session: requests.Session,
    api_key: str,
    city: str,
    spec: dict[str, str],
    page: int,
    offset: int = 20,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    params: dict[str, str] = {
        "key": api_key,
        "city": city,
        "citylimit": "true",
        "children": "0",
        "offset": str(max(1, min(offset, 25))),
        "page": str(page),
        "extensions": "all",
    }
    if spec.get("types"):
        params["types"] = spec["types"]
    if spec.get("keywords"):
        params["keywords"] = spec["keywords"]

    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(AMAP_TEXT_SEARCH_URL, params=params, timeout=15)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            last_error = f"网络异常：{exc}"
            time.sleep(1.0 * attempt)
            continue

        status = str(payload.get("status") or "")
        infocode = str(payload.get("infocode") or "")
        info = str(payload.get("info") or "")

        if status == "1":
            pois = payload.get("pois")
            return pois if isinstance(pois, list) else []

        if infocode in QUOTA_EXCEEDED_CODES:
            raise QuotaExceededError(f"高德 API 配额受限（infocode={infocode}, info={info}）")

        if infocode in QPS_LIMIT_CODES:
            wait_sec = 1.5 * attempt
            print(f"  [限流退避] {city}/{spec['label']} 第{page}页 触发 QPS 限流，等待 {wait_sec:.1f}s 后重试...")
            time.sleep(wait_sec)
            last_error = f"QPS 限流：{infocode} {info}"
            continue

        raise RuntimeError(f"高德接口返回错误（infocode={infocode}, info={info}）")

    raise RuntimeError(last_error or "请求失败")


def _upsert_pois(
    conn: sqlite3.Connection,
    city: str,
    category: str,
    category_label: str,
    pois: list[dict[str, Any]],
) -> int:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = 0
    for poi in pois:
        if not isinstance(poi, dict):
            continue
        poi_id = _clean_text(poi.get("id"))
        name = _clean_text(poi.get("name"))
        if not poi_id or not name:
            continue
        biz = poi.get("biz_ext") if isinstance(poi.get("biz_ext"), dict) else {}
        lng, lat = _parse_location(poi.get("location"))
        rating = _parse_float(biz.get("rating"))
        cost = _parse_float(biz.get("cost"))
        cur = conn.execute(
            """
            INSERT INTO pois (
                poi_id, city, category, category_label, name, type_name, typecode,
                pname, cityname, adname, business_area, address, lng, lat,
                rating, cost, tel, tag, raw_json, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(poi_id) DO UPDATE SET
                rating = COALESCE(excluded.rating, pois.rating),
                cost = COALESCE(excluded.cost, pois.cost),
                business_area = COALESCE(NULLIF(excluded.business_area, ''), pois.business_area),
                address = COALESCE(NULLIF(excluded.address, ''), pois.address),
                tag = COALESCE(NULLIF(excluded.tag, ''), pois.tag),
                raw_json = excluded.raw_json,
                fetched_at = excluded.fetched_at
            """,
            (
                poi_id,
                city,
                category,
                category_label,
                name,
                _clean_text(poi.get("type")),
                _clean_text(poi.get("typecode")),
                _clean_text(poi.get("pname")),
                _clean_text(poi.get("cityname")),
                _clean_text(poi.get("adname")),
                _clean_text(poi.get("business_area")),
                _clean_text(poi.get("address")),
                lng,
                lat,
                rating,
                cost,
                _clean_text(poi.get("tel")),
                _clean_text(poi.get("tag")),
                json.dumps(poi, ensure_ascii=False),
                now,
            ),
        )
        inserted += cur.rowcount
    return inserted


def _mark_task(
    conn: sqlite3.Connection,
    city: str,
    category: str,
    page: int,
    status: str,
    returned_count: int = 0,
    error_msg: str = "",
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO crawl_tasks (city, category, page, status, returned_count, error_msg, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(city, category, page) DO UPDATE SET
            status = excluded.status,
            returned_count = excluded.returned_count,
            error_msg = excluded.error_msg,
            updated_at = excluded.updated_at
        """,
        (city, category, page, status, returned_count, error_msg, now),
    )


def cmd_run(args: argparse.Namespace) -> int:
    api_key = _load_amap_key()
    if not api_key:
        print("错误：未在 .env 中检测到有效的高德 Key（AMAP_MAPS_API_KEY / AMAP_API_KEY / GAODE_API_KEY）。")
        return 1

    cities = (
        [c.strip() for c in args.cities.replace("，", ",").split(",") if c.strip()]
        if args.cities
        else list(TOP_TOURIST_CITIES)
    )
    categories = (
        [c.strip() for c in args.categories.replace("，", ",").split(",") if c.strip() in CATEGORY_SPECS]
        if args.categories
        else list(CATEGORY_SPECS.keys())
    )
    if not categories:
        print(f"错误：无效分类，可选分类为：{', '.join(CATEGORY_SPECS.keys())}")
        return 1

    pages = max(1, min(int(args.pages_per_category), 25))
    offset = max(1, min(int(args.page_size), 25))
    max_requests = max(1, int(args.max_requests))
    delay = max(0.25, float(args.delay))

    conn = _init_db(Path(args.db))
    done_rows = conn.execute("SELECT city, category, page, status, returned_count FROM crawl_tasks").fetchall()
    done_map = {(r["city"], r["category"], int(r["page"])): (r["status"], int(r["returned_count"])) for r in done_rows}

    total_planned = len(cities) * len(categories) * pages
    print(
        f"准备采集：{len(cities)} 个城市 x {len(categories)} 个分类 x {pages} 页"
        f"（计划最多 {total_planned} 次请求，本次上限 {max_requests} 次，间隔 {delay:.2f}s）"
    )
    print(f"SQLite 数据库：{Path(args.db).resolve()}")

    session = requests.Session()
    requests_made = 0
    skipped = 0
    total_saved = 0

    try:
        for city in cities:
            for category in categories:
                spec = CATEGORY_SPECS[category]
                for page in range(1, pages + 1):
                    prev = done_map.get((city, category, page))
                    if prev and prev[0] in {"done", "exhausted"}:
                        skipped += 1
                        if prev[0] == "exhausted" or prev[1] < offset:
                            break
                        continue

                    if requests_made >= max_requests:
                        print(f"\n已达到本次请求上限（{max_requests} 次），进度已保存。下次直接重跑同一命令即可断点续传。")
                        return 0

                    if requests_made > 0:
                        time.sleep(delay)

                    requests_made += 1
                    try:
                        pois = _fetch_amap_page(session, api_key, city, spec, page=page, offset=offset)
                    except QuotaExceededError as exc:
                        print(f"\n[配额触顶暂停] {exc}")
                        print("当前进度已落盘，次日配额刷新后重跑相同命令会自动从断点继续。")
                        return 0
                    except Exception as exc:
                        _mark_task(conn, city, category, page, "error", 0, str(exc))
                        conn.commit()
                        print(f"  [失败] {city} / {spec['label']} 第 {page} 页：{exc}")
                        continue

                    saved_count = _upsert_pois(conn, city, category, spec["label"], pois)
                    total_saved += saved_count
                    status = "exhausted" if len(pois) < offset else "done"
                    _mark_task(conn, city, category, page, status, len(pois))
                    conn.commit()
                    print(
                        f"  [{requests_made}/{max_requests}] {city} / {spec['label']} 第 {page} 页："
                        f"返回 {len(pois)} 条，入库/更新 {saved_count} 条"
                    )
                    if status == "exhausted":
                        break
    except KeyboardInterrupt:
        print("\n检测到手动中断，已完成的页面已全部持久化保存，重跑将自动断点续传。")
    finally:
        conn.close()

    print(
        f"\n本次执行结束：实际请求 {requests_made} 次，跳过已完成 {skipped} 页，累计入库/更新 {total_saved} 条 POI。"
    )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"数据库尚不存在：{db_path}")
        return 0

    conn = _init_db(db_path)
    total_pois = conn.execute("SELECT COUNT(*) FROM pois").fetchone()[0]
    total_cities = conn.execute("SELECT COUNT(DISTINCT city) FROM pois").fetchone()[0]
    done_tasks = conn.execute("SELECT COUNT(*) FROM crawl_tasks WHERE status IN ('done', 'exhausted')").fetchone()[0]
    err_tasks = conn.execute("SELECT COUNT(*) FROM crawl_tasks WHERE status = 'error'").fetchone()[0]

    print(f"数据库：{db_path.resolve()}")
    print(f"已入库去重 POI 总数：{total_pois} 条（覆盖 {total_cities} 个城市）")
    print(f"已完成分页任务：{done_tasks} 页 | 失败待重试：{err_tasks} 页")

    print("\n按分类统计：")
    for row in conn.execute(
        "SELECT category, category_label, COUNT(*) AS cnt, ROUND(AVG(rating), 2) AS avg_rating "
        "FROM pois GROUP BY category, category_label ORDER BY cnt DESC"
    ):
        print(f"  - {row['category_label']} ({row['category']}): {row['cnt']} 条（均分 {row['avg_rating'] or '-'}）")

    print("\n按城市统计（Top 30）：")
    for row in conn.execute(
        "SELECT city, COUNT(*) AS cnt, "
        "SUM(CASE WHEN category='scenic' THEN 1 ELSE 0 END) AS scenic_cnt, "
        "SUM(CASE WHEN category='indoor_culture' THEN 1 ELSE 0 END) AS indoor_cnt, "
        "SUM(CASE WHEN category='food_local' THEN 1 ELSE 0 END) AS food_cnt, "
        "SUM(CASE WHEN category='hotel' THEN 1 ELSE 0 END) AS hotel_cnt, "
        "SUM(CASE WHEN category='transport_hub' THEN 1 ELSE 0 END) AS hub_cnt "
        "FROM pois GROUP BY city ORDER BY cnt DESC LIMIT 30"
    ):
        print(
            f"  - {row['city']}: 共 {row['cnt']} 条"
            f"（景点 {row['scenic_cnt']} / 室内馆 {row['indoor_cnt']} / 美食 {row['food_cnt']} / 酒店 {row['hotel_cnt']} / 枢纽 {row['hub_cnt']}）"
        )
    conn.close()
    return 0


def _median(values: list[float]) -> float | None:
    clean = sorted(v for v in values if v is not None and v > 0)
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2 == 1:
        return round(clean[mid], 1)
    return round((clean[mid - 1] + clean[mid]) / 2.0, 1)


def _build_city_profile(city: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """基于本地真实高德 POI 聚合城市交通枢纽、热门游玩片区与真实人均价格基线。"""
    district_buckets: dict[str, dict[str, int]] = {}
    food_costs: list[float] = []
    hotel_costs_all: list[float] = []
    hotel_costs_budget: list[float] = []
    hotel_costs_comfort: list[float] = []
    hotel_costs_luxury: list[float] = []
    hubs: list[dict[str, Any]] = []
    seen_hub_names: set[str] = set()

    for item in items:
        cat = item["category"]
        adname = (item.get("adname") or "").strip()
        cost = item.get("cost")
        if adname and cat in {"scenic", "indoor_culture", "food_local", "hotel"}:
            bucket = district_buckets.setdefault(
                adname, {"scenic": 0, "indoor": 0, "food": 0, "hotel": 0, "total": 0}
            )
            if cat == "scenic":
                bucket["scenic"] += 1
            elif cat == "indoor_culture":
                bucket["indoor"] += 1
            elif cat == "food_local":
                bucket["food"] += 1
            elif cat == "hotel":
                bucket["hotel"] += 1
            bucket["total"] += 1

        if cat == "food_local" and cost and 15 <= cost <= 1000:
            food_costs.append(float(cost))
        elif cat == "hotel" and cost and 60 <= cost <= 5000:
            c = float(cost)
            hotel_costs_all.append(c)
            if c <= 280:
                hotel_costs_budget.append(c)
            elif c <= 650:
                hotel_costs_comfort.append(c)
            else:
                hotel_costs_luxury.append(c)
        elif cat == "transport_hub":
            name = item["name"]
            if name not in seen_hub_names and any(k in name for k in ("站", "机场", "码头", "港")):
                # 过滤掉纯停车场/出入口/售票厅子点，保留主枢纽
                if not any(noise in name for noise in ("停车场", "售票", "出口", "入口", "卫生间", "充电", "贵宾")):
                    seen_hub_names.add(name)
                    hubs.append(
                        {
                            "name": name,
                            "adname": adname,
                            "address": item.get("address") or "",
                            "lng": item.get("lng"),
                            "lat": item.get("lat"),
                            "type_name": item.get("type_name") or "",
                        }
                    )

    top_districts = sorted(
        (
            {
                "district": dist,
                "scenic": counts["scenic"],
                "indoor_culture": counts["indoor"],
                "food_local": counts["food"],
                "hotel": counts["hotel"],
                "play_score": counts["scenic"] * 2 + counts["indoor"] * 2 + counts["food"],
            }
            for dist, counts in district_buckets.items()
        ),
        key=lambda d: (-d["play_score"], -d["scenic"], d["district"]),
    )[:5]

    return {
        "city": city,
        "total_pois": len(items),
        "major_hubs": hubs[:8],
        "top_districts": top_districts,
        "price_baseline": {
            "food_median_cost": _median(food_costs),
            "food_samples": len(food_costs),
            "hotel_median_cost": _median(hotel_costs_all),
            "hotel_budget_median": _median(hotel_costs_budget),
            "hotel_comfort_median": _median(hotel_costs_comfort),
            "hotel_luxury_median": _median(hotel_costs_luxury),
            "hotel_samples": len(hotel_costs_all),
        },
    }


def cmd_export(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"数据库尚不存在：{db_path}")
        return 1

    export_dir = Path(args.export_dir)
    json_dir = export_dir / "json"
    rag_dir = export_dir / "rag_notes"
    json_dir.mkdir(parents=True, exist_ok=True)
    rag_dir.mkdir(parents=True, exist_ok=True)

    conn = _init_db(db_path)
    rows = conn.execute(
        """
        SELECT poi_id, city, category, category_label, name, type_name, adname,
               business_area, address, lng, lat, rating, cost, tag, fetched_at
        FROM pois
        ORDER BY city ASC, category ASC, COALESCE(rating, 0) DESC, name ASC
        """
    ).fetchall()

    # 1. 导出全量 CSV
    csv_path = export_dir / "amap_pois.csv"
    fieldnames = [
        "poi_id", "city", "category", "category_label", "name", "type_name",
        "adname", "business_area", "address", "lng", "lat", "rating", "cost", "tag", "fetched_at",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in fieldnames})

    # 2. 按城市分组导出结构化 JSON 与 RAG 攻略参考 Markdown
    by_city: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item = {k: row[k] for k in fieldnames}
        by_city.setdefault(row["city"], []).append(item)

    city_profiles: dict[str, dict[str, Any]] = {}
    for city, items in by_city.items():
        profile = _build_city_profile(city, items)
        city_profiles[city] = profile
        city_json = {
            "city": city,
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_pois": len(items),
            "profile": profile,
            "categories": {
                cat: [x for x in items if x["category"] == cat]
                for cat in CATEGORY_SPECS
            },
        }
        (json_dir / f"{city}.json").write_text(
            json.dumps(city_json, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 生成可直接放进 knowledge_base/custom/ 的高德真实片区、枢纽、价格基线与高分清单 Markdown
        md_lines = [
            "---",
            f"title: {city}高德真实 POI 片区与价格画像",
            f"city: {city}",
            "category: 离线高德POI汇总",
            "tags: 景点, 室内场馆, 美食, 酒店, 片区分布, 交通枢纽, 预算参考",
            "source: 高德开放平台离线采集与统计聚合",
            "---",
            "",
            f"## {city}核心游玩片区、交通枢纽与真实消费参考",
        ]
        if profile["major_hubs"]:
            hub_str = "、".join(
                f"{h['name']}（{h['adname']}）" if h.get("adname") else h["name"]
                for h in profile["major_hubs"][:6]
            )
            md_lines.append(f"- **主要到达与返程交通枢纽**：{hub_str}。")
        if profile["top_districts"]:
            dist_parts = [
                f"{d['district']}（景点 {d['scenic']} / 室内馆 {d['indoor_culture']} / 餐饮 {d['food_local']} / 酒店 {d['hotel']}）"
                for d in profile["top_districts"][:4]
            ]
            md_lines.append(f"- **高密度游玩与住宿核心片区（建议按片区串线减少跨区折返）**：{'；'.join(dist_parts)}。")
        pb = profile["price_baseline"]
        price_bits = []
        if pb.get("food_median_cost"):
            price_bits.append(f"热门餐饮人均中位数约 {int(pb['food_median_cost'])} 元（样本 {pb['food_samples']} 家）")
        if pb.get("hotel_budget_median") or pb.get("hotel_comfort_median") or pb.get("hotel_luxury_median"):
            h_bits = []
            if pb.get("hotel_budget_median"):
                h_bits.append(f"经济约 {int(pb['hotel_budget_median'])} 元/晚")
            if pb.get("hotel_comfort_median"):
                h_bits.append(f"舒适约 {int(pb['hotel_comfort_median'])} 元/晚")
            if pb.get("hotel_luxury_median"):
                h_bits.append(f"高端约 {int(pb['hotel_luxury_median'])} 元/晚")
            price_bits.append("酒店参考中位价：" + " / ".join(h_bits) + f"（样本 {pb['hotel_samples']} 家）")
        if price_bits:
            md_lines.append(f"- **本地真实消费基线（高德样本聚合）**：{'；'.join(price_bits)}。")
        md_lines.append("")

        for cat, spec in CATEGORY_SPECS.items():
            if cat == "transport_hub":
                continue
            cat_items = [x for x in items if x["category"] == cat]
            if not cat_items:
                continue
            md_lines.append(f"## {city}{spec['label']}高分推荐（节选）")
            for item in cat_items[:15]:
                area = item["adname"] or item["business_area"] or city
                rating_txt = f"评分 {item['rating']}" if item["rating"] else "暂无评分"
                cost_txt = f"人均约 {int(item['cost'])} 元" if item["cost"] else ""
                addr_txt = f"地址：{item['address']}" if item["address"] else ""
                meta_parts = [p for p in (area, rating_txt, cost_txt, addr_txt) if p]
                md_lines.append(f"- {item['name']}（{'，'.join(meta_parts)}）")
            md_lines.append("")

        (rag_dir / f"amap_{city}_pois.md").write_text("\n".join(md_lines), encoding="utf-8")

    profiles_path = export_dir / "city_profiles.json"
    profiles_path.write_text(json.dumps(city_profiles, ensure_ascii=False, indent=2), encoding="utf-8")

    conn.close()
    print(f"导出完成：共 {len(rows)} 条 POI，覆盖 {len(by_city)} 个城市。")
    print(f"  - 全量 CSV：{csv_path.resolve()}")
    print(f"  - 城市画像总表：{profiles_path.resolve()}")
    print(f"  - 城市 JSON 目录：{json_dir.resolve()}")
    print(f"  - RAG Markdown 目录：{rag_dir.resolve()}")
    if args.sync_to_rag:
        custom_dir = PROJECT_ROOT / "knowledge_base" / "custom"
        custom_dir.mkdir(parents=True, exist_ok=True)
        for md_file in rag_dir.glob("amap_*_pois.md"):
            (custom_dir / md_file.name).write_text(md_file.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  - 已同步 {len(by_city)} 篇 Markdown 至 RAG 自定义知识库：{custom_dir.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="全国重点旅游城市高德官方 POI 离线采集与导出工具")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite 数据库路径（默认 data/amap_poi_corpus.db）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="开始或断点续传采集高德 POI")
    p_run.add_argument("--cities", default="", help="逗号分隔的城市列表；留空默认采集全国 30 个重点旅游城市")
    p_run.add_argument(
        "--categories",
        default="",
        help=f"逗号分隔的分类列表；默认全部（可选：{','.join(CATEGORY_SPECS.keys())}）",
    )
    p_run.add_argument("--pages-per-category", type=int, default=3, help="每个城市每个分类最多翻页数（默认 3 页，每页 20 条）")
    p_run.add_argument("--page-size", type=int, default=20, help="每页返回条数（1-25，默认 20）")
    p_run.add_argument("--max-requests", type=int, default=500, help="本次运行最多发起的 API 请求数（默认 500）")
    p_run.add_argument("--delay", type=float, default=0.5, help="相邻请求间隔秒数（默认 0.5s，安全低于高德 3 QPS 限制）")
    p_run.set_defaults(func=cmd_run)

    p_stats = sub.add_parser("stats", help="查看已采集 POI 统计与进度")
    p_stats.set_defaults(func=cmd_stats)

    p_export = sub.add_parser("export", help="从 SQLite 导出 CSV、城市 JSON 和 RAG Markdown")
    p_export.add_argument("--export-dir", default=str(DEFAULT_EXPORT_DIR), help="导出输出目录（默认 data/exports）")
    p_export.add_argument(
        "--sync-to-rag",
        action="store_true",
        help="将生成的城市高分 POI Markdown 同步复制到 knowledge_base/custom/ 供 RAG 检索",
    )
    p_export.set_defaults(func=cmd_export)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
