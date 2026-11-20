"""RAG 混合检索知识库与前端自由编辑契约测试（全离线、零重型依赖）。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sync.knowledge.rag_service import OpenAICompatibleEmbedder, TravelRAGService


def _load_markdown_writer():
    """在不触发 sync.multi_agent.__init__（依赖 fastmcp/langchain）的前提下加载 markdown_writer。"""
    pkg_name = "_tm_isolated_multi_agent"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(PROJECT_ROOT / "sync" / "multi_agent")]
        sys.modules[pkg_name] = pkg

    def _load_sub(name: str, filename: str):
        full = f"{pkg_name}.{name}"
        if full in sys.modules:
            return sys.modules[full]
        spec = importlib.util.spec_from_file_location(
            full,
            PROJECT_ROOT / "sync" / "multi_agent" / filename,
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full] = mod
        spec.loader.exec_module(mod)
        return mod

    _load_sub("constants", "constants.py")
    return _load_sub("markdown_writer", "markdown_writer.py")


def _disabled_embedder() -> OpenAICompatibleEmbedder:
    """构造显式关闭向量调用的 Embedder，保证测试不受本机环境变量干扰。"""
    embedder = OpenAICompatibleEmbedder(api_key="", model="")
    embedder.api_key = ""
    embedder.model = ""
    return embedder


class TravelRAGUnifiedCorpusTests(unittest.TestCase):
    """验证统一索引 9 城策展 JSON + 内置 Markdown 攻略及默认 BM25+元数据检索。"""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="tm_rag_unified_"))
        shutil.copytree(PROJECT_ROOT / "knowledge_base" / "builtin", self.tmp_dir / "builtin")
        (self.tmp_dir / "custom").mkdir(parents=True, exist_ok=True)
        self.service = TravelRAGService(
            base_dir=self.tmp_dir,
            city_corpus_dir=PROJECT_ROOT / "sync" / "knowledge" / "cities",
            embedder=_disabled_embedder(),
        )

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_indexes_curated_json_and_builtin_markdown(self):
        listing = self.service.list_documents()
        self.assertGreaterEqual(listing["total_docs"], 12)
        self.assertGreaterEqual(listing["total_chunks"], 30)
        self.assertEqual(listing["retrieval_mode"], "bm25_metadata")
        self.assertFalse(listing["vector_enabled"])

        categories = {doc["category"] for doc in listing["documents"]}
        self.assertIn("策展城市库", categories)

        cities = {doc["city"] for doc in listing["documents"]}
        for expected in ("深圳", "广州", "厦门", "北京", "上海", "杭州", "成都", "西安", "福州", "三亚", "重庆"):
            self.assertIn(expected, cities)

    def test_shenzhen_curated_rainy_retrieval_and_city_isolation(self):
        hits = self.service.retrieve("雨天室内博物馆美术馆避雨替代", city="深圳", top_k=4)
        self.assertTrue(hits)
        self.assertTrue(all(hit["city"] in {"深圳", "通用"} for hit in hits))
        self.assertTrue(any(hit["city"] == "深圳" for hit in hits))
        self.assertEqual(hits[0]["retrieval_mode"], "bm25_metadata")
        self.assertEqual(hits[0]["source_meta"]["provider"], "knowledge_base")
        self.assertEqual(hits[0]["source_meta"]["kind"], "knowledge_base")

    def test_builtin_sanya_and_chongqing_retrieval(self):
        sanya_hits = self.service.retrieve("免税店 海棠湾 亚龙湾 海鲜 避坑", city="三亚", top_k=4)
        self.assertTrue(sanya_hits)
        self.assertEqual(sanya_hits[0]["city"], "三亚")
        self.assertTrue(all(hit["city"] in {"三亚", "通用"} for hit in sanya_hits))

        cq_hits = self.service.retrieve("洪崖洞 夜景 轻轨 火锅 动线", city="重庆", top_k=4)
        self.assertTrue(cq_hits)
        self.assertEqual(cq_hits[0]["city"], "重庆")
        self.assertTrue(all(hit["city"] in {"重庆", "通用"} for hit in cq_hits))

    def test_retrieve_for_plan_returns_structured_context_and_meta(self):
        result = self.service.retrieve_for_plan(
            prefs={
                "destinationCity": "深圳",
                "interests": ["科技地标", "文化艺术", "美食"],
                "preferenceProfile": {"pace": "轻松", "learnedHints": ["优先室内场所"]},
                "freeText": "带父母出行，怕下雨想少走弯路",
            },
            weather={"深圳": "2026-08-15 阵雨 26~31°C"},
            top_k=5,
        )
        self.assertTrue(result["references"])
        self.assertTrue(result["prompt_snippets"])
        meta = result["meta"]
        self.assertEqual(meta["retrieval_mode"], "bm25_metadata")
        self.assertEqual(meta["hit_count"], len(result["references"]))
        self.assertGreaterEqual(meta["total_docs"], 12)
        self.assertEqual(meta["query_city"], "深圳")


class TravelRAGHybridAndCustomTests(unittest.TestCase):
    """验证混合向量 RRF 重排、Embedding 持久化缓存以及自定义文档增删保护。"""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="tm_rag_hybrid_"))
        (self.tmp_dir / "builtin").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "custom").mkdir(parents=True, exist_ok=True)
        (self.tmp_dir / "builtin" / "builtin_sample.md").write_text(
            "---\n"
            "title: 测试内置攻略\n"
            "city: 杭州\n"
            "category: 城市攻略\n"
            "tags: 西湖, 预约\n"
            "---\n\n"
            "## 西湖错峰建议\n"
            "清晨七点前在断桥和苏堤散步人最少，午后可转去中国茶叶博物馆避暑。\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @staticmethod
    def _semantic_embed(texts: list[str]) -> list[list[float]]:
        """确定性 4 维语义向量桩：[咖啡文艺, 海岛度假, 亲子动物, 避坑预约]。"""
        vectors: list[list[float]] = []
        for text in texts:
            v0 = 1.0 if any(k in text for k in ("手冲", "烘焙", "咖啡", "复古街区", "独立书店")) else 0.05
            v1 = 1.0 if any(k in text for k in ("浮潜", "冲浪", "沙滩", "海岛", "帆船")) else 0.05
            v2 = 1.0 if any(k in text for k in ("遛娃", "儿童", "海洋馆", "长隆", "动物园")) else 0.05
            v3 = 1.0 if any(k in text for k in ("闭馆", "预约", "周一", "错峰", "排队")) else 0.05
            vectors.append([v0, v1, v2, v3])
        return vectors

    def test_hybrid_vector_rrf_and_embedding_cache(self):
        call_counter = {"batches": 0, "texts": 0}

        def tracked_embed(texts: list[str]) -> list[list[float]]:
            call_counter["batches"] += 1
            call_counter["texts"] += len(texts)
            return self._semantic_embed(texts)

        service = TravelRAGService(
            base_dir=self.tmp_dir,
            city_corpus_dir=self.tmp_dir / "empty_cities",
            embed_fn=tracked_embed,
            embedder=_disabled_embedder(),
        )
        service.add_custom_document(
            title="上海私藏独立书店与手冲地图",
            content="## 愚园路与安福路\n上午在独立书店翻看画册，下午找巷子里的烘焙豆手冲小店发呆。",
            city="上海",
            tags=["文艺", "小众"],
        )
        service.add_custom_document(
            title="三亚浮潜与帆船体验",
            content="## 蜈支洲岛出海\n清晨报名海岛浮潜和帆船项目，能见度最好。",
            city="三亚",
            tags=["出海", "海岛"],
        )

        # 用语义相近但字面不重合的词查询，验证向量分支参与 RRF 重排
        hits = service.retrieve("复古街区喝咖啡", city="上海", top_k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["retrieval_mode"], "hybrid_bm25_vector")
        self.assertIn("上海私藏独立书店", hits[0]["title"])
        self.assertTrue(any("语义相似" in reason for reason in hits[0]["match_reasons"]))

        cache_file = self.tmp_dir / ".cache" / "embeddings.json"
        self.assertTrue(cache_file.exists())
        cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
        self.assertTrue(cache_data)

        # 重建实例，确认文档向量从磁盘缓存命中，仅对 query 文本调用一次 embed_fn
        before_texts = call_counter["texts"]
        service2 = TravelRAGService(
            base_dir=self.tmp_dir,
            city_corpus_dir=self.tmp_dir / "empty_cities",
            embed_fn=tracked_embed,
            embedder=_disabled_embedder(),
        )
        hits2 = service2.retrieve("复古街区喝咖啡", city="上海", top_k=3)
        self.assertTrue(hits2)
        self.assertEqual(call_counter["texts"] - before_texts, 1)

    def test_custom_doc_crud_validation_and_builtin_delete_protection(self):
        service = TravelRAGService(
            base_dir=self.tmp_dir,
            city_corpus_dir=self.tmp_dir / "empty_cities",
            embedder=_disabled_embedder(),
        )

        with self.assertRaises(ValueError):
            service.add_custom_document(title="", content="这是一段足够长的攻略正文内容。")
        with self.assertRaises(ValueError):
            service.add_custom_document(title="太短", content="短文本")

        created = service.add_custom_document(
            title="我的成都私房茶馆笔记",
            content="## 人民公园鹤鸣茶社\n早上九点半前去临湖竹椅喝盖碗茶，顺便听一段川剧采耳。",
            city="成都",
            tags=["慢节奏", "喝茶"],
        )
        doc_id = created["doc_id"]
        self.assertEqual(created["origin_type"], "custom")

        hits = service.retrieve("人民公园 盖碗茶 慢节奏", city="成都", top_k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["doc_id"], doc_id)

        # 内置文档不可删除（应抛出保护异常）
        builtin_docs = [d for d in service.list_documents()["documents"] if d["origin_type"] != "custom"]
        self.assertTrue(builtin_docs)
        with self.assertRaises(ValueError):
            service.delete_custom_document(builtin_docs[0]["doc_id"])

        # 自定义文档可删除，且删除后索引即时更新
        self.assertTrue(service.delete_custom_document(doc_id))
        self.assertFalse(service.delete_custom_document(doc_id))
        remaining_ids = {d["doc_id"] for d in service.list_documents()["documents"]}
        self.assertNotIn(doc_id, remaining_ids)


class MarkdownWriterAndFrontendContractTests(unittest.TestCase):
    """验证 Markdown 导出 RAG 章节与前端自由编辑 / E2E 选择器契约。"""

    def test_markdown_writer_renders_rag_references_section(self):
        writer = _load_markdown_writer()
        markdown = writer._build_markdown(
            prefs={
                "originCity": "广州",
                "destinationCity": "深圳",
                "startDate": "2026-08-15",
                "days": 1,
                "travelers": 2,
                "budget": 3000,
                "transportMode": "高铁",
                "hotelLevel": "舒适",
            },
            routes={
                "recommended": "train",
                "options": [
                    {"title": "高铁", "summary": "广州南至深圳北约 35 分钟"},
                ],
                "advice": "建议提前买票",
            },
            local_transport={"hub": "深圳北站", "summary": "地铁直达南山"},
            hotels={
                "recommended": {"name": "南山舒适酒店", "address": "南山区科技园", "estimated_price_per_night": 480},
                "area_recommendation": "南山后海",
                "candidates": [],
            },
            weather={"深圳": "晴 25~31°C"},
            weather_advice={"summary": "晴热注意防晒"},
            pois={"attractions": [], "foods": [], "specialty_places": []},
            budget={
                "total_budget": 3000,
                "estimated_total": 1100,
                "within_budget": True,
                "breakdown": {"intercity_transport": 300, "hotel": 480, "activities_and_food": 200, "local_transport": 120},
                "advice": "预算充裕",
            },
            itinerary_days=[
                {
                    "day": 1,
                    "date": "2026-08-15",
                    "theme": "南山看海与艺术",
                    "items": [
                        {
                            "time": "10:00-12:00",
                            "title": "深圳湾公园",
                            "category": "景点",
                            "location": "深圳湾公园",
                            "address": "南山区滨海大道",
                            "transport": "地铁9号线",
                            "duration": "2小时",
                            "estimated_cost": 0,
                            "detail": "海风舒适",
                        }
                    ],
                }
            ],
            rag_references=[
                {
                    "title": "深圳目的地知识库",
                    "section": "南山区动线",
                    "city": "深圳",
                    "content": "深圳湾公园与海上世界顺路，建议傍晚看日落。",
                }
            ],
        )
        self.assertIn("### 攻略知识参考（RAG）", markdown)
        self.assertIn("深圳目的地知识库", markdown)
        self.assertIn("南山区动线", markdown)

    def test_frontend_html_and_js_contracts(self):
        html = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = (PROJECT_ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (PROJECT_ROOT / "web" / "styles.css").read_text(encoding="utf-8")

        # 缓存版本号升级 + RAG 与自由编辑模态框 + E2E 必保选择器
        for token in (
            "v=phase52",
            'id="planButton"',
            'id="editPlanButton"',
            'id="exportButton"',
            'id="exportMenu"',
            'data-scroll-target="daysSection"',
            'data-scroll-target="ragSection"',
            'id="openRagModalButton"',
            'id="ragModal"',
            'id="placePickerModal"',
        ):
            self.assertIn(token, html)

        # 自由编辑 + RAG 交互 + main 既有异步/追问/知识库能力
        for token in (
            'id="daysSection"',
            'id="ragSection"',
            "BACKEND_STEP_TO_STAGE",
            "RAGKnowledgeAgent",
            "sendPlanAsync",
            "sendPlanSync",
            "/api/refine-plan",
            "/api/rag/docs",
            "/api/rag/search",
            "/api/poi/search",
            "renderKnowledgeDetail",
            "renderRagReferences",
            "pushUndoSnapshot",
            "undoPlanEdit",
            "redoPlanEdit",
            "addNewItineraryDay",
            "deleteItineraryDay",
            "moveItemBetweenDays",
            "openPlacePickerModal",
            "openRagModal",
            "selectHotelCandidate",
            "selectIntercityMode",
            'data-action="delete"',
            'draggable="true"',
        ):
            self.assertIn(token, js)

        # 样式已适配玻璃拟态面板与编辑器
        for token in (
            ".edit-toolbar",
            ".inline-editor-grid",
            ".modal-card",
            ".rag-ref-card",
        ):
            self.assertIn(token, css)


class LocalPoiStoreFallbackTests(unittest.TestCase):
    """验证本地高德离线 SQLite 语料库的分类检索、酒店档位筛选与缺失降级。"""

    def setUp(self):
        import sqlite3
        from sync.knowledge.local_poi_store import (
            corpus_stats,
            search_local_hotels,
            search_local_pois,
        )

        self.search_local_pois = search_local_pois
        self.search_local_hotels = search_local_hotels
        self.corpus_stats = corpus_stats
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="tm_local_poi_"))
        self.db_path = self.tmp_dir / "test_poi.db"

        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(
            """
            CREATE TABLE pois (
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
            """
        )
        rows = [
            ("P1", "南京", "indoor_culture", "博物馆与室内文化", "南京博物院", "科教文化服务;博物馆", "140100", "江苏省", "南京市", "玄武区", "明故宫", "中山东路321号", 118.825, 32.041, 4.9, 0.0, "", "历史,室内", "{}", "2026-11-20"),
            ("P2", "南京", "scenic", "风景名胜", "夫子庙秦淮风光带", "风景名胜;公园广场", "110000", "江苏省", "南京市", "秦淮区", "夫子庙", "贡院西街", 118.789, 32.021, 4.6, 0.0, "", "夜景", "{}", "2026-11-20"),
            ("P3", "南京", "food_local", "热门餐饮与地方菜", "南京大牌档(夫子庙店)", "餐饮服务;中餐厅", "050100", "江苏省", "南京市", "秦淮区", "夫子庙", "大石坝街48号", 118.791, 32.020, 4.7, 88.0, "", "盐水鸭,老字号", "{}", "2026-11-20"),
            ("H1", "南京", "hotel", "酒店与住宿", "南京丽思卡尔顿酒店", "住宿服务;五星级宾馆", "100102", "江苏省", "南京市", "玄武区", "新街口", "中山路18号", 118.784, 32.042, 4.9, 1680.0, "", "豪华", "{}", "2026-11-20"),
            ("H2", "南京", "hotel", "酒店与住宿", "亚朵酒店(南京夫子庙店)", "住宿服务;宾馆酒店", "100100", "江苏省", "南京市", "秦淮区", "夫子庙", "建康路128号", 118.790, 32.023, 4.8, 398.0, "", "商务", "{}", "2026-11-20"),
            ("H3", "南京", "hotel", "酒店与住宿", "如家快捷酒店(新街口店)", "住宿服务;经济型连锁酒店", "100105", "江苏省", "南京市", "秦淮区", "新街口", "洪武路80号", 118.785, 32.038, 4.3, 198.0, "", "经济", "{}", "2026-11-20"),
        ]
        conn.executemany(
            "INSERT INTO pois VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_search_local_pois_and_hotels(self):
        stats = self.corpus_stats(self.db_path)
        self.assertTrue(stats["available"])
        self.assertEqual(stats["total_pois"], 6)
        self.assertEqual(stats["city_count"], 1)

        indoor = self.search_local_pois("南京市", categories=("indoor_culture",), limit=5, db_path=self.db_path)
        self.assertEqual(len(indoor), 1)
        self.assertEqual(indoor[0]["name"], "南京博物院")
        self.assertEqual(indoor[0]["location"], "118.825,32.041")
        self.assertEqual(indoor[0]["biz_ext"]["rating"], "4.9")

        kw_hits = self.search_local_pois("南京", keywords="盐水鸭", limit=5, db_path=self.db_path)
        self.assertEqual(len(kw_hits), 1)
        self.assertIn("南京大牌档", kw_hits[0]["name"])

        lux = self.search_local_hotels("南京", hotel_level="高端", limit=3, db_path=self.db_path)
        self.assertEqual(lux[0]["name"], "南京丽思卡尔顿酒店")

        comfort = self.search_local_hotels("南京", hotel_level="舒适", near="夫子庙", limit=3, db_path=self.db_path)
        self.assertEqual(comfort[0]["name"], "亚朵酒店(南京夫子庙店)")

        budget = self.search_local_hotels("南京", hotel_level="经济", limit=3, db_path=self.db_path)
        self.assertEqual(budget[0]["name"], "如家快捷酒店(新街口店)")

    def test_missing_or_disabled_db_degrades_safely(self):
        self.assertEqual(self.search_local_pois("南京", db_path="off"), [])
        self.assertEqual(self.search_local_hotels("南京", db_path=self.tmp_dir / "missing.db"), [])


if __name__ == "__main__":
    unittest.main()
