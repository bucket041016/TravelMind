"""TravelMind 目的地知识库：人工策展语料 + 关键词检索。

只被 MCP Server（sync/fastmcp_server_streamhttp.py 的 kb_retrieve 工具）直接依赖；
规划器一律经 MCP 工具消费检索结果，不 import 本包。
"""

from __future__ import annotations

from .retriever import (
    CORPUS_DIR,
    KeywordRetriever,
    KnowledgeRetriever,
    normalize_city_name,
)

__all__ = [
    "CORPUS_DIR",
    "KeywordRetriever",
    "KnowledgeRetriever",
    "get_retriever",
    "normalize_city_name",
    "retrieve",
]

_retriever: KnowledgeRetriever = KeywordRetriever()


def get_retriever() -> KnowledgeRetriever:
    """进程内共享的检索器实例（语料索引懒加载一次）。"""
    return _retriever


def retrieve(city: str, query: str = "", limit: int = 8) -> dict:
    """检索城市攻略与景点详情，返回 kb_retrieve 工具的结构化载荷。"""
    return get_retriever().retrieve(city, query=query, limit=limit)
