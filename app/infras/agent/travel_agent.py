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
    核心升级：增加了对“当前步骤是否支持该操作”的判断。
    """
    # 增加安全性检查：确保 messages 不为空
    if not state.get("messages"):
        return {"router_decision": "continue"}

    last_msg = state["messages"][-1].content
    current_step = state.get("step", "collect")

    # 如果处于等待支付状态，特殊处理
    if current_step == "wait_payment":
        pass

    router_prompt = f"""
    你是一个严格的意图分类器。用户当前处于旅行规划的 "{current_step}" 阶段。
    用户最新输入是: "{last_msg}"

    请根据当前步骤判断用户意图，并输出 JSON：

    1. "modify": 用户明确想要改变目的地、时间、预算等核心条件。
    
    2. "side_chat": 
       - 用户问天气、攻略等无关问题。
       - **关键规则**：如果用户试图执行当前步骤无法完成的操作（例如在 "collect" 阶段就说 "选方案1"，或者在 "plan" 阶段还没出结果就说 "支付"），这属于无效操作，必须归类为 "side_chat"，以便系统解释并引导。
    
    3. "continue": 
       - 用户正在回答当前步骤的问题（例如在 "collect" 回答预算）。
       - 用户在 "review" 阶段选择方案。
       - 用户在 "wait_payment" 阶段询问支付细节。

    当前步骤 "{current_step}" 的有效操作定义：
    - collect: 提供/补充 目的地、时间、预算。
    - plan: 等待生成（通常此时不会有用户输入，如果有，通常是 modify 或 side_chat）。
    - review: 选择具体的方案（如“方案1”，“第二个”）。
    - wait_payment: 确认支付或询问支付状态。

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

# 节点 E: 侧轨 - 闲聊/问询/无效操作处理 (Side Chat)


async def side_chat_node(state: TravelState):
    print("💬 [Node] Side Chat (RAG/Weather/Invalid Action)...")
    last_msg = state["messages"][-1].content
    current_step = state.get("step", "collect")

    # 这里可以调用 get_weather 或 search_travel_guides
    if "天气" in last_msg:
        weather = await get_weather.ainvoke({"location": state.get("destination", "北京")})
        reply = f"当地天气如下：{weather}"
    else:
        # 升级 Prompt：让 Side Chat 能够处理“无效操作”的解释
        system_prompt = f"""
        你是一个旅行助手。用户当前处于 "{current_step}" 步骤。
        
        用户的输入可能是：
        1. 闲聊或询问天气、攻略等（与流程无关）。
        2. 试图执行当前步骤无法完成的操作（例如在“collect”阶段就要求“选方案”或“支付”）。

        对于情况 1：简短回答问题，并温柔地引导用户回到主流程。
        对于情况 2：明确告知用户当前还不能这样做，解释原因，并引导用户完成当前步骤。

        例如：如果在 collect 阶段用户说“选方案1”，你应该回：“我们还没生成方案呢。请先告诉我您的出发地和预算，我才能为您规划。”
        """

        reply = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=last_msg)
        ])
        reply = reply.content

    return {"messages": [AIMessage(content=reply)]}

# 节点 F: 侧轨 - 智能修改需求 (Smart Modify)


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

# 核心路由逻辑函数：modify 后的自动跳转逻辑


def route_after_modify(state: TravelState):
    if state.get("step") == "plan":
        return "plan"  # 如果 modify 决定了重算，直接进 plan 节点
    return END  # 否则结束等待用户

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

# 设置入口
workflow.add_edge(START, "intent_router")

# 核心路由逻辑函数


def route_next_step(state: TravelState):
    decision = state.get("router_decision", "continue")
    current_step = state.get("step", "collect")

    if decision == "modify":
        return "modify"

    if decision == "side_chat":
        return "side_chat"

    # continue 走主流程
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

# modify 后的条件边
workflow.add_conditional_edges(
    "modify",
    route_after_modify,
    {
        "plan": "plan",
        END: END
    }
)

# 侧轨执行完，回到 Router 等待下一次输入
workflow.add_edge("side_chat", END)
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
    interrupt_before=["wait_payment"]
)
