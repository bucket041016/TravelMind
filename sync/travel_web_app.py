from __future__ import annotations

import operator
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Sequence, TypedDict
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
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

MCP_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8083/my-custom-path")


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
  <circle cx="350" cy="245" r="16" fill="#1479c9"/>
  <circle cx="520" cy="305" r="16" fill="#24a36a"/>
  <circle cx="655" cy="205" r="16" fill="#d88a17"/>
  <path d="M350 245C410 230 455 330 520 305S605 210 655 205" fill="none" stroke="#1479c9" stroke-width="8" stroke-linecap="round" opacity=".55"/>
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
        f"mid,0x1479C9,{amap_static_marker_label(point['label'], index)}:{point['lng']:.6f},{point['lat']:.6f}"
        for index, point in enumerate(points[:10])
    )
    label_styles = "|".join(
        f"{point['label']},0,0,14,0xFFFFFF,0x1479C9:{point['lng']:.6f},{point['lat']:.6f}"
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
        "markers": marker_styles or f"mid,0x1479C9,1:{point_text}",
    }
    if label_styles:
        params["labels"] = label_styles
    if route_text and len(route_points) > 1:
        params["paths"] = f"8,0x1479C9,0.8,,:{route_text}"

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


@app.post("/api/plan")
def plan_trip(request: PlanRequest):
    try:
        planner = get_structured_planner()
        if hasattr(request, "model_dump"):
            payload = request.model_dump()
        else:
            payload = request.dict()
        return planner.run(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/reset")
def reset():
    agent = get_agent()
    agent.conversation_history.clear()
    return {"ok": True}
