"""TravelMind 旅游攻略 RAG（混合检索增强生成）服务。

统一索引三类知识语料：
1. sync/knowledge/cities/*.json（main 分支人工策展的 9 城结构化攻略与景点事实）；
2. knowledge_base/builtin/*.md（预置补充城市与通用出行策略 Markdown 攻略）；
3. knowledge_base/custom/*.md（用户通过页面上传或粘贴的私有攻略笔记，持久化管理）。

检索架构：
- 默认模式（bm25_metadata）：纯 Python 中英文分词 + Okapi BM25 + 城市/偏好/天气元数据加权过滤，零额外依赖、离线完全确定。
- 混合向量模式（hybrid_bm25_vector）：当配置 RAG_EMBEDDING_API_KEY（或传入自定义 embed_fn）时，
  通过 OpenAI 兼容 /embeddings 接口增量计算向量并持久化缓存到 knowledge_base/.cache/embeddings.json，
  结合 RRF（Reciprocal Rank Fusion）将 BM25 排名与向量余弦相似度融合重排。

事实红线：
- RAG 仅补充片区动线、预约规则、避坑提醒、雨天室内替代与本地吃法；
- 不生成未验证地点、坐标、实时票价、库存或班次。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
from typing import Any, Callable

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KB_DIR = PROJECT_ROOT / "knowledge_base"
DEFAULT_CITY_CORPUS_DIR = PROJECT_ROOT / "sync" / "knowledge" / "cities"

DOMAIN_TERMS = {
    "避坑", "预约", "闭馆", "排队", "错峰", "动线", "片区", "日落", "夜景", "早茶",
    "火锅", "海鲜", "小吃", "老字号", "博物馆", "美术馆", "海边", "海滩", "沙滩",
    "公园", "古镇", "老街", "步行街", "骑行", "地铁", "打车", "高铁", "机场", "码头",
    "轮渡", "船票", "行李", "寄存", "雨天", "阵雨", "雷阵雨", "室内", "替代", "高温",
    "防晒", "轻松", "紧凑", "亲子", "老人", "长辈", "拍照", "出片", "预算", "免费",
    "门票", "免税", "返程", "酒店", "住宿", "商圈", "枢纽", "夜游", "咖啡",
    "深圳", "广州", "厦门", "福州", "北京", "上海", "杭州", "成都", "重庆", "三亚",
    "南京", "西安", "武汉", "天津", "苏州", "长沙", "青岛", "大理", "丽江", "昆明",
    "桂林", "哈尔滨", "拉萨", "贵阳", "扬州", "洛阳", "香港", "澳门",
    "鼓浪屿", "故宫", "西湖", "外滩", "深圳湾", "南山", "福田", "盐田", "大鹏",
    "永庆坊", "沙面", "广州塔", "洪崖洞", "熊猫", "三坊七巷", "亚龙湾", "海棠湾",
    "兵马俑", "大唐不夜城", "海上世界", "华侨城", "莲花山", "南头古城",
}

STOPWORDS = {
    "的", "了", "和", "与", "或", "在", "是", "有", "为", "以", "及", "等", "这", "那",
    "可以", "建议", "推荐", "适合", "需要", "注意", "一般", "通常", "如果", "以及",
    "一个", "一些", "我们", "你们", "他们", "怎么", "什么", "哪些", "如何",
}


def _clean_city(city: str) -> str:
    text = re.sub(r"\s+", "", str(city or ""))
    return text.removesuffix("市区").removesuffix("市")


def tokenize_zh_en(text: str) -> list[str]:
    """轻量级中英文混合分词（零第三方分词依赖）。"""
    raw = str(text or "").lower()
    tokens: list[str] = []

    for word in re.findall(r"[a-z0-9_]+", raw):
        if len(word) >= 2:
            tokens.append(word)

    for segment in re.findall(r"[\u4e00-\u9fff]+", raw):
        seg_len = len(segment)
        if seg_len == 0:
            continue
        if seg_len == 1:
            if segment not in STOPWORDS:
                tokens.append(segment)
            continue

        for length in (4, 3, 2):
            if seg_len < length:
                continue
            for idx in range(seg_len - length + 1):
                piece = segment[idx : idx + length]
                if piece in DOMAIN_TERMS:
                    tokens.append(piece)

        for idx in range(seg_len - 1):
            bigram = segment[idx : idx + 2]
            if bigram not in STOPWORDS:
                tokens.append(bigram)

    return tokens


def _parse_frontmatter(raw_text: str) -> tuple[dict[str, Any], str]:
    text = raw_text.lstrip("\ufeff")
    match = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n(.*)$", text, re.S)
    if not match:
        return {}, text.strip()

    header, body = match.group(1), match.group(2).strip()
    meta: dict[str, Any] = {}
    for line in header.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "tags":
            meta["tags"] = [
                item.strip()
                for item in re.split(r"[,，、\s]+", value)
                if item.strip()
            ]
        else:
            meta[key] = value
    return meta, body


def _split_long_text(text: str, max_chars: int = 460, overlap: int = 60) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(length, start + max_chars)
        if end < length:
            split_pos = max(
                cleaned.rfind("\n", start + max_chars // 2, end),
                cleaned.rfind("。", start + max_chars // 2, end),
                cleaned.rfind("；", start + max_chars // 2, end),
            )
            if split_pos > start:
                end = split_pos + 1
        part = cleaned[start:end].strip()
        if part:
            chunks.append(part)
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks


def _make_chunk(
    *,
    chunk_id: str,
    doc_id: str,
    title: str,
    section: str,
    city: str,
    category: str,
    tags: list[str],
    source: str,
    origin_type: str,
    content: str,
) -> dict[str, Any]:
    full_text = f"{title} / {section}\n{content}"
    content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()[:16]
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "title": title,
        "section": section,
        "city": _clean_city(city) or "通用",
        "category": category or "旅行攻略",
        "tags": list(tags),
        "source": source or "TravelMind 攻略知识库",
        "origin_type": origin_type,
        "content": content,
        "search_text": full_text,
        "content_hash": content_hash,
        "tokens": tokenize_zh_en(f"{title} {section} {city} {' '.join(tags)} {content}"),
    }


def _chunk_markdown(
    doc_id: str,
    title: str,
    city: str,
    category: str,
    tags: list[str],
    source: str,
    origin_type: str,
    body: str,
) -> list[dict[str, Any]]:
    sections: list[tuple[str, list[str]]] = []
    current_section = "概览"
    buffer: list[str] = []

    for line in body.splitlines():
        heading_match = re.match(r"^#{1,3}\s+(.+)$", line.strip())
        if heading_match:
            if buffer:
                sections.append((current_section, buffer))
                buffer = []
            current_section = heading_match.group(1).strip()
        else:
            buffer.append(line)

    if buffer:
        sections.append((current_section, buffer))

    if not sections and body.strip():
        sections = [("正文", body.splitlines())]

    chunks: list[dict[str, Any]] = []
    for sec_idx, (section_title, lines) in enumerate(sections, start=1):
        sec_text = "\n".join(lines).strip()
        if not sec_text:
            continue
        for sub_idx, part in enumerate(_split_long_text(sec_text), start=1):
            chunks.append(
                _make_chunk(
                    chunk_id=f"{doc_id}#s{sec_idx}p{sub_idx}",
                    doc_id=doc_id,
                    title=title,
                    section=section_title,
                    city=city,
                    category=category,
                    tags=tags,
                    source=source,
                    origin_type=origin_type,
                    content=part,
                )
            )
    return chunks


def _chunk_city_corpus_json(doc_id: str, data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """把 sync/knowledge/cities/*.json 结构化策展语料转为语义分块。"""
    city = _clean_city(str(data.get("city") or doc_id)) or "通用"
    title = f"{city}官方策展城市攻略"
    source = "TravelMind 策展城市知识库"
    tags: list[str] = ["城市攻略", "片区动线", "预约避坑"]
    chunks: list[dict[str, Any]] = []

    # 1. 城市概览 + 片区分布 + 实用贴士 + 季节建议
    overview_lines: list[str] = []
    if data.get("summary"):
        overview_lines.append(str(data["summary"]).strip())
    for dist in data.get("districts") or []:
        if not isinstance(dist, dict):
            continue
        name = str(dist.get("name") or "").strip()
        char = str(dist.get("character") or "").strip()
        best_for = "、".join(str(x) for x in dist.get("best_for") or [] if str(x).strip())
        if name:
            overview_lines.append(f"- {name}：{char}" + (f"（适合：{best_for}）" if best_for else ""))
    if overview_lines:
        chunks.append(
            _make_chunk(
                chunk_id=f"{doc_id}#overview",
                doc_id=doc_id,
                title=title,
                section="城市概览与片区划分",
                city=city,
                category="策展攻略",
                tags=["片区", "动线", "经典景点"],
                source=source,
                origin_type="builtin",
                content="\n".join(overview_lines),
            )
        )

    tips_lines: list[str] = []
    for tip in data.get("practical_tips") or []:
        if str(tip).strip():
            tips_lines.append(f"- {str(tip).strip()}")
    for season in data.get("seasonal") or []:
        if isinstance(season, dict) and season.get("advice"):
            months = str(season.get("months") or "").strip()
            tips_lines.append(f"- {months}月季节提示：{str(season['advice']).strip()}")
    if tips_lines:
        chunks.append(
            _make_chunk(
                chunk_id=f"{doc_id}#tips",
                doc_id=doc_id,
                title=title,
                section="交通避坑与季节提示",
                city=city,
                category="策展攻略",
                tags=["避坑", "交通", "雨天替代", "季节"],
                source=source,
                origin_type="builtin",
                content="\n".join(tips_lines),
            )
        )

    # 2. 美食笔记
    food_lines: list[str] = []
    for food in data.get("food_notes") or []:
        if isinstance(food, dict) and food.get("name"):
            food_lines.append(f"- {food['name']}：{str(food.get('note') or '').strip()}")
    if food_lines:
        chunks.append(
            _make_chunk(
                chunk_id=f"{doc_id}#food",
                doc_id=doc_id,
                title=title,
                section="本地美食与就餐贴士",
                city=city,
                category="策展攻略",
                tags=["美食", "地方特色", "排队"],
                source=source,
                origin_type="builtin",
                content="\n".join(food_lines),
            )
        )

    # 3. 热门景点分块（按室内/雨天替代与片区整理，避免单块过碎也保持高召回）
    indoor_lines: list[str] = []
    outdoor_lines: list[str] = []
    for idx, entry in enumerate(data.get("attractions") or [], start=1):
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        name = str(entry["name"]).strip()
        district = str(entry.get("district") or "").strip()
        parts = []
        if district:
            parts.append(district)
        if entry.get("suggested_duration"):
            parts.append(f"建议 {entry['suggested_duration']}")
        if entry.get("best_time"):
            parts.append(f"最佳时段：{entry['best_time']}")
        if entry.get("booking"):
            parts.append(f"预约：{entry['booking']}")
        highlights = [str(h).strip() for h in entry.get("highlights") or [] if str(h).strip()]
        if highlights:
            parts.append("；".join(highlights[:2]))
        if entry.get("note"):
            parts.append(str(entry["note"]).strip())
        line = f"- {name}：{'；'.join(parts)}"
        if entry.get("indoor") or entry.get("rainy_alternative"):
            indoor_lines.append(line)
        else:
            outdoor_lines.append(line)
        for kw in entry.get("keywords") or []:
            kw_text = str(kw).strip()
            if kw_text and kw_text not in tags and len(tags) < 12:
                tags.append(kw_text)

    if indoor_lines:
        for sub_idx, part in enumerate(_split_long_text("\n".join(indoor_lines)), start=1):
            chunks.append(
                _make_chunk(
                    chunk_id=f"{doc_id}#indoor_{sub_idx}",
                    doc_id=doc_id,
                    title=title,
                    section="室内场馆与雨天替代推荐",
                    city=city,
                    category="策展攻略",
                    tags=["室内", "雨天替代", "博物馆", "展览", "避暑"],
                    source=source,
                    origin_type="builtin",
                    content=part,
                )
            )
    if outdoor_lines:
        for sub_idx, part in enumerate(_split_long_text("\n".join(outdoor_lines)), start=1):
            chunks.append(
                _make_chunk(
                    chunk_id=f"{doc_id}#scenic_{sub_idx}",
                    doc_id=doc_id,
                    title=title,
                    section="核心景点玩法与预约避坑",
                    city=city,
                    category="策展攻略",
                    tags=["经典景点", "海边", "拍照", "预约", "公园"],
                    source=source,
                    origin_type="builtin",
                    content=part,
                )
            )

    preview = str(data.get("summary") or (overview_lines[0] if overview_lines else "")).strip()[:140]
    doc_meta = {
        "doc_id": doc_id,
        "title": title,
        "city": city,
        "category": "策展城市库",
        "tags": tags[:8],
        "source": source,
        "origin_type": "builtin",
        "chunk_count": len(chunks),
        "char_count": sum(len(c["content"]) for c in chunks),
        "preview": preview,
    }
    return doc_meta, chunks


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (norm_a * norm_b)


class OpenAICompatibleEmbedder:
    """可选的 OpenAI 兼容 /embeddings 客户端，支持硅基流动/通义/智谱/OpenAI 等。"""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        timeout: float = 12.0,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("RAG_EMBEDDING_API_KEY")
            or os.getenv("EMBEDDING_API_KEY")
            or ""
        ).strip()
        self.base_url = (
            base_url
            or os.getenv("RAG_EMBEDDING_BASE_URL")
            or os.getenv("EMBEDDING_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.model = (
            model
            or os.getenv("RAG_EMBEDDING_MODEL")
            or os.getenv("EMBEDDING_MODEL")
            or "text-embedding-3-small"
        ).strip()
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.model)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.enabled or not texts:
            return []
        response = requests.post(
            f"{self.base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": texts,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        data = sorted(payload.get("data", []), key=lambda item: item.get("index", 0))
        return [list(map(float, item.get("embedding", []))) for item in data]


@dataclass
class TravelRAGService:
    """混合检索 RAG 引擎（BM25 + 元数据加权 + 可选语义向量 RRF 融合）。"""

    base_dir: Path = field(default_factory=lambda: DEFAULT_KB_DIR)
    city_corpus_dir: Path | None = field(default_factory=lambda: DEFAULT_CITY_CORPUS_DIR)
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None
    embedder: OpenAICompatibleEmbedder | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _documents: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _chunks: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)
    _doc_freq: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _avg_doc_len: float = field(default=1.0, init=False, repr=False)
    _embeddings_cache: dict[str, list[float]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)
        self.builtin_dir = self.base_dir / "builtin"
        self.custom_dir = self.base_dir / "custom"
        self.cache_dir = self.base_dir / ".cache"
        self.cache_file = self.cache_dir / "embeddings.json"
        if self.city_corpus_dir is not None:
            self.city_corpus_dir = Path(self.city_corpus_dir)
        if self.embedder is None:
            self.embedder = OpenAICompatibleEmbedder()
        self.builtin_dir.mkdir(parents=True, exist_ok=True)
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        self._load_embeddings_cache()
        self.reload()

    @property
    def vector_enabled(self) -> bool:
        return self.embed_fn is not None or bool(self.embedder and self.embedder.enabled)

    @property
    def retrieval_mode(self) -> str:
        return "hybrid_bm25_vector" if self.vector_enabled else "bm25_metadata"

    def _compute_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.embed_fn is not None:
            return self.embed_fn(texts)
        if self.embedder and self.embedder.enabled:
            return self.embedder.embed_texts(texts)
        return []

    def _load_embeddings_cache(self) -> None:
        if not self.cache_file.exists():
            self._embeddings_cache = {}
            return
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._embeddings_cache = {
                    str(k): v for k, v in data.items() if isinstance(v, list)
                }
        except Exception:
            self._embeddings_cache = {}

    def _save_embeddings_cache(self) -> None:
        if not self._embeddings_cache:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(
                json.dumps(self._embeddings_cache, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def reload(self) -> None:
        """重新扫描策展 JSON、内置 Markdown 和用户自定义攻略目录并重建索引。"""
        with self._lock:
            documents: list[dict[str, Any]] = []
            chunks: list[dict[str, Any]] = []

            # 1. 加载 sync/knowledge/cities/*.json 策展城市库
            if self.city_corpus_dir and self.city_corpus_dir.exists():
                for path in sorted(self.city_corpus_dir.glob("*.json")):
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if not isinstance(data, dict):
                        continue
                    doc_id = f"city_{path.stem}"
                    doc_meta, doc_chunks = _chunk_city_corpus_json(doc_id, data)
                    stat = path.stat()
                    doc_meta["updated_at"] = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                    documents.append(doc_meta)
                    chunks.extend(doc_chunks)

            # 2. 加载 knowledge_base/builtin/*.md 和 knowledge_base/custom/*.md
            for origin_type, folder in [("builtin", self.builtin_dir), ("custom", self.custom_dir)]:
                if not folder.exists():
                    continue
                for path in sorted(folder.glob("*.md")):
                    try:
                        raw = path.read_text(encoding="utf-8")
                    except Exception:
                        continue
                    meta, body = _parse_frontmatter(raw)
                    doc_id = path.stem
                    title = str(meta.get("title") or doc_id).strip()
                    city = _clean_city(str(meta.get("city") or "通用")) or "通用"
                    category = str(meta.get("category") or ("内置攻略" if origin_type == "builtin" else "自定义攻略")).strip()
                    tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
                    source = str(meta.get("source") or ("TravelMind 内置攻略库" if origin_type == "builtin" else "用户自定义攻略")).strip()
                    doc_chunks = _chunk_markdown(
                        doc_id=doc_id,
                        title=title,
                        city=city,
                        category=category,
                        tags=tags,
                        source=source,
                        origin_type=origin_type,
                        body=body,
                    )
                    chunks.extend(doc_chunks)
                    stat = path.stat()
                    documents.append(
                        {
                            "doc_id": doc_id,
                            "title": title,
                            "city": city,
                            "category": category,
                            "tags": tags,
                            "source": source,
                            "origin_type": origin_type,
                            "chunk_count": len(doc_chunks),
                            "char_count": len(body),
                            "updated_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                            "preview": body[:140].replace("\n", " ").strip(),
                        }
                    )

            doc_freq: dict[str, int] = {}
            total_len = 0
            for chunk in chunks:
                tokens = chunk["tokens"]
                total_len += len(tokens)
                for token in set(tokens):
                    doc_freq[token] = doc_freq.get(token, 0) + 1

            self._documents = documents
            self._chunks = chunks
            self._doc_freq = doc_freq
            self._avg_doc_len = (total_len / len(chunks)) if chunks else 1.0

            if self.vector_enabled and chunks:
                self._ensure_chunk_embeddings()

    def _ensure_chunk_embeddings(self) -> None:
        missing_chunks = [
            chunk for chunk in self._chunks if chunk["content_hash"] not in self._embeddings_cache
        ]
        if not missing_chunks:
            return
        batch_size = 16
        updated = False
        for start in range(0, len(missing_chunks), batch_size):
            batch = missing_chunks[start : start + batch_size]
            try:
                vectors = self._compute_embeddings([item["search_text"] for item in batch])
            except Exception:
                break
            if len(vectors) != len(batch):
                break
            for item, vector in zip(batch, vectors):
                self._embeddings_cache[item["content_hash"]] = vector
                updated = True
        if updated:
            self._save_embeddings_cache()

    def list_documents(self) -> dict[str, Any]:
        with self._lock:
            return {
                "retrieval_mode": self.retrieval_mode,
                "vector_enabled": self.vector_enabled,
                "embedding_model": (self.embedder.model if self.embedder and self.embedder.enabled else ""),
                "total_docs": len(self._documents),
                "total_chunks": len(self._chunks),
                "documents": [dict(doc) for doc in self._documents],
            }

    def add_custom_document(
        self,
        *,
        title: str,
        content: str,
        city: str = "通用",
        category: str = "自定义攻略",
        tags: list[str] | str | None = None,
        source: str = "用户上传攻略",
    ) -> dict[str, Any]:
        clean_title = str(title or "").strip()
        clean_content = str(content or "").strip()
        if not clean_title:
            raise ValueError("攻略标题不能为空")
        if len(clean_content) < 10:
            raise ValueError("攻略正文内容太短（至少 10 个字）")

        clean_city = _clean_city(city) or "通用"
        clean_category = str(category or "自定义攻略").strip() or "自定义攻略"
        if isinstance(tags, str):
            tag_list = [item.strip() for item in re.split(r"[,，、\s]+", tags) if item.strip()]
        elif isinstance(tags, list):
            tag_list = [str(item).strip() for item in tags if str(item).strip()]
        else:
            tag_list = []

        slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", clean_title).strip("_")[:28] or "note"
        digest = hashlib.sha256(f"{clean_title}:{clean_content}:{datetime.now().isoformat()}".encode("utf-8")).hexdigest()[:8]
        doc_id = f"custom_{slug}_{digest}"

        frontmatter_lines = [
            "---",
            f"title: {clean_title}",
            f"city: {clean_city}",
            f"category: {clean_category}",
            f"tags: {','.join(tag_list)}",
            f"source: {source}",
            "---",
            "",
            clean_content,
            "",
        ]
        target = self.custom_dir / f"{doc_id}.md"
        target.write_text("\n".join(frontmatter_lines), encoding="utf-8")
        self.reload()

        with self._lock:
            for doc in self._documents:
                if doc["doc_id"] == doc_id:
                    return dict(doc)
        return {"doc_id": doc_id, "title": clean_title, "city": clean_city, "origin_type": "custom"}

    def delete_custom_document(self, doc_id: str) -> bool:
        safe_id = str(doc_id or "").strip()
        if not safe_id or not safe_id.startswith("custom_") or "/" in safe_id or "\\" in safe_id or ".." in safe_id:
            raise ValueError("只允许删除用户自定义的攻略文档")
        target = self.custom_dir / f"{safe_id}.md"
        if not target.exists():
            return False
        target.unlink()
        self.reload()
        return True

    def _bm25_score(self, query_tokens: list[str], chunk: dict[str, Any], k1: float = 1.5, b: float = 0.75) -> float:
        doc_tokens = chunk["tokens"]
        if not doc_tokens or not query_tokens:
            return 0.0
        tf_map: dict[str, int] = {}
        for tok in doc_tokens:
            tf_map[tok] = tf_map.get(tok, 0) + 1
        doc_len = len(doc_tokens)
        total_docs = max(len(self._chunks), 1)
        score = 0.0
        for token in set(query_tokens):
            tf = tf_map.get(token, 0)
            if tf <= 0:
                continue
            df = self._doc_freq.get(token, 0)
            idf = math.log(1.0 + (total_docs - df + 0.5) / (df + 0.5))
            denom = tf + k1 * (1.0 - b + b * (doc_len / max(self._avg_doc_len, 1.0)))
            score += idf * (tf * (k1 + 1.0)) / max(denom, 1e-6)
        return score

    def _chunk_matches_city(self, chunk: dict[str, Any], target_city: str) -> str:
        if not target_city:
            return "general"
        chunk_city = _clean_city(chunk.get("city", ""))
        if chunk_city == target_city:
            return "exact"
        if target_city in chunk.get("title", "") or target_city in chunk.get("section", "") or target_city in chunk.get("content", ""):
            return "mention"
        if chunk_city in {"", "通用"}:
            return "general"
        return "other"

    def retrieve(
        self,
        query: str,
        *,
        city: str = "",
        interests: list[str] | None = None,
        weather: str = "",
        pace: str = "",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """执行混合检索（元数据过滤 + BM25 + 可选语义向量 RRF 融合）。"""
        with self._lock:
            if not self._chunks:
                return []

            target_city = _clean_city(city)
            interest_list = [str(item).strip() for item in (interests or []) if str(item).strip()]
            weather_text = str(weather or "")
            has_rain = bool(re.search(r"雨|雷阵雨", weather_text)) and "无雨" not in weather_text
            has_heat = bool(re.search(r"3[2-9]|4\d|高温|暴晒", weather_text))

            query_parts = [str(query or "").strip(), target_city, *interest_list]
            if pace:
                query_parts.append(str(pace))
            if has_rain:
                query_parts.append("雨天 室内 替代方案")
            if has_heat:
                query_parts.append("高温 防晒 室内")
            full_query = " ".join(part for part in query_parts if part).strip()
            query_tokens = tokenize_zh_en(full_query)

            candidates: list[tuple[dict[str, Any], str]] = []
            for chunk in self._chunks:
                match_level = self._chunk_matches_city(chunk, target_city)
                if target_city and match_level == "other":
                    continue
                candidates.append((chunk, match_level))

            if not candidates:
                candidates = [(chunk, "general") for chunk in self._chunks]

            bm25_scores: dict[str, float] = {}
            for chunk, _ in candidates:
                bm25_scores[chunk["chunk_id"]] = self._bm25_score(query_tokens, chunk)

            bm25_ranked = sorted(
                candidates,
                key=lambda pair: (-bm25_scores[pair[0]["chunk_id"]], pair[0]["chunk_id"]),
            )
            bm25_rank_map = {
                chunk["chunk_id"]: rank for rank, (chunk, _) in enumerate(bm25_ranked, start=1)
            }

            vector_scores: dict[str, float] = {}
            vector_rank_map: dict[str, int] = {}
            used_vector = False
            if self.vector_enabled and full_query:
                try:
                    self._ensure_chunk_embeddings()
                    query_vecs = self._compute_embeddings([full_query])
                    if query_vecs and query_vecs[0]:
                        q_vec = query_vecs[0]
                        for chunk, _ in candidates:
                            c_vec = self._embeddings_cache.get(chunk["content_hash"])
                            vector_scores[chunk["chunk_id"]] = _cosine_similarity(q_vec, c_vec) if c_vec else 0.0
                        vector_ranked = sorted(
                            candidates,
                            key=lambda pair: (-vector_scores.get(pair[0]["chunk_id"], 0.0), pair[0]["chunk_id"]),
                        )
                        vector_rank_map = {
                            chunk["chunk_id"]: rank for rank, (chunk, _) in enumerate(vector_ranked, start=1)
                        }
                        used_vector = True
                except Exception:
                    used_vector = False

            rrf_k = 60.0
            scored_items: list[tuple[float, str, dict[str, Any], list[str]]] = []
            for chunk, match_level in candidates:
                cid = chunk["chunk_id"]
                bm25_val = bm25_scores.get(cid, 0.0)
                vec_val = vector_scores.get(cid, 0.0)
                reasons: list[str] = []

                if used_vector:
                    base_score = (1.0 / (rrf_k + bm25_rank_map[cid])) + (1.0 / (rrf_k + vector_rank_map[cid]))
                    score = base_score * 100.0
                    if vec_val > 0.35:
                        reasons.append(f"语义相似 {vec_val:.2f}")
                else:
                    score = bm25_val

                if match_level == "exact":
                    score += 3.5 if not used_vector else 0.9
                    reasons.append(f"命中城市：{target_city}")
                elif match_level == "mention":
                    score += 2.2 if not used_vector else 0.55
                    reasons.append(f"提及城市：{target_city}")
                elif match_level == "general":
                    score += 0.3 if not used_vector else 0.1

                if chunk.get("origin_type") == "custom":
                    score += 1.2 if not used_vector else 0.35
                    reasons.append("用户自定义攻略")

                chunk_tags = set(chunk.get("tags") or [])
                chunk_blob = f"{chunk['section']} {chunk['content']}"
                matched_interests = [
                    item for item in interest_list if item in chunk_tags or item in chunk_blob
                ]
                if matched_interests:
                    score += (0.8 * len(matched_interests)) if not used_vector else (0.2 * len(matched_interests))
                    reasons.append(f"匹配偏好：{'、'.join(matched_interests[:2])}")

                if has_rain and ("雨天" in chunk_blob or "室内" in chunk_blob):
                    score += 1.5 if not used_vector else 0.4
                    reasons.append("雨天室内适配")
                if has_heat and ("高温" in chunk_blob or "防晒" in chunk_blob or "室内" in chunk_blob):
                    score += 1.0 if not used_vector else 0.25
                    reasons.append("高温防晒适配")

                if bm25_val > 0 or vec_val > 0.2 or match_level in {"exact", "mention"}:
                    scored_items.append((score, cid, chunk, reasons))

            scored_items.sort(key=lambda item: (-item[0], item[1]))

            results: list[dict[str, Any]] = []
            doc_counts: dict[str, int] = {}
            actual_mode = "hybrid_bm25_vector" if used_vector else "bm25_metadata"

            for score, _, chunk, reasons in scored_items:
                if len(results) >= max(1, int(top_k)):
                    break
                doc_id = chunk["doc_id"]
                if doc_counts.get(doc_id, 0) >= 2 and len(scored_items) > top_k:
                    continue
                doc_counts[doc_id] = doc_counts.get(doc_id, 0) + 1
                results.append(
                    {
                        "chunk_id": chunk["chunk_id"],
                        "doc_id": doc_id,
                        "title": chunk["title"],
                        "section": chunk["section"],
                        "city": chunk["city"],
                        "category": chunk["category"],
                        "tags": chunk["tags"],
                        "source": chunk["source"],
                        "origin_type": chunk["origin_type"],
                        "content": chunk["content"],
                        "score": round(score, 3),
                        "retrieval_mode": actual_mode,
                        "match_reasons": reasons or ["关键词匹配"],
                        "source_meta": {
                            "provider": "knowledge_base",
                            "status": "live",
                            "kind": "knowledge_base",
                            "confidence": "high" if score >= 3.0 else "medium",
                            "note": "来自 TravelMind 攻略知识库（RAG 混合检索），实操预约与营业时间请以现场为准。",
                        },
                    }
                )
            return results

    def retrieve_for_plan(
        self,
        prefs: dict[str, Any],
        weather: dict[str, str] | None = None,
        *,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """为结构化行程规划生成可注入 LLM 的攻略片段和前端展示引用。"""
        city = str(prefs.get("destinationCity") or "").strip()
        interests = prefs.get("interests") or []
        profile = prefs.get("preferenceProfile") or {}
        pace = str(profile.get("pace") or "")
        learned = " ".join(profile.get("learnedHints") or [])
        free_text = str(prefs.get("freeText") or "")
        weather_summary = " ".join((weather or {}).values())

        query = f"{city} 旅游攻略 片区动线 避坑 预约 美食 {' '.join(interests)} {pace} {learned} {free_text}"
        hits = self.retrieve(
            query,
            city=city,
            interests=interests,
            weather=weather_summary,
            pace=pace,
            top_k=top_k,
        )

        prompt_snippets = [
            {
                "title": item["title"],
                "section": item["section"],
                "city": item["city"],
                "origin_type": item["origin_type"],
                "content": item["content"][:420],
            }
            for item in hits
        ]

        return {
            "references": hits,
            "prompt_snippets": prompt_snippets,
            "meta": {
                "retrieval_mode": hits[0]["retrieval_mode"] if hits else self.retrieval_mode,
                "hit_count": len(hits),
                "total_docs": len(self._documents),
                "total_chunks": len(self._chunks),
                "query_city": city,
            },
        }


_DEFAULT_RAG_SERVICE: TravelRAGService | None = None
_SERVICE_LOCK = threading.Lock()


def get_rag_service() -> TravelRAGService:
    global _DEFAULT_RAG_SERVICE
    with _SERVICE_LOCK:
        if _DEFAULT_RAG_SERVICE is None:
            _DEFAULT_RAG_SERVICE = TravelRAGService()
        return _DEFAULT_RAG_SERVICE
