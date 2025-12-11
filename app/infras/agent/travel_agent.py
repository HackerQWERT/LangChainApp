import os
import operator
import json
from typing import Annotated, List, TypedDict, Literal, Optional, Dict
# For Python < 3.12 compatibility
from typing_extensions import TypedDict as ExtTypedDict
from dotenv import load_dotenv

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage, AIMessage
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver  # 生产环境换成 PostgresSaver

# 导入你的工具 (假设在 my_tools.py)
from app.infras.func import (
    search_flights, search_hotels, book_flight, book_hotel,
    get_weather, search_travel_guides
)

# --- 0. 配置与初始化 ---
load_dotenv()

llm = AzureChatOpenAI(
    azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    temperature=1,
)

# 定义 JSON 模式的 LLM (用于精准提取信息)
json_llm = llm.bind(response_format={"type": "json_object"})

# --- 1. 核心 State 定义 (Slots) ---
# 这是工业级 Agent 的核心：显式的状态槽位


class TravelState(TypedDict):
    # 基础聊天记录 (使用 operator.add 确保消息是追加而非覆盖)
    messages: Annotated[List[BaseMessage], operator.add]

    # 流程控制
    step: Literal["collect", "plan", "review",
                  "execute", "wait_payment", "finish"]

    # 用户需求槽位 (Slots)
    destination: Optional[str]
    origin: Optional[str]
    dates: Optional[str]
    budget: Optional[str]
    people: Optional[str]

    # 中间产物
    generated_plans: Optional[List[Dict]]  # LLM 生成的 3 个方案
    chosen_plan_index: Optional[int]      # 用户选了第几个
    booking_results: Optional[Dict]       # 预订成功后的回执

    # 路由信号
    router_decision: Literal["continue", "side_chat", "modify"]

# --- 2. 意图识别 (Router Logic) ---


class RouterOutput(BaseModel):
    decision: Literal["continue", "side_chat", "modify"]
    reason: str


async def intent_router_node(state: TravelState):
    """
    守门员节点：分析用户最新一句话的意图。
    - continue: 顺着主流程往下走 (补充信息、确认方案)
    - modify: 想要修改已经确定的需求 (改目的地、改时间)
    - side_chat: 闲聊 (天气、签证、甚至问你是谁)
    """
    # 增加安全性检查：确保 messages 不为空
    if not state.get("messages"):
        return {"router_decision": "continue"}

    last_msg = state["messages"][-1].content
    current_step = state.get("step", "collect")

    # 如果处于等待支付状态，特殊处理：
    # 除非用户明确说“不买了”或“改需求”，否则视为 continue (可能是在问支付问题)
    if current_step == "wait_payment":
        pass  # 继续走通用逻辑，但 Prompt 可以微调

    router_prompt = f"""
    你是一个意图分类器。用户当前处于旅行规划的 "{current_step}" 阶段。
    用户最新输入是: "{last_msg}"

    请分析用户意图并输出 JSON:
    - "modify": 如果用户明确想要改变目的地、时间、预算等核心条件 (如: "换个时间", "去泰国吧", "预算不够")。
    - "side_chat": 如果用户问天气、攻略、或者与当前规划步骤无关的问题。
    - "continue": 如果用户是在回答系统的问题、确认方案、选择方案、推进流程，或者在支付阶段询问支付相关问题。

    输出格式: {{ "decision": "...", "reason": "..." }}
    """

    response = await json_llm.ainvoke([HumanMessage(content=router_prompt)])
    result = json.loads(response.content)

    print(f"🚦 [Router] Decision: {result['decision']} ({result['reason']})")
    return {"router_decision": result["decision"]}

# --- 3. 节点逻辑 (Nodes) ---

# 节点 A: 需求收集 (Collect)


async def collect_requirements_node(state: TravelState):
    print("📋 [Node] Collecting Requirements...")

    # 构建当前已知信息
    current_slots = {
        "destination": state.get("destination"),
        "origin": state.get("origin"),
        "dates": state.get("dates"),
        "budget": state.get("budget")
    }

    # 确保 messages 存在
    last_content = state['messages'][-1].content if state.get(
        'messages') else ""

    prompt = f"""
    你是专业的旅行顾问。你的目标是收集以下信息：目的地、出发地、日期、预算。
    
    当前已知: {json.dumps(current_slots, ensure_ascii=False)}
    用户最新回复: "{last_content}"
    
    请执行以下操作并输出 JSON:
    1. 从用户回复中提取新的槽位信息 (updated_slots)。
    2. 判断所有必要信息是否已收集完毕 (is_complete)。
    3. 生成回复用户的文本 (reply)。如果未收集完，请追问缺少的项；如果收集完了，请告诉用户即将生成方案。

    JSON 输出格式:
    {{
        "updated_slots": {{ "destination": "...", ... }},
        "is_complete": true/false,
        "reply": "..."
    }}
    """

    response = await json_llm.ainvoke([HumanMessage(content=prompt)])
    data = json.loads(response.content)

    # 更新 State
    updates = data["updated_slots"]
    # 注意：这里使用 AIMessage，因为 state 定义里使用了 operator.add，所以会自动追加
    updates["messages"] = [AIMessage(content=data["reply"])]

    if data["is_complete"]:
        updates["step"] = "plan"  # 状态转移：进入规划阶段
    # 如果没完成，step 保持不变（LangGraph 默认行为是不更新未返回的 key）

    return updates

# 节点 B: 生成方案 (Generate Plans)


async def generate_plans_node(state: TravelState):
    print("💡 [Node] Generating Plans...")

    reqs = f"从 {state.get('origin', '未知')} 去 {state.get('destination', '未知')}, 时间 {state.get('dates', '待定')}, 预算 {state.get('budget', '待定')}"

    # 在这里可以先调用 Search Tools 获取真实航班价格，作为 context 传给 LLM
    # 为了演示简洁，直接让 LLM 生成结构化方案

    prompt = f"""
    基于需求: {reqs}
    请生成 3 个截然不同的旅行方案 (经济型、舒适型、豪华型)。
    
    请严格输出 JSON 格式:
    {{
        "plans": [
            {{ "id": 1, "name": "特种兵穷游", "price": 2000, "details": "..." }},
            {{ "id": 2, "name": "舒适休闲", "price": 5000, "details": "..." }},
            {{ "id": 3, "name": "奢华享受", "price": 20000, "details": "..." }}
        ],
        "reply_text": "我为您准备了三个方案..."
    }}
    """

    response = await json_llm.ainvoke([HumanMessage(content=prompt)])
    data = json.loads(response.content)

    # 格式化输出给用户看
    pretty_msg = data["reply_text"] + "\n"
    for p in data["plans"]:
        pretty_msg += f"\n方案 {p['id']}: {p['name']} ({p['price']}元) - {p['details']}"

    return {
        "generated_plans": data["plans"],
        "step": "review",
        "messages": [AIMessage(content=pretty_msg)]
    }

# 节点 C: 用户选方案 (Review & Choose)


async def review_plan_node(state: TravelState):
    print("🤔 [Node] Reviewing Plan...")
    last_msg = state["messages"][-1].content.lower()  # 转小写方便匹配

    # 增强匹配逻辑：支持自然语言选择
    idx = -1
    if any(k in last_msg for k in ["1", "一", "穷游", "经济", "第一个"]):
        idx = 0
    elif any(k in last_msg for k in ["2", "二", "舒适", "休闲", "第二个"]):
        idx = 1
    elif any(k in last_msg for k in ["3", "三", "豪华", "奢华", "第三个"]):
        idx = 2

    if idx == -1:
        return {"messages": [AIMessage(content="请明确告诉我您选择方案 1 (经济), 2 (舒适) 还是 3 (豪华)？")]}

    # 确保索引不越界
    plans = state.get("generated_plans", [])
    if not plans or idx >= len(plans):
        return {"messages": [AIMessage(content="抱歉，方案数据似乎有误，请重新规划。")], "step": "plan"}

    selected = plans[idx]
    reply = f"好的！您选择了【{selected['name']}】。我正在为您进行实时预订锁定..."

    return {
        "chosen_plan_index": idx,
        "step": "execute",
        "messages": [AIMessage(content=reply)]
    }

# 节点 D: 执行预订 (Execute - 调用你的 Tools)


async def execute_booking_node(state: TravelState):
    print("⚙️ [Node] Executing Tools...")

    idx = state.get("chosen_plan_index")
    plans = state.get("generated_plans", [])

    if idx is None or not plans:
        return {"step": "plan", "messages": [AIMessage(content="预订信息丢失，请重新规划。")]}

    plan = plans[idx]
    dest = state.get("destination", "未知目的地")
    origin = state.get("origin", "未知出发地")

    # 这里调用你真实的 Tools，确保传参正确
    # 注意：假设 book_flight 接受 from_airport/to_airport，book_hotel 接受 hotel_name
    try:
        flight_res = await book_flight.ainvoke({
            "from_airport": origin,
            "to_airport": dest
        })
        hotel_res = await book_hotel.ainvoke({
            "hotel_name": f"{dest} Top Hotel"
        })
    except Exception as e:
        return {"messages": [AIMessage(content=f"预订过程中出现错误: {str(e)}")]}

    result_summary = f"预订成功！\n航班: {flight_res}\n酒店: {hotel_res}\n总价: {plan['price']}"

    return {
        "booking_results": {"flight": flight_res, "hotel": hotel_res},
        "step": "wait_payment",
        "messages": [AIMessage(content=f"{result_summary}\n\n[系统] 订单已创建，请点击链接支付...")]
    }

# 节点 E: 侧轨 - 闲聊/问询 (Side Chat)


async def side_chat_node(state: TravelState):
    print("💬 [Node] Side Chat (RAG/Weather)...")
    last_msg = state["messages"][-1].content

    # 这里可以调用 get_weather 或 search_travel_guides
    if "天气" in last_msg:
        weather = await get_weather.ainvoke({"location": state.get("destination", "北京")})
        reply = f"当地天气如下：{weather}"
    else:
        # 普通闲聊
        reply = await llm.ainvoke([
            SystemMessage(
                content="你是一个旅行助手。用户问了一个跟当前预订流程无关的问题，请简短回答，并引导用户回到主流程。"),
            HumanMessage(content=last_msg)
        ])
        reply = reply.content

    return {"messages": [AIMessage(content=reply)]}

# 节点 F: 侧轨 - 智能修改需求 (Smart Modify)
# 改动核心：不再无脑重置到 collect，而是智能判断是否需要重算方案


async def modify_req_node(state: TravelState):
    print("✏️ [Node] Modifying Requirements (Smart)...")
    last_msg = state["messages"][-1].content

    # 1. 提取变更的槽位
    current_slots = {
        "destination": state.get("destination"),
        "origin": state.get("origin"),
        "dates": state.get("dates"),
        "budget": state.get("budget")
    }

    prompt = f"""
    用户想要修改旅行需求。
    当前需求: {json.dumps(current_slots, ensure_ascii=False)}
    用户输入: "{last_msg}"

    请执行:
    1. 提取用户想要修改的字段 (如 destination, dates, budget)。
    2. 更新后的完整需求槽位。
    3. 判断变更是否巨大以至于需要重新生成方案 (replan_required)。
       - 改目的地、日期、出发地 -> 通常必须 replan。
       - 改预算 -> 可能需要 replan。
       - 只是补充备注 -> 不需要 replan。
    
    输出 JSON: {{ "updated_slots": {{...}}, "replan_required": true/false, "reply": "..." }}
    """

    response = await json_llm.ainvoke([HumanMessage(content=prompt)])
    data = json.loads(response.content)

    updates = data["updated_slots"]
    updates["messages"] = [AIMessage(content=data["reply"])]

    # 2. 智能路由状态
    if data["replan_required"]:
        # 如果需要重算，直接跳到 plan，而不是 collect！
        # 只要信息完整，就不用回 collect 废话
        is_complete = all(updates.get(k)
                          for k in ["destination", "origin", "dates", "budget"])

        if is_complete:
            print("   -> 变更导致重算，且信息完整，直接进入 Plan 阶段")
            updates["step"] = "plan"
            updates["generated_plans"] = []  # 清空旧方案
            updates["chosen_plan_index"] = None
        else:
            print("   -> 变更导致重算，但信息缺失，回到 Collect 阶段")
            updates["step"] = "collect"
    else:
        # 如果只是微调（比如改个备注），保持当前 step 不变
        print("   -> 微调变更，保持当前步骤")
        pass  # step 保持原样

    return updates

# --- 4. 构建图 (Graph Construction) ---

workflow = StateGraph(TravelState)

# 添加节点
workflow.add_node("intent_router", intent_router_node)
workflow.add_node("collect", collect_requirements_node)
workflow.add_node("plan", generate_plans_node)
workflow.add_node("review", review_plan_node)
workflow.add_node("execute", execute_booking_node)
workflow.add_node("side_chat", side_chat_node)
workflow.add_node("modify", modify_req_node)
# 增加一个空的 wait_payment 节点作为中断锚点
workflow.add_node("wait_payment", lambda x: {"messages": [
                  AIMessage(content="收到支付回调，继续处理...")]})

# 设置入口：每次用户说话，先过 Router
workflow.add_edge(START, "intent_router")

# 核心路由逻辑函数


def route_next_step(state: TravelState):
    # 使用 .get() 设定默认值，防止 KeyError
    decision = state.get("router_decision", "continue")
    current_step = state.get("step", "collect")

    # 1. 如果用户想修改，最高优先级
    if decision == "modify":
        return "modify"

    # 2. 如果用户在闲聊，进侧轨
    if decision == "side_chat":
        return "side_chat"

    # 3. 否则，继续主流程 (根据当前 step 决定去哪个节点)
    return current_step


# 添加条件边
workflow.add_conditional_edges(
    "intent_router",
    route_next_step,
    {
        "modify": "modify",
        "side_chat": "side_chat",
        "collect": "collect",
        "plan": "plan",
        "review": "review",
        "execute": "execute",
        "wait_payment": "wait_payment"
    }
)

# 侧轨执行完，回到 Router 等待下一次输入（或者直接结束等待用户新输入）
# 注意：这里使用 END 是正确的。MemorySaver 会保存状态。
# 下次用户说话时，Start -> Intent Router，此时 State 里的 Step 依然是原来的 Step。
workflow.add_edge("side_chat", END)
workflow.add_edge("modify", END)
workflow.add_edge("collect", END)
workflow.add_edge("review", END)

# Plan 节点执行完 -> END (展示给用户)
workflow.add_edge("plan", END)

# Execute 执行完 -> Wait Payment
workflow.add_edge("execute", "wait_payment")
# Wait Payment 之后 -> Finish
workflow.add_edge("wait_payment", END)

# 设置持久化 (MemorySaver 模拟 Postgres)
memory = MemorySaver()
graph_app = workflow.compile(
    checkpointer=memory,
    interrupt_before=["wait_payment"]  # 关键修改：在进入支付等待前中断，模拟收银台模式
)
