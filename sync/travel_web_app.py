from __future__ import annotations

import asyncio
import itertools
import json
import operator
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Annotated, Sequence, TypedDict
from urllib.parse import quote_plus
from uuid import uuid4

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
from langchain.tools.render import render_text_description
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_deepseek import ChatDeepSeek
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

try:
    from mcp_tools_adapter import get_mcp_tools_as_langchain
    from multi_agent import MultiAgentTravelPlanner, StructuredTravelPlanner
except ModuleNotFoundError:
    from sync.mcp_tools_adapter import get_mcp_tools_as_langchain
    from sync.multi_agent import MultiAgentTravelPlanner, StructuredTravelPlanner

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = PROJECT_ROOT / "web"

load_dotenv(PROJECT_ROOT / ".env")

MCP_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8098/my-custom-path")


@tool
def get_today() -> str:
    """获取当前系统日期，返回 YYYY-MM-DD。"""

    return datetime.today().strftime("%Y-%m-%d")


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]


class TravelAgent:
    def __init__(self, model: BaseChatModel, tools: list):
        self.raw_model = model
        self.tools = tools
        self.tools_map = {tool.name: tool for tool in tools}
        self.graph = self._build_graph()
        self.conversation_history: list[BaseMessage] = []
        self.tool_events: list[dict[str, str]] = []

    def _build_graph(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("agent_llm", self._call_model)
        workflow.add_node("action", self._call_tool)
        workflow.set_entry_point("agent_llm")
        workflow.add_conditional_edges(
            "agent_llm",
            self._should_continue,
            {"continue": "action", "end": END},
        )
        workflow.add_edge("action", "agent_llm")
        return workflow.compile()

    def _call_model(self, state: AgentState) -> dict:
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """
你是 TravelMind 智慧出行 Agent，负责把用户的自然语言需求变成可执行的旅行方案。

工作要求：
1. 优先使用工具获取事实，不要编造天气、路线、预算、景点和文件路径。
2. 每轮只调用一个工具；观察工具结果后再决定下一步。
3. 如果用户使用“今天、明天、后天”等相对日期，先调用 get_today。
4. 做完整出行规划时，优先调用 amap_plan_routes 获取高德多路线方案；如果高德工具提示未配置或失败，再调用 plan_route 作为降级方案。
5. 同城短途或需要精确 POI 坐标时，可先调用 amap_geocode；跨城/多方式路线可直接调用 amap_plan_routes。
6. 规划旅行方案时，按需调用 get_weather、amap_plan_routes、search_poi、estimate_budget。
7. 如果用户要求保存、导出或生成文件，先形成完整 Markdown 内容，再调用 write_itinerary_file。
8. 最终回答使用中文 Markdown，结构清晰，必须包含“路线对比”和“推荐方案”。
9. 不展示内部推理过程，不输出原始工具 JSON。

可用工具如下：
{tools}
""",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        model_with_tools = self.raw_model.bind_tools(self.tools)
        chain = prompt | model_with_tools
        response = chain.invoke(
            {
                "messages": state["messages"],
                "tools": render_text_description(self.tools),
            }
        )
        return {"messages": [response]}

    def _call_tool(self, state: AgentState) -> dict:
        last_message = state["messages"][-1]
        tool_messages = []

        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call.get("args", {})
            tool = self.tools_map.get(tool_name)

            if tool is None:
                output = f"Tool '{tool_name}' not found."
            else:
                try:
                    output = tool.invoke(tool_args)
                except Exception as exc:
                    output = f"Error executing tool {tool_name}: {exc}"

            output_text = str(output)
            self.tool_events.append(
                {
                    "name": tool_name,
                    "args": str(tool_args),
                    "output": output_text[:700],
                }
            )
            tool_messages.append(
                ToolMessage(content=output_text, tool_call_id=tool_call["id"])
            )

        return {"messages": tool_messages}

    @staticmethod
    def _should_continue(state: AgentState) -> str:
        last_message = state["messages"][-1]
        return "continue" if getattr(last_message, "tool_calls", None) else "end"

    def run(self, query: str) -> dict:
        self.tool_events = []
        inputs = {"messages": self.conversation_history + [HumanMessage(content=query)]}
        final_answer = ""

        for output in self.graph.stream(inputs):
            node_output = output.get("agent_llm")
            if not node_output:
                continue
            messages = node_output.get("messages", [])
            if not messages:
                continue
            last_message = messages[-1]
            if isinstance(last_message, AIMessage) and not last_message.tool_calls:
                final_answer = last_message.content

        if final_answer:
            self.conversation_history.extend(
                [HumanMessage(content=query), AIMessage(content=final_answer)]
            )

        return {"answer": final_answer, "trace": self.tool_events}


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    answer: str
    trace: list[dict[str, str]]
    agent_steps: list[dict[str, str]] = Field(default_factory=list)


class PlanRequest(BaseModel):
    originCity: str = "广州"
    destinationCity: str = "深圳"
    startDate: str = ""
    days: int = 2
    travelers: int = 1
    budget: int | None = None
    intercityModes: list[str] = Field(default_factory=lambda: ["高铁/动车/城际", "自驾"])
    localModes: list[str] = Field(default_factory=lambda: ["公共交通", "打车", "步行"])
    hotelLevel: str = "舒适"
    interests: list[str] = Field(default_factory=lambda: ["经典景点", "美食", "地方特色"])
    preferenceProfile: dict[str, object] = Field(default_factory=dict)
    freeText: str = ""
    hardConstraints: list[str] = Field(default_factory=list)
    softPreferences: list[str] = Field(default_factory=list)


class RefinePlanRequest(BaseModel):
    plan: dict[str, object]
    message: str


class PlanAsyncRequest(PlanRequest):
    clientRequestId: str = ""


app = FastAPI(title="TravelMind Agent Demo", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

_agent: TravelAgent | None = None
_multi_agent_planner: MultiAgentTravelPlanner | None = None
_structured_planner: StructuredTravelPlanner | None = None


def get_amap_remote_mcp_url() -> str:
    explicit_url = os.getenv("AMAP_MCP_URL", "").strip()
    if explicit_url:
        return explicit_url

    enabled = os.getenv("ENABLE_AMAP_REMOTE_MCP", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return ""

    amap_key = (
        os.getenv("AMAP_MAPS_API_KEY")
        or os.getenv("AMAP_API_KEY")
        or os.getenv("GAODE_API_KEY")
        or ""
    ).strip()
    if not amap_key:
        return ""

    return f"https://mcp.amap.com/mcp?key={quote_plus(amap_key)}"


def get_amap_key() -> str:
    return (
        os.getenv("AMAP_MAPS_API_KEY")
        or os.getenv("AMAP_API_KEY")
        or os.getenv("GAODE_API_KEY")
        or ""
    ).strip()


def svg_map_placeholder(message: str) -> Response:
    safe_message = (
        message.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="520" viewBox="0 0 960 520">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#eaf3fb"/>
      <stop offset="1" stop-color="#f6faf7"/>
    </linearGradient>
  </defs>
  <rect width="960" height="520" fill="url(#bg)"/>
  <path d="M90 120h780M90 210h780M90 300h780M90 390h780M210 70v380M390 70v380M570 70v380M750 70v380" stroke="#c9d8e6" stroke-width="2" opacity=".7"/>
  <path d="M350 245C410 230 455 330 520 305S605 210 655 205" fill="none" stroke="#5c8d96" stroke-width="7" stroke-linecap="round" opacity=".58"/>
  <circle cx="350" cy="245" r="20" fill="#ffffff" opacity=".95"/>
  <circle cx="350" cy="245" r="15" fill="#0b7285"/>
  <text x="350" y="251" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#ffffff">1</text>
  <circle cx="520" cy="305" r="20" fill="#ffffff" opacity=".95"/>
  <circle cx="520" cy="305" r="15" fill="#c47a13"/>
  <text x="520" y="311" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#ffffff">2</text>
  <circle cx="655" cy="205" r="20" fill="#ffffff" opacity=".95"/>
  <circle cx="655" cy="205" r="15" fill="#73539c"/>
  <text x="655" y="211" text-anchor="middle" font-family="Arial, sans-serif" font-size="14" font-weight="700" fill="#ffffff">3</text>
  <rect x="246" y="430" width="468" height="44" rx="10" fill="#ffffff" opacity=".92"/>
  <text x="480" y="458" text-anchor="middle" font-family="Microsoft YaHei, Arial, sans-serif" font-size="18" fill="#425466">{safe_message}</text>
</svg>"""
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


def amap_static_marker_label(label: str, index: int) -> str:
    """AMap static marker labels are safest as a single ASCII character."""
    clean = re.sub(r"[^0-9A-Za-z]", "", str(label or "")).strip()
    if len(clean) == 1:
        return clean
    tokens = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return tokens[index % len(tokens)]


def amap_static_error_message(response: requests.Response, title: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"{title or '地图'}暂不可用，已显示点位示意图"
    info = str(payload.get("info") or payload.get("infocode") or "").strip()
    if "CUQPS" in info or payload.get("infocode") == "10021":
        return "高德静态地图限流，已显示点位示意图"
    if info:
        return f"高德静态地图返回错误：{info}，已显示点位示意图"
    return f"{title or '地图'}暂不可用，已显示点位示意图"


def get_agent() -> TravelAgent:
    global _agent
    if _agent is not None:
        return _agent

    if not os.getenv("DEEPSEEK_API_KEY"):
        raise RuntimeError("未检测到 DEEPSEEK_API_KEY，请在项目根目录 .env 中配置。")

    tools = [get_today]
    tools.extend(get_mcp_tools_as_langchain(MCP_URL))
    amap_remote_mcp_url = get_amap_remote_mcp_url()
    if amap_remote_mcp_url:
        try:
            tools.extend(get_mcp_tools_as_langchain(amap_remote_mcp_url))
        except Exception as exc:
            print(f"高德官方远程 MCP 加载失败，继续使用本地 MCP 工具：{exc}")
    model = ChatDeepSeek(model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"), temperature=0.1)
    _agent = TravelAgent(model=model, tools=tools)
    return _agent


def get_multi_agent_planner() -> MultiAgentTravelPlanner:
    global _multi_agent_planner
    if _multi_agent_planner is None:
        _multi_agent_planner = MultiAgentTravelPlanner(MCP_URL)
    return _multi_agent_planner


def get_structured_planner() -> StructuredTravelPlanner:
    global _structured_planner
    if _structured_planner is None:
        _structured_planner = StructuredTravelPlanner(MCP_URL)
    return _structured_planner


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/v2")
def index_v2():
    # 旧版入口已合并进首页，保留 /v2 重定向兼容旧书签。
    return RedirectResponse(url="/", status_code=301)


@app.get("/api/tools")
def list_tools():
    try:
        agent = get_agent()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return [
        {"name": tool.name, "description": tool.description}
        for tool in agent.tools
    ]


@app.get("/api/map-static")
def map_static(markers: str = "", path: str = "", title: str = ""):
    amap_key = get_amap_key()
    if not amap_key:
        return svg_map_placeholder("高德静态地图未配置，已显示点位示意图")

    points = []
    for marker in markers.split(";"):
        parts = marker.split(",")
        if len(parts) < 2:
            continue
        try:
            lng = float(parts[0])
            lat = float(parts[1])
        except ValueError:
            continue
        if -180 <= lng <= 180 and -90 <= lat <= 90:
            label = parts[2].strip() if len(parts) >= 3 and parts[2].strip() else str(len(points) + 1)
            points.append({"lng": lng, "lat": lat, "label": label[:2]})

    if not points:
        return svg_map_placeholder("暂无可用坐标，已显示点位示意图")

    point_text = ";".join(f"{point['lng']:.6f},{point['lat']:.6f}" for point in points[:10])
    marker_styles = "|".join(
        f"mid,0x0B7285,{amap_static_marker_label(point['label'], index)}:{point['lng']:.6f},{point['lat']:.6f}"
        for index, point in enumerate(points[:10])
    )
    label_styles = "|".join(
        f"{point['label']},0,0,16,0xFFFFFF,0x0B7285:{point['lng']:.6f},{point['lat']:.6f}"
        for point in points[:10]
    )
    route_points = []
    for part in path.split(";"):
        if re.match(r"^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$", part.strip()):
            route_points.append(part.strip())
    route_text = ";".join(route_points[:10])

    params = {
        "key": amap_key,
        "size": "960*520",
        "scale": "2",
        "markers": marker_styles or f"mid,0x0B7285,1:{point_text}",
    }
    if label_styles:
        params["labels"] = label_styles
    if route_text and len(route_points) > 1:
        params["paths"] = f"6,0x5C8D96,0.58,,:{route_text}"

    try:
        response = requests.get(
            "https://restapi.amap.com/v3/staticmap",
            params=params,
            timeout=8,
        )
        if response.ok and response.content:
            content_type = response.headers.get("content-type", "image/png")
            if "json" not in content_type.lower():
                return Response(
                    content=response.content,
                    media_type=content_type,
                    headers={"Cache-Control": "no-store"},
                )
        return svg_map_placeholder(amap_static_error_message(response, title))
    except requests.RequestException:
        return svg_map_placeholder(f"{title or '地图'}暂不可用，已显示点位示意图")


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")

    try:
        agent = get_agent()
        return agent.run(request.message.strip())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/multi-agent-chat", response_model=ChatResponse)
def multi_agent_chat(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")

    try:
        planner = get_multi_agent_planner()
        return planner.run(request.message.strip())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _persist_plan_snapshot(plan: dict, *, changed_only: bool = False) -> None:
    """持久化计划快照与偏好（观测失败不影响响应；Phase 5）。"""
    if not isinstance(plan, dict) or not plan.get("plan_id"):
        return
    try:
        from sync import persistence

        persistence.save_plan_snapshot(
            str(plan["plan_id"]), int(plan.get("version") or 0), plan
        )
        hints = ((plan.get("preferences") or {}).get("preferenceProfile") or {}).get("learnedHints") or []
        if hints:
            persistence.save_learned_hints([str(item) for item in hints])
    except Exception:  # noqa: BLE001 - 持久化是旁路
        return


@app.post("/api/plan")
def plan_trip(request: PlanRequest):
    try:
        planner = get_structured_planner()
        if hasattr(request, "model_dump"):
            payload = request.model_dump()
        else:
            payload = request.dict()
        plan = planner.run(payload)
        _persist_plan_snapshot(plan)
        return plan
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/refine-plan")
def refine_plan(request: RefinePlanRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")
    if os.getenv("TRAVELMIND_REFINE", "on").strip().lower() in {"off", "0", "false", "no"}:
        raise HTTPException(status_code=503, detail="结构化追问已通过 TRAVELMIND_REFINE=off 关闭")

    required = ["preferences", "intercity_transport", "local_transport", "hotels", "pois", "weather", "itinerary_days"]
    missing = [key for key in required if not request.plan.get(key)]
    if missing:
        raise HTTPException(status_code=400, detail=f"计划缺少必要字段：{', '.join(missing)}")

    try:
        planner = get_structured_planner()
        result = planner.refine_plan(request.plan, request.message.strip())
        if isinstance(result, dict) and result.get("status") == "ok" and result.get("changed"):
            _persist_plan_snapshot(result.get("plan") or {})
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/plan-async")
def plan_trip_async(request: PlanAsyncRequest):
    """异步规划入口（Phase 5）：立即返回 task_id，进度经 SSE 事件流消费。

    幂等：同一 clientRequestId 在 running/done 状态下直接返回已有 task_id，
    绝不重复启动真实外部调用。TRAVELMIND_PERSISTENCE=off 时 503（前端回退同步）。
    """
    from sync import persistence

    if not persistence.persistence_enabled():
        raise HTTPException(status_code=503, detail="异步任务已通过 TRAVELMIND_PERSISTENCE=off 关闭")

    request_id = str(request.clientRequestId or "").strip()
    if request_id:
        existing = persistence.get_task_by_request(request_id)
        if existing and existing["status"] in {"running", "done"}:
            return {"task_id": existing["task_id"], "replayed": True}

    payload = request.model_dump()
    task_id = f"task-{uuid4().hex[:12]}"
    if not persistence.create_task(task_id, request_id or task_id):
        existing = persistence.get_task_by_request(request_id or task_id)
        if existing:
            return {"task_id": existing["task_id"], "replayed": True}
        raise HTTPException(status_code=500, detail="任务登记失败")

    planner = get_structured_planner()

    def runner() -> None:
        seq = itertools.count()

        def on_progress(event: dict) -> None:
            persistence.append_event(task_id, next(seq), str(event.get("type") or "progress"), event)

        planner._progress.callback = on_progress
        try:
            plan = planner.run(payload)
            persistence.append_event(task_id, next(seq), "done", {"plan_id": plan.get("plan_id")})
            persistence.save_plan_snapshot(str(plan.get("plan_id") or ""), int(plan.get("version") or 0), plan)
            hints = ((plan.get("preferences") or {}).get("preferenceProfile") or {}).get("learnedHints") or []
            if hints:
                persistence.save_learned_hints([str(item) for item in hints])
            persistence.mark_task(task_id, "done", plan_id=str(plan.get("plan_id") or ""))
        except Exception as exc:  # noqa: BLE001 - 任务级错误以 error 事件与任务状态呈现
            message = str(exc)[:300]
            persistence.append_event(task_id, next(seq), "error", {"message": message})
            persistence.mark_task(task_id, "error", error=message)
        finally:
            planner._progress.callback = None

    threading.Thread(target=runner, daemon=True, name=f"plan-{task_id}").start()
    return {"task_id": task_id, "replayed": False}


@app.get("/api/plan-events/{task_id}")
async def plan_events(task_id: str, request: Request):
    """SSE 事件流：step_start/step_end/done/error；断线重连按 Last-Event-ID 续传。"""
    from sync import persistence

    task = persistence.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    async def event_stream():
        last_seq = -1
        try:
            last_seq = int(request.headers.get("last-event-id") or -1)
        except (TypeError, ValueError):
            last_seq = -1
        while True:
            for seq, event, data in persistence.load_events(task_id, after_seq=last_seq):
                last_seq = seq
                yield {"id": str(seq), "event": event, "data": json.dumps(data, ensure_ascii=False)}
                if event in {"done", "error"}:
                    return
            current = persistence.get_task(task_id)
            if current is None:
                yield {"event": "error", "data": json.dumps({"message": "任务不存在或已过期"}, ensure_ascii=False)}
                return
            if current["status"] == "done":
                # 终态但 done 事件缺失（进程中断后重启等）：补发终态事件保证前端收敛。
                yield {"event": "done", "data": json.dumps({"plan_id": current.get("plan_id")}, ensure_ascii=False)}
                return
            if current["status"] in {"error", "interrupted"}:
                message = current.get("error") or "任务已中断"
                yield {"event": "error", "data": json.dumps({"message": message}, ensure_ascii=False)}
                return
            await asyncio.sleep(0.25)

    return EventSourceResponse(event_stream())


@app.get("/api/task/{task_id}")
def task_status(task_id: str):
    """任务状态查询（断线可查询当前状态；done 时带计划快照）。"""
    from sync import persistence

    task = persistence.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    result: dict[str, object] = {
        "task_id": task.get("task_id"),
        "status": task.get("status"),
        "plan_id": task.get("plan_id"),
        "error": task.get("error"),
    }
    if task.get("status") == "done" and task.get("plan_id"):
        plan = persistence.load_plan_snapshot(str(task["plan_id"]))
        if plan:
            result["plan"] = plan
    return result


@app.post("/api/reset")
def reset():
    agent = get_agent()
    agent.conversation_history.clear()
    return {"ok": True}
