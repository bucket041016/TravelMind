"""DeepSeek 大模型规划脑 -- 负责行程规划、酒店价格估算、路线评审、质量体检。

从 structured_planner.py 中提取，作为独立的 AI 调用封装层。
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_deepseek import ChatDeepSeek
from pydantic import BaseModel

from .deepseek_contracts import HotelPriceOutput, PlanOutput, RefineOutput, ReviewOutput, RouteJudgement


class DeepSeekInvocationError(ValueError):
    """DeepSeek 输出在重试预算内仍无法使用：携带错误分类与尝试次数（D11）。

    error_kind: "schema"（输出无法解析/校验）| "call"（调用/网络/鉴权/超时）。
    """

    def __init__(self, *, error_kind: str, attempt_count: int, message: str):
        super().__init__(message)
        self.error_kind = error_kind
        self.attempt_count = attempt_count


class DeepSeekPlanningBrainAgent:
    """Use DeepSeek as the planning brain while keeping AMap as the fact source."""

    def __init__(self) -> None:
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self.model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        try:
            self.timeout = float(os.getenv("DEEPSEEK_PLAN_TIMEOUT_SECONDS", "35"))
        except (TypeError, ValueError):
            # 环境变量被配置成非法值时回退默认值，避免整个 planner 构造失败。
            self.timeout = 35.0
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            self.timeout = 35.0
        self.model = None
        if self.api_key:
            self._sanitize_no_proxy()
            self.model = ChatDeepSeek(
                model=self.model_name,
                temperature=0.35,
                timeout=self.timeout,
                max_retries=1,
                max_tokens=3500,
            )

    @staticmethod
    def _sanitize_no_proxy() -> None:
        """清理 NO_PROXY 环境变量中 httpx 0.28+ 无法解析的条目。

        httpx 0.28+ 在构造 Client 时会用 URLPattern 解析 NO_PROXY 中的每个
        条目，要求格式为完整 URL（如 http://127.0.0.1）。而系统常见的旧式格式
        （127.0.0.1、localhost、::1、127.0.0.0/8 等）会导致 InvalidURL 错误，
        表现为 "Invalid port: ':1'" 或 "Relative URLs cannot have a path
        starting with ':'"。

        本方法在构造 ChatDeepSeek -> openai.OpenAI -> httpx.Client 之前调用，
        将无法解析的条目从 NO_PROXY 中移除，避免初始化失败。只修改当前进程的
        环境变量，不影响系统设置。
        """
        for var_name in ("NO_PROXY", "no_proxy"):
            raw = os.environ.get(var_name)
            if not raw:
                continue
            try:
                from httpx._utils import URLPattern
            except ImportError:
                return
            entries = [e.strip() for e in raw.split(",") if e.strip()]
            safe = []
            for entry in entries:
                try:
                    URLPattern(entry)
                    safe.append(entry)
                except Exception:
                    pass
            os.environ[var_name] = ",".join(safe)

    def _unavailable(self, key: str, default: Any = None) -> dict[str, Any]:
        return {
            "llm_status": "unavailable",
            "reason": "DEEPSEEK_API_KEY missing",
            "error_kind": "unavailable",
            "attempt_count": 0,
            "fallback_reason": "deepseek_unavailable",
            key: default,
        }

    @staticmethod
    def _degraded(exc: DeepSeekInvocationError, key: str, default: Any = None) -> dict[str, Any]:
        llm_status = "schema_failed" if exc.error_kind == "schema" else "call_failed"
        return {
            "llm_status": llm_status,
            "reason": str(exc),
            "error_kind": exc.error_kind,
            "attempt_count": exc.attempt_count,
            "fallback_reason": f"deepseek_{llm_status}",
            key: default,
        }

    def plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.model:
            return self._unavailable("plan")

        system_prompt = (
            "你是 TravelMind 的智能行程规划脑。你必须基于给定的高德候选 POI、酒店、交通、天气和用户偏好规划行程。"
            "真实地点必须引用候选中的 candidate_id；不要编造真实景点、餐厅、酒店、航班号、票价或库存。"
            "如果需要加入更人性化的体验建议但没有真实 POI，可设置 is_suggestion=true，并写清楚 validation_note。"
            "只输出 JSON，不要 Markdown，不要解释。"
        )
        user_prompt = (
            "请生成结构化行程 JSON，schema 如下：\n"
            "{\n"
            '  "days": [\n'
            '    {"day": 1, "theme": "", "items": [\n'
            '      {"title": "", "candidate_id": "", "category": "activity|food|hotel|transfer|note", '
            '"transport": "", "duration": "", "detail": "", "is_suggestion": false, "validation_note": "", '
            '"estimated_price_range": "", "price_confidence": "high|medium|low|unknown", "price_note": ""}\n'
            "    ]}\n"
            "  ]\n"
            "}\n"
            "要求：每天 3-5 个 item；优先选择真实 candidate_id；不要重复安排同一真实景点或餐厅；"
            "体现用户偏好、节奏取舍、天气和交通约束；泛化建议不得进入地图。"
            "最后一天如安排返程交通，必须写成 category=transfer，只说明从目的地车站/机场返回出发城市，不能再给目的地住宿建议。"
            "如果高德候选没有 cost，只有在常识上明确可能有门票/体验消费时才给正价 estimated_price_range，例如 30-80；"
            "开放空间、免费公共活动或无法判断是否收费时可给 0-0，price_note 必须说明需以官方/现场为准。"
            "不要编造实时票价、门票库存或可预订价格。\n\n"
            f"输入数据：\n{json.dumps(payload, ensure_ascii=False)}"
        )

        try:
            parsed, attempt_count = self._invoke_parsed(system_prompt, user_prompt, PlanOutput)
        except DeepSeekInvocationError as exc:
            return self._degraded(exc, "plan")
        return {"llm_status": "used", "reason": "", "attempt_count": attempt_count, "plan": parsed}

    def estimate_hotel_prices(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.model:
            return self._unavailable("prices", [])

        system_prompt = (
            "你是 TravelMind 的酒店价格常识估算助手。你只能给非实时常识区间，"
            "不能声称这是可预订房价、库存或平台实时价。只输出 JSON。"
        )
        user_prompt = (
            "请为没有高德 cost 的酒店候选估算每晚价格区间，schema 如下：\n"
            '{"prices":[{"candidate_id":"","estimated_price_range":"300-500",'
            '"price_confidence":"low|medium|unknown","price_note":""}]}\n'
            "要求：价格单位为人民币/晚；必须写明需以酒店平台实时房价和房态为准；"
            "如果无法判断，price_confidence 用 unknown。\n\n"
            f"输入数据：\n{json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            parsed, attempt_count = self._invoke_parsed(system_prompt, user_prompt, HotelPriceOutput)
        except DeepSeekInvocationError as exc:
            return self._degraded(exc, "prices", [])

        prices = parsed.get("prices") if isinstance(parsed.get("prices"), list) else []
        return {"llm_status": "used", "reason": "", "attempt_count": attempt_count, "prices": prices}

    def judge_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.model:
            return self._unavailable("judgement")

        system_prompt = (
            "你是 TravelMind 的路线体验评审。高德和后端规则负责路线事实，你只判断这段移动放在当天行程里是否合理。"
            "不要编造路线、票价、实时打车价格或不存在的地点；替换地点只能返回输入候选中的 candidate_id。"
            "只输出 JSON，不要 Markdown，不要解释。"
        )
        user_prompt = (
            "请评审这段目的地内移动，schema 如下：\n"
            '{"decision":"accept|switch_mode|replace_place|mark_impractical",'
            '"suggested_mode":"taxi|driving|transit|walking|bicycling",'
            '"replacement_candidate_id":"","risk_level":"low|medium|high",'
            '"judge_reason":"","display_summary":""}\n'
            "判断原则：如果公共交通耗时明显破坏旅行体验，可建议 switch_mode；如果同类近距离候选更合适，优先 replace_place；"
            "如果无合适交通或替换，mark_impractical。accept 只能用于轻松、可信、值得的移动。\n\n"
            f"输入数据：\n{json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            parsed, attempt_count = self._invoke_parsed(system_prompt, user_prompt, RouteJudgement)
        except DeepSeekInvocationError as exc:
            return self._degraded(exc, "judgement")

        return {"llm_status": "used", "reason": "", "attempt_count": attempt_count, "judgement": parsed}

    def review_itinerary(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.model:
            return self._unavailable("review")

        system_prompt = (
            "你是 TravelMind 的行程质量体检员。你只基于输入中的真实候选、路线事实、用户偏好检查行程质量。"
            "如果建议返工，repaired_plan 中的真实地点必须使用输入候选 candidate_id；不要编造地点、价格、车次、航班或库存。"
            "只输出 JSON，不要 Markdown，不要解释。"
        )
        user_prompt = (
            "请体检这份行程，schema 如下：\n"
            '{"overall_score":80,"route_score":80,"pace_score":80,"cluster_score":80,"logic_score":80,'
            '"issues":[{"severity":"low|medium|high","day":1,"message":"","kind":"route|pace|cluster|logic|budget"}],'
            '"fixes":[""],"needs_repair":false,"repaired_plan":{"days":[]}}\n'
            "评分 0-100。只有发现高风险跨区乱跳、超长交通、返程/住宿串台、节奏明显不符时 needs_repair=true。"
            "repaired_plan 与规划 schema 一致，最多返工一次，优先调整顺序或替换为同片区真实候选。\n\n"
            f"输入数据：\n{json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            parsed, attempt_count = self._invoke_parsed(system_prompt, user_prompt, ReviewOutput)
        except DeepSeekInvocationError as exc:
            return self._degraded(exc, "review")

        return {"llm_status": "used", "reason": "", "attempt_count": attempt_count, "review": parsed}

    def parse_refine_ops(self, payload: dict[str, Any]) -> dict[str, Any]:
        """把用户追问解析为计划增量操作（Phase 4）；降级语义与四个脑方法一致。"""
        if not self.model:
            return self._unavailable("operations", [])

        system_prompt = (
            "你是 TravelMind 的追问解析器。你只基于输入中的计划摘要和候选池，把用户追问解析为结构化增量操作。"
            "真实地点只能引用输入候选池中的 candidate_id，不能编造地点、价格、车次或库存；"
            "item 引用必须使用输入 items 提供的 item_id，退化时使用 item_title。"
            "语义无法确定或用户只是咨询时，用 action=answer_only 并在 answer 中说明或提问，不要猜测执行。"
            "只输出 JSON，不要 Markdown，不要解释。"
        )
        user_prompt = (
            "请把用户追问解析为增量操作，schema 如下：\n"
            '{"operations": [{"action": "replace_place|remove_item|add_activity|adjust_budget|change_pace|change_hotel_strategy|answer_only", '
            '"day": 1, "item_id": "", "item_title": "", "candidate_id": "", "new_title": "", '
            '"budget": 0, "pace": "", "hotel_strategy": "", "slot": "", "reason": "", "needs_confirmation": false}], "answer": ""}\n'
            "判定规则：\n"
            "1. 把某天整体换成某种场景（如室内/户外）→ 对该天每个需要更换的 activity 逐个发 replace_place，餐饮一般不动；\n"
            "2. 预算改为 X → adjust_budget（budget=X）；\n"
            "3. 节奏快慢 → change_pace（轻松|标准|紧凑）；\n"
            "4. 住宿位置偏好 → change_hotel_strategy（近景点|近地铁枢纽|近商圈）；\n"
            "5. 增加/删除具体地点 → add_activity/remove_item（引用 item_id，删除也可用 item_title）；\n"
            "6. 纯咨询、闲聊、无法定位到具体日期或地点 → answer_only，把回答写进 answer。\n"
            "要求：每次最多 12 条操作；候选不得与行程中已安排地点重复；不要输出修改后的完整行程。\n\n"
            f"输入数据：\n{json.dumps(payload, ensure_ascii=False)}"
        )
        try:
            parsed, attempt_count = self._invoke_parsed(system_prompt, user_prompt, RefineOutput)
        except DeepSeekInvocationError as exc:
            return self._degraded(exc, "operations", [])

        operations = parsed.get("operations") if isinstance(parsed.get("operations"), list) else []
        return {
            "llm_status": "used",
            "reason": "",
            "attempt_count": attempt_count,
            "operations": operations,
            "answer": str(parsed.get("answer") or ""),
        }

    @staticmethod
    def _message_content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item))
            return "\n".join(part for part in parts if part)
        return str(content)

    def _invoke_parsed(
        self,
        system_prompt: str,
        user_prompt: str,
        model_cls: type[BaseModel],
        max_attempts: int = 2,
    ) -> tuple[dict[str, Any], int]:
        """调用 DeepSeek 并把输出解析为 model_cls，校验失败时回喂错误重试。

        返回 (parsed, attempt_count)。重试预算耗尽抛 DeepSeekInvocationError，
        error_kind 区分 schema（输出无法解析/校验）与 call（调用/网络/鉴权/超时）。
        """
        last_error = ""
        last_kind = "call"
        attempt_count = 0
        for attempt in range(max_attempts):
            attempt_count += 1
            prompt = user_prompt
            if attempt:
                prompt += (
                    "\n\n上一次输出无法解析或校验失败，错误："
                    f"{last_error}\n请严格按 schema 只返回 JSON 对象，不要 Markdown、不要解释。"
                )
            try:
                response = self.model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=prompt)])
            except Exception as exc:  # noqa: BLE001 - 错误分类后统一回喂/抛出。
                last_error = str(exc)
                last_kind = "call"
                continue
            try:
                content = self._message_content_to_text(response.content)
                return self._parse_json_object(content, model_cls), attempt_count
            except Exception as exc:  # noqa: BLE001 - 输出质量问题按 schema 分类。
                last_error = str(exc)
                last_kind = "schema"
        raise DeepSeekInvocationError(
            error_kind=last_kind,
            attempt_count=attempt_count,
            message=f"DeepSeek 输出在 {max_attempts} 次尝试内都无法解析/校验：{last_error}",
        )

    @staticmethod
    def _parse_json_object(text: str, model_cls: type[BaseModel]) -> dict[str, Any]:
        cleaned = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.S)
        if fenced:
            cleaned = fenced.group(1)
        if not cleaned.startswith("{"):
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                cleaned = cleaned[start : end + 1]
        return model_cls.model_validate_json(cleaned).model_dump()
