import os
import operator
import json
import asyncio
from typing import Annotated, List, TypedDict, Literal, Optional, Dict
from typing_extensions import TypedDict as ExtTypedDict
from dotenv import load_dotenv

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage, AIMessage
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

# 导入你的工具
from app.infras.func.agent_func import search_flights, search_hotels, book_flight, book_hotel, get_weather, search_travel_guides

# --- 0. 配置与初始化 ---
load_dotenv()

llm = AzureChatOpenAI(
    azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    temperature=0.5,
)

# 定义 JSON 模式的 LLM
json_llm = llm.bind(response_format={"type": "json_object"})

# --- 1. 核心 State 定义 ---


class TravelState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]

    # 状态流转
    step: Literal["collect", "plan", "review",
                  "searching", "selecting", "wait_payment", "finish"]

    # 基础槽位
    destination: Optional[str]
    origin: Optional[str]
    dates: Optional[str]
    budget: Optional[str]

    # 方案相关
    generated_plans: Optional[List[Dict]]
    chosen_plan_index: Optional[int]

    # 实时搜索结果缓存
    realtime_options: Optional[Dict]  # { "flights": [...], "hotels": [...] }

    # 预订状态
    booking_status: Optional[Dict]    # { "flight": bool, "hotel": bool }

    booking_results: Optional[Dict]
    router_decision: Literal["continue", "side_chat", "modify"]

# --- 2. 意图识别 (Router) ---


async def intent_router_node(state: TravelState):
    """
    升级后的路由：支持 selecting 阶段的选品操作
    """
    if not state.get("messages"):
        return {"router_decision": "continue"}

    last_msg = state["messages"][-1].content
    current_step = state.get("step", "collect")

    if current_step == "wait_payment":
        pass

    router_prompt = f"""
    你是一个意图分类器。用户当前处于 "{current_step}" 阶段。
    用户最新输入是: "{last_msg}"

    请判断用户意图并输出 JSON (modify / side_chat / continue):

    当前步骤 "{current_step}" 的有效操作定义：
    - collect: 提供/补充 目的地、时间、预算。
    - plan: 等待生成。
    - review: 选择大方案 (如"方案1")。
    - selecting: 选择具体资源 (如"订F1", "预订酒店H2", "全都要", "只要机票")。
    - wait_payment: 支付相关确认。

    规则：
    1. "modify": 用户明确想改核心需求（如“不去日本了去泰国”）。
    2. "side_chat": 用户试图执行当前步骤不支持的操作，或者询问攻略/天气等。
    3. "continue": 用户正在进行当前步骤的有效操作。

    输出格式: {{ "decision": "...", "reason": "..." }}
    """

    response = await json_llm.ainvoke([HumanMessage(content=router_prompt)])
    result = json.loads(response.content)

    print(f"🚦 [Router] Decision: {result['decision']} ({result['reason']})")
    return {"router_decision": result["decision"]}

# --- 3. 节点逻辑 ---

# 3.1 收集需求


async def collect_requirements_node(state: TravelState):
    print("📋 [Node] Collecting Requirements...")
    current_slots = {
        "destination": state.get("destination"),
        "origin": state.get("origin"),
        "dates": state.get("dates"),
        "budget": state.get("budget")
    }
    last_content = state['messages'][-1].content if state.get(
        'messages') else ""

    prompt = f"""
    你是专业的旅行顾问。收集信息：目的地、出发地、日期、预算。
    当前已知: {json.dumps(current_slots, ensure_ascii=False)}
    用户回复: "{last_content}"
    
    请输出 JSON:
    1. 提取 updated_slots
    2. is_complete (bool)
    3. reply (text)
    
    输出格式: {{ "updated_slots": {{...}}, "is_complete": bool, "reply": "..." }}
    """
    response = await json_llm.ainvoke([HumanMessage(content=prompt)])
    data = json.loads(response.content)

    updates = data["updated_slots"]
    updates["messages"] = [AIMessage(content=data["reply"])]

    if data["is_complete"]:
        updates["step"] = "plan"

    return updates

# 3.2 生成方案 (集成 search_travel_guides)


async def generate_plans_node(state: TravelState):
    print("💡 [Node] Generating Plans (with Real RAG)...")

    dest = state.get("destination", "未知")
    reqs = f"从 {state.get('origin')} 去 {dest}, 时间 {state.get('dates')}, 预算 {state.get('budget')}"

    # 1. 先调用攻略工具，获取真实上下文
    print(f"   -> Calling search_travel_guides('{dest} 旅行攻略')...")
    try:
        guides_context = await search_travel_guides.ainvoke({"query": f"{dest} 旅游攻略 必去景点 行程建议"})
    except Exception as e:
        guides_context = "暂无详细攻略，请根据常识生成。"
        print(f"   -> Guide search failed: {e}")

    # 2. 基于真实攻略生成方案
    prompt = f"""
    基于用户需求: {reqs}
    以及目的地的真实攻略信息:
    {guides_context[:2000]} (截取部分)
    
    请生成 3 个截然不同的旅行方案 (经济型、舒适型、豪华型)。
    方案内容必须结合上述攻略中的真实景点和特色。
    
    输出 JSON: {{ "plans": [{{ "id": 1, "name": "...", "price": 0, "details": "..." }}...], "reply_text": "..." }}
    """
    response = await json_llm.ainvoke([HumanMessage(content=prompt)])
    data = json.loads(response.content)

    pretty_msg = data["reply_text"] + "\n"
    for p in data["plans"]:
        pretty_msg += f"\n方案 {p['id']}: {p['name']} ({p['price']}元) - {p['details']}"

    return {
        "generated_plans": data["plans"],
        "step": "review",
        "messages": [AIMessage(content=pretty_msg)]
    }

# 3.3 审核方案 -> 跳转搜索


async def review_plan_node(state: TravelState):
    print("🤔 [Node] Reviewing Plan...")
    last_msg = state["messages"][-1].content.lower()

    idx = -1
    if any(k in last_msg for k in ["1", "一", "穷游", "经济", "第一个"]):
        idx = 0
    elif any(k in last_msg for k in ["2", "二", "舒适", "休闲", "第二个"]):
        idx = 1
    elif any(k in last_msg for k in ["3", "三", "豪华", "奢华", "第三个"]):
        idx = 2

    if idx == -1:
        return {"messages": [AIMessage(content="请明确选择方案 1, 2 或 3？")]}

    plans = state.get("generated_plans", [])
    if not plans or idx >= len(plans):
        return {"messages": [AIMessage(content="方案数据丢失，请重新规划。")], "step": "plan"}

    selected = plans[idx]

    return {
        "chosen_plan_index": idx,
        "step": "searching",  # 下一步去搜索
        "booking_status": {"flight": False, "hotel": False},
        "booking_results": {},
        "messages": [AIMessage(content=f"好的，选择了【{selected['name']}】。正在为您调用接口搜索实时资源...")]
    }

# 3.4 实时搜索 (集成 search_flights / search_hotels)


async def search_realtime_node(state: TravelState):
    print("🔍 [Node] Searching Realtime Options (API)...")

    dest = state.get("destination", "Unknown")
    origin = state.get("origin", "Unknown")
    date_str = state.get("dates", "Unknown")

    # 1. 并行调用真实的搜索工具
    # 注意：search_hotels 需要 check_out，这里我们偷懒传 "flexible" 或者让工具内部处理
    # 更好的做法是用 LLM 拆解 date_str，但为了速度这里直接透传
    print(f"   -> API: Flights({origin}->{dest}) | Hotels({dest})...")

    flight_task = search_flights.ainvoke(
        {"origin": origin, "destination": dest, "date": date_str})
    hotel_task = search_hotels.ainvoke(
        {"location": dest, "check_in": date_str, "check_out": "flexible"})

    # 使用 asyncio.gather 并发请求
    raw_flights, raw_hotels = await asyncio.gather(flight_task, hotel_task)

    # 2. 使用 LLM 清洗非结构化的搜索结果 -> 结构化 JSON
    structure_prompt = f"""
    你是一个数据清洗专家。请将以下从搜索引擎获取的原始文本结果，转换为标准的 JSON 选项列表。
    
    原始机票结果:
    {raw_flights}
    
    原始酒店结果:
    {raw_hotels}
    
    任务:
    1. 提取 2-3 个最佳机票选项 (ID为 F1, F2...)。
    2. 提取 2-3 个最佳酒店选项 (ID为 H1, H2...)。
    3. 如果搜索结果为空或乱码，请基于常识生成 2 个合理的模拟选项作为兜底，并在 carrier/name 中标注 "(模拟数据)"。
    
    输出 JSON 格式:
    {{
        "flights": [{{ "id": "F1", "carrier": "...", "time": "...", "price": "..." }}],
        "hotels": [{{ "id": "H1", "name": "...", "rating": "...", "price": "..." }}],
        "message": "为您找到以下资源..." (简短引导语)
    }}
    """

    response = await json_llm.ainvoke([HumanMessage(content=structure_prompt)])
    data = json.loads(response.content)

    # 构造展示消息
    msg = f"{data['message']}\n\n"
    msg += "**✈️ 机票选项**:\n"
    for f in data["flights"]:
        msg += f"- [ID: {f['id']}] {f['carrier']} ({f['time']}) 价格: {f['price']}\n"

    msg += "\n**🏨 酒店选项**:\n"
    for h in data["hotels"]:
        msg += f"- [ID: {h['id']}] {h['name']} (评分: {h['rating']}) 价格: {h['price']}\n"

    msg += "\n请告诉我您的选择（例如：“订机票F1” 或 “订F1和H1”）。"

    return {
        "realtime_options": {"flights": data["flights"], "hotels": data["hotels"]},
        "step": "selecting",
        "messages": [AIMessage(content=msg)]
    }

# 3.5 执行选品与循环判断


async def execute_selection_node(state: TravelState):
    print("⚙️ [Node] Processing Selection...")

    last_msg = state["messages"][-1].content
    options = state.get("realtime_options", {})
    current_status = state.get(
        "booking_status", {"flight": False, "hotel": False})

    # 1. 分析选择
    prompt = f"""
    用户正在选择预订资源。
    可选资源: {json.dumps(options, ensure_ascii=False)}
    用户输入: "{last_msg}"
    当前状态: {json.dumps(current_status)}
    
    输出 JSON: 
    {{ 
        "selected_flight_id": "F1" or null, 
        "selected_hotel_id": "H1" or null,
        "skip_flight": bool,
        "skip_hotel": bool,
        "reply": "..."
    }}
    """

    response = await json_llm.ainvoke([HumanMessage(content=prompt)])
    decision = json.loads(response.content)

    fid = decision.get("selected_flight_id")
    hid = decision.get("selected_hotel_id")
    reply_parts = []
    new_status = current_status.copy()

    # 2. 执行预订 (调用真实 book 接口)
    # 注意：真实接口可能需要更多参数，这里演示核心流程
    if fid and not current_status["flight"]:
        print(f"   -> Booking Flight {fid}")
        try:
            # 简单调用预订接口 (参数可从 state 补全)
            await book_flight.ainvoke({
                "from_airport": state.get("origin", "SHA"),
                "to_airport": state.get("destination", "NRT")
            })
            new_status["flight"] = True
            reply_parts.append(f"机票 {fid} 锁定成功")
        except Exception as e:
            reply_parts.append(f"机票 {fid} 失败: {e}")

    if hid and not current_status["hotel"]:
        print(f"   -> Booking Hotel {hid}")
        try:
            await book_hotel.ainvoke({"hotel_name": f"Hotel {hid}"})
            new_status["hotel"] = True
            reply_parts.append(f"酒店 {hid} 锁定成功")
        except Exception as e:
            reply_parts.append(f"酒店 {hid} 失败: {e}")

    if decision.get("skip_flight"):
        new_status["flight"] = True
    if decision.get("skip_hotel"):
        new_status["hotel"] = True

    # 3. 循环逻辑
    final_msg = decision["reply"]
    if reply_parts:
        final_msg = "，".join(reply_parts)

    is_all_done = new_status["flight"] and new_status["hotel"]

    if is_all_done:
        return {
            "booking_status": new_status,
            "step": "wait_payment",
            "messages": [AIMessage(content=f"{final_msg}。\n\n订单已生成，请点击支付...")]
        }
    else:
        missing = []
        if not new_status["flight"]:
            missing.append("机票")
        if not new_status["hotel"]:
            missing.append("酒店")
        loop_msg = f"{final_msg}。\n\n您还需要预订 {'、'.join(missing)} 吗？请继续选择，或回复“跳过”。"
        return {
            "booking_status": new_status,
            "step": "selecting",
            "messages": [AIMessage(content=loop_msg)]
        }

# 3.6 侧轨 (集成 search_travel_guides)


async def side_chat_node(state: TravelState):
    print("💬 [Node] Side Chat...")
    last_msg = state["messages"][-1].content

    # 如果用户问攻略/指南/玩法，直接调用工具
    if any(k in last_msg for k in ["攻略", "指南", "玩", "吃", "景点", "推荐"]):
        print("   -> Calling search_travel_guides for Side Chat...")
        query = f"{state.get('destination', '')} {last_msg}"
        guides = await search_travel_guides.ainvoke({"query": query})
        return {"messages": [AIMessage(content=f"为您找到相关攻略信息：\n{guides}")]}

    # 天气
    if "天气" in last_msg:
        weather = await get_weather.ainvoke({"location": state.get("destination", "北京")})
        return {"messages": [AIMessage(content=f"当地天气: {weather}")]}

    # 其他闲聊
    res = await llm.ainvoke([
        SystemMessage(content="礼貌回应闲聊，并引导回主流程。"),
        HumanMessage(content=last_msg)
    ])
    return {"messages": [res]}

# 3.7 智能修改


async def modify_req_node(state: TravelState):
    print("✏️ [Node] Modifying...")
    return {
        "step": "collect",
        "generated_plans": [],
        "messages": [AIMessage(content="好的，重新规划。请告诉我新的需求。")]
    }


def route_after_modify(state: TravelState):
    if state.get("step") == "plan":
        return "plan"
    return END

# --- 4. 构建图 ---


workflow = StateGraph(TravelState)

workflow.add_node("intent_router", intent_router_node)
workflow.add_node("collect", collect_requirements_node)
workflow.add_node("plan", generate_plans_node)
workflow.add_node("review", review_plan_node)
workflow.add_node("search_realtime", search_realtime_node)
workflow.add_node("execute_select", execute_selection_node)
workflow.add_node("side_chat", side_chat_node)
workflow.add_node("modify", modify_req_node)
workflow.add_node("wait_payment", lambda x: {
                  "messages": [AIMessage(content="支付回调...")]})

workflow.add_edge(START, "intent_router")


def route_next_step(state: TravelState):
    decision = state.get("router_decision", "continue")
    if decision == "modify":
        return "modify"
    if decision == "side_chat":
        return "side_chat"
    return state.get("step", "collect")


workflow.add_conditional_edges(
    "intent_router",
    route_next_step,
    {
        "modify": "modify",
        "side_chat": "side_chat",
        "collect": "collect",
        "plan": "plan",
        "review": "review",
        "searching": "search_realtime",
        "selecting": "execute_select",
        "wait_payment": "wait_payment"
    }
)

workflow.add_edge("side_chat", END)
workflow.add_edge("collect", END)
workflow.add_edge("review", END)
workflow.add_edge("search_realtime", END)
workflow.add_edge("execute_select", END)
workflow.add_edge("wait_payment", END)
workflow.add_conditional_edges("modify", route_after_modify, {
                               "plan": "plan", END: END})
workflow.add_edge("plan", END)

memory = MemorySaver()
graph_app = workflow.compile(
    checkpointer=memory,
    interrupt_before=["wait_payment"]
)
