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
from app.infras.func import (
    lookup_airport_code,
    search_flights,
    confirm_flight,
    confirm_hotel,
    lock_flight,
    lock_hotel,
    query_booked_flights,
    query_booked_hotels,
    get_weather,
    search_travel_guides,
    search_hotels,
    get_current_time
)

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

    # 基础槽位 (已移除 budget)
    destination: Optional[str]
    origin: Optional[str]
    dates: Optional[str]
    # budget: Optional[str]  <-- Removed

    # 方案相关
    generated_plans: Optional[List[Dict]]
    chosen_plan_index: Optional[int]

    # 实时搜索结果缓存
    realtime_options: Optional[Dict]  # { "flights": [...], "hotels": [...] }

    # 待支付的订单信息 (包含锁单后的 order_id)
    pending_selection: Optional[Dict]

    # 预订状态 (记录是否已完成预订)
    booking_status: Optional[Dict]    # { "flight": bool, "hotel": bool }

    booking_results: Optional[Dict]
    # 新增 "check_weather" 状态
    router_decision: Literal["continue",
                             "side_chat", "modify", "check_weather"]

# --- 2. 意图识别 (Router) ---


async def intent_router_node(state: TravelState):
    """
    升级后的路由：优化 Review 阶段的意图识别，防止方案选择被误判为闲聊
    """
    if not state.get("messages"):
        return {"router_decision": "continue"}

    last_msg = state["messages"][-1].content
    current_step = state.get("step", "collect")

    # 获取当前上下文中的关键信息（用于辅助判断）
    # 如果处于 Review 阶段，把方案名喂给 Router，让它知道这些词不是闲聊
    context_info = ""
    if current_step == "review":
        plans = state.get("generated_plans", [])
        plan_names = [p['name'] for p in plans]
        context_info = f"当前待选方案名: {plan_names}"
    elif current_step == "wait_payment":
        context_info = "当前处于支付确认阶段，用户需要确认支付。"
    elif current_step == "finish":
        context_info = "当前订单已完成/已结束。用户可能在询问结果、感谢或发起新话题。"

    router_prompt = f"""
    你是一个意图分类器。用户当前处于 "{current_step}" 阶段。
    用户最新输入是: "{last_msg}"
    {context_info}

    请判断用户意图并输出 JSON (modify / side_chat / check_weather / continue):

    当前步骤 "{current_step}" 的有效操作定义：
    - collect: 提供/补充 目的地、时间。 (注意：不再需要预算)
    - plan: 等待生成。
    - review: 用户正在进行方案选择。注意：如果用户提及方案中的关键词（如“特种兵”、“舒适”、“第一个”），或者针对方案提问，都属于 "continue"。
    - selecting: 选择具体资源 (如"订F1", "预订酒店H2", "全都要", "只要机票")。
    - wait_payment: 确认支付、支付、好的、确认等同意支付的词汇；或者询问总价详情。这都属于 "continue"。
    - finish: 订单已结束。用户的任何追问（如“成功了吗”）通常归类为 continue 或 side_chat；如果用户想去新地方，归类为 modify。

    规则：
    1. "modify": 用户明确想改核心需求（如“不去日本了去泰国”），或者在finish阶段想开启新行程。
    2. "check_weather": 用户明确询问天气、气温、下雨等气象信息。
    3. "side_chat": 只有当用户的话题完全脱离当前业务流（如询问毫无关系的知识、闲聊无关话题）时才选此项。**如果在 Review 阶段提及了方案名中的词（如特种兵），绝对不是 side_chat，而是 continue。**
    4. "continue": 用户正在进行当前步骤的有效操作（包括选择方案、确认支付、订单完成后的追问）。

    输出格式: {{ "decision": "...", "reason": "..." }}
    """

    try:
        response = await json_llm.ainvoke([HumanMessage(content=router_prompt)])
        result = json.loads(response.content)
    except Exception as e:
        print(f"Router Error: {e}")
        return {"router_decision": "continue"}

    print(f"🚦 [Router] Decision: {result['decision']} ({result['reason']})")
    return {"router_decision": result["decision"]}

# --- 3. 节点逻辑 ---

# 3.1 收集需求 (已移除 Budget)


async def collect_requirements_node(state: TravelState):
    print("📋 [Node] Collecting Requirements...")
    current_slots = {
        "destination": state.get("destination"),
        "origin": state.get("origin"),
        "dates": state.get("dates")
        # "budget": state.get("budget") <-- Removed
    }
    last_content = state['messages'][-1].content if state.get(
        'messages') else ""

    prompt = f"""
    你是专业的旅行顾问。收集信息：目的地、出发地、日期。
    (注意：我们不再询问预算信息)
    
    当前已知: {json.dumps(current_slots, ensure_ascii=False)}
    用户回复: "{last_content}"
    
    请输出 JSON:
    1. 提取 updated_slots
    2. is_complete (bool) - 当目的地、出发地、日期都具备时为 true
    3. reply (text)
       - 如果信息不全，请礼貌追问。
       - **如果 is_complete 为 true (信息已全)，请回复：“信息已确认，正在为您调用攻略并生成定制方案，请稍候...” (不要问用户是否需要方案，因为下一步会自动生成)。**
    
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
    # 移除预算字段
    reqs = f"从 {state.get('origin')} 去 {dest}, 时间 {state.get('dates')}"

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
    {str(guides_context)[:2000]} (截取部分)
    
    请生成 3 个截然不同的旅行方案 (例如：经济型、舒适型、豪华型，或者特种兵、深度游等)。
    方案内容必须结合上述攻略中的真实景点和特色。
    
    输出 JSON: {{ "plans": [{{ "id": 1, "name": "...", "price_estimate": "...", "details": "..." }}...], "reply_text": "..." }}
    """
    response = await json_llm.ainvoke([HumanMessage(content=prompt)])
    data = json.loads(response.content)

    pretty_msg = data["reply_text"] + "\n"
    for p in data["plans"]:
        # price_estimate 是 LLM 估算的文本，不再是具体的 budget 数字
        pretty_msg += f"\n方案 {p['id']}: {p['name']} ({p.get('price_estimate', '价格待定')}) - {p['details']}"

    return {
        "generated_plans": data["plans"],
        "step": "review",
        "messages": [AIMessage(content=pretty_msg)]
    }

# 3.3 审核方案 -> 跳转搜索 (已修复：使用语义匹配)


async def review_plan_node(state: TravelState):
    print("🤔 [Node] Reviewing Plan (Semantic Matching)...")
    last_msg = state["messages"][-1].content
    plans = state.get("generated_plans", [])

    if not plans:
        return {"messages": [AIMessage(content="方案数据丢失，请重新规划。")], "step": "plan"}

    # 构建 Prompt 让 LLM 帮我们识别用户选了哪个方案
    # 将方案简化成 ID: Name 的形式给 LLM 参考
    plan_options = "\n".join(
        [f"ID {i}: {p['name']} ({p.get('details', '')[:20]}...)" for i, p in enumerate(plans)])

    prompt = f"""
    用户正在从以下旅行方案中进行选择：
    {plan_options}

    用户输入: "{last_msg}"

    任务：
    判断用户选择了哪一个方案。
    1. 如果用户明确选择了某个方案（通过ID、名称关键词、或者描述如“最便宜的”、“特种兵”），返回 index (0, 1, 2)。
    2. 如果用户没有做出选择（例如只是在提问，或者由于犹豫不决），返回 -1。

    输出 JSON: {{ "chosen_index": int, "reply": "若未选择时的引导语" }}
    """

    try:
        response = await json_llm.ainvoke([HumanMessage(content=prompt)])
        result = json.loads(response.content)
        idx = result.get("chosen_index", -1)
    except Exception as e:
        print(f"Review Match Error: {e}")
        idx = -1

    # 初始化 booking_status
    initial_booking_status = {"flight": False, "hotel": False}

    # 逻辑分支
    if idx != -1 and 0 <= idx < len(plans):
        selected = plans[idx]
        return {
            "chosen_plan_index": idx,
            "step": "searching",  # 成功匹配，进入下一步
            "booking_status": initial_booking_status,
            "booking_results": {},
            "messages": [AIMessage(content=f"好的，选择了【方案{idx+1}: {selected['name']}】。正在为您调用接口搜索实时资源...")]
        }
    else:
        # 匹配失败，或者用户在犹豫，停留在当前步骤
        fallback_msg = result.get("reply", "请问您具体想选择哪一个方案呢？（可以说“方案1”或“特种兵那个”）")
        return {
            "messages": [AIMessage(content=fallback_msg)]
            # step 保持不变，还是 review，等待用户下一次输入
        }

# 3.4 实时搜索 (集成 search_flights / search_hotels)


async def search_realtime_node(state: TravelState):
    print("🔍 [Node] Searching Realtime Options (API)...")

    dest = state.get("destination", "Unknown")
    origin = state.get("origin", "Unknown")
    date_str = state.get("dates", "Unknown")

    print(f"   -> API: Flights({origin}->{dest}) | Hotels({dest})...")

    # 并行调用
    flight_task = search_flights.ainvoke(
        {"origin": origin, "destination": dest, "date": date_str})
    hotel_task = search_hotels.ainvoke(
        {"location": dest, "check_in": date_str, "check_out": "flexible"})

    raw_flights, raw_hotels = await asyncio.gather(flight_task, hotel_task)

    # 清洗数据
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

# 3.5 执行选品与计算总价 + 锁单 (Locking) - 支持分步处理与严格校验


async def execute_selection_node(state: TravelState):
    print("⚙️ [Node] Processing Selection, Locking (One-by-One/Independent)...")

    last_msg = state["messages"][-1].content
    options = state.get("realtime_options", {})
    current_status = state.get(
        "booking_status", {"flight": False, "hotel": False})

    # 提取有效 ID 列表，用于 Prompt 强校验
    valid_flight_ids = [f['id'] for f in options.get('flights', [])]
    valid_hotel_ids = [h['id'] for h in options.get('hotels', [])]

    prompt = f"""
    用户正在选择预订资源。
    用户输入: "{last_msg}"
    当前预订状态: {json.dumps(current_status)}
    
    **有效资源 ID 列表 (必须严格匹配)**:
    - 有效机票 ID: {valid_flight_ids}
    - 有效酒店 ID: {valid_hotel_ids}
    
    任务：
    1. 提取用户意图中的机票 ID 和 酒店 ID。
    2. **校验有效性**：用户输入的 ID 必须在上述有效列表中。如果不在，标记为 invalid。**严禁自动修正或猜测 ID**。
    3. **处理逻辑 (独立操作)**：
       - 识别用户想要操作的项目（Select 或 Skip）。
       - **无需强制顺序**：用户可以先选酒店，也可以先选机票。
       - **冲突处理**：如果用户同时选择了机票和酒店（例如 "F1 H1"），请优先处理 **机票**，并在 reply 中说明“先为您锁定机票，稍后处理酒店”。
       - **状态检查**：如果用户尝试选择已完成（True）的项目，提示已完成。
    
    输出 JSON: 
    {{ 
        "action_item": "flight" or "hotel" or null,
        "action_type": "select" or "skip" or "invalid" or "error", 
        "selected_id": "...", // 仅当 valid 时返回 ID
        "item_info": {{ "id": "...", "price_text": "..." }} or null,
        "reply": "..." // 针对有效选择，请回复“正在为您锁定 [项目]...”
    }}
    """

    response = await json_llm.ainvoke([HumanMessage(content=prompt)])
    decision = json.loads(response.content)

    action_item = decision.get("action_item")
    action_type = decision.get("action_type")
    selected_id = decision.get("selected_id")
    reply = decision.get("reply", "请明确您的选择。")

    # 1. 处理错误或无效 ID
    if action_type in ["invalid", "error"] or not action_item:
        return {
            "messages": [AIMessage(content=reply)]
        }

    # 2. 处理“跳过”逻辑
    if action_type == "skip":
        new_status = current_status.copy()
        new_status[action_item] = True  # 标记为已完成

        # 检查是否还有剩下的
        msg = f"好的，为您跳过{action_item}。"
        if not new_status["flight"]:
            msg += " 接下来，请选择机票。"
        elif not new_status["hotel"]:
            msg += " 接下来，请选择酒店。"
        else:
            msg += " 所有项目已处理完毕，正在生成总结..."

        return {
            "booking_status": new_status,
            "step": "selecting",
            "messages": [AIMessage(content=msg)]
        }

    # 3. 处理“锁定 (select)”逻辑
    if action_type == "select" and selected_id:
        lock_logs = []
        order_id = None

        print(f"   -> Locking {action_item} {selected_id}...")

        try:
            if action_item == "flight":
                lock_res = await lock_flight.ainvoke({
                    "flight_number": selected_id,
                    "date": state.get("dates", "unknown")
                })
            else:
                lock_res = await lock_hotel.ainvoke({
                    "hotel_name": selected_id,
                    "check_in": state.get("dates", "unknown")
                })
            order_id = str(lock_res).strip()
            lock_logs.append(
                f"{action_item} {selected_id} 锁定成功 (订单号: {order_id})")
        except Exception as e:
            print(f"❌ Locking failed: {e}")
            return {
                "messages": [AIMessage(content=f"{selected_id} 锁定失败: {e}。请重试。")]
            }

        # 构建待支付信息 (安全获取 price_text)
        item_info = decision.get("item_info") or {}
        price = item_info.get("price_text", "价格待定")

        pending_info = {
            "type": action_item,      # 记录当前待支付的是 flight 还是 hotel
            "info": decision.get("item_info"),
            "order_id": order_id,
            "price": price
        }

        # 更新回复文案，强调锁定和尽快支付
        reply_msg = f"{reply}\n\n" + "\n".join(lock_logs) + \
            f"\n\n**资源已锁定，请尽快支付！**\n💰 待支付金额：{price}\n(请回复“确认支付”)"

        # 进入支付确认状态
        return {
            "pending_selection": pending_info,
            "step": "wait_payment",
            "messages": [AIMessage(content=reply_msg)]
        }

    return {"messages": [AIMessage(content="操作无法识别，请重试。")]}


# 3.5.1 处理支付并确认订单 (Confirming) - 支持循环检测

async def process_payment_node(state: TravelState):
    print("💳 [Node] Processing Payment & Confirming Orders...")

    pending = state.get("pending_selection", {})
    item_type = pending.get("type")  # flight / hotel
    order_id = pending.get("order_id")

    current_status = state.get(
        "booking_status", {"flight": False, "hotel": False}).copy()

    # 保存已预订的结果，用于最终总结
    booking_results = state.get("booking_results", {}).copy()

    # 1. 确认订单
    confirm_logs = []
    if order_id and item_type:
        print(f"   -> Confirming {item_type} Order {order_id}...")
        try:
            if item_type == "flight":
                await confirm_flight.ainvoke({"order_id": order_id})
            else:
                await confirm_hotel.ainvoke({"order_id": order_id})

            confirm_logs.append(f"✅ {item_type} 订单 {order_id} 支付成功并已出票！")
            current_status[item_type] = True  # 标记该项已完成
            booking_results[item_type] = pending.get("info")  # 保存详情

        except Exception as e:
            confirm_logs.append(f"❌ {item_type} 订单确认失败: {e}")
            # 失败了不更新状态，用户需要重试或重新选择

    # 2. 检查是否全部完成
    is_flight_done = current_status.get("flight")
    is_hotel_done = current_status.get("hotel")

    if is_flight_done and is_hotel_done:
        # 全部完成 -> Finish
        plans = state.get("generated_plans", [])
        chosen_idx = state.get("chosen_plan_index", 0)
        chosen_plan = plans[chosen_idx] if plans and chosen_idx < len(
            plans) else {"name": "自选行程", "details": ""}

        flight_info = booking_results.get("flight", {})
        hotel_info = booking_results.get("hotel", {})

        summary = f"""
        {' '.join(confirm_logs)}
        
        🎉 **所有预订已完成** 🎉
        
        📍 **行程方案**: {chosen_plan['name']}
        ✈️ **机票**: {flight_info.get('carrier')} {flight_info.get('time')} ({flight_info.get('price')})
        🏨 **酒店**: {hotel_info.get('name')} ({hotel_info.get('price')})
        
        祝您旅途愉快！
        """
        return {
            "booking_status": current_status,
            "booking_results": booking_results,
            "pending_selection": None,  # 清空待支付
            "step": "finish",
            "messages": [AIMessage(content=summary)]
        }

    else:
        # 还有未完成项 -> 回到 Selecting
        missing = []
        if not is_flight_done:
            missing.append("机票")
        elif not is_hotel_done:
            missing.append("酒店")  # else if 保证顺序

        msg = f"{' '.join(confirm_logs)}\n\n接下来，请继续选择{'、'.join(missing)}。"

        return {
            "booking_status": current_status,
            "booking_results": booking_results,
            "pending_selection": None,
            "step": "selecting",
            "messages": [AIMessage(content=msg)]
        }


# =============================================================================
# 3.6 新增: 专门的天气查询节点 (独立)
# =============================================================================


async def check_weather_node(state: TravelState):
    """
    专门负责查询天气的节点。
    智能分析用户意图中的地点，结合上下文进行查询。
    """
    print("🌤️ [Node] Checking Weather...")
    last_msg = state["messages"][-1].content
    context_dest = state.get("destination")

    # 智能提取地点 Prompt
    extract_loc_prompt = f"""
    用户正在请求天气查询。
    用户输入: "{last_msg}"
    当前上下文目的地: "{context_dest or '无'}"
    
    任务:
    1. 优先从用户输入中提取地点 (如 "查询东京的天气" -> "东京")。
    2. 若用户未提具体地点 (如 "那边天气怎么样"), 使用上下文目的地。
    3. 若都无，返回 null。
    
    输出 JSON: {{ "location": "..." or null }}
    """

    try:
        res = await json_llm.ainvoke([HumanMessage(content=extract_loc_prompt)])
        target_location = json.loads(res.content).get("location")
    except Exception as e:
        print(f"Weather Location Extract Error: {e}")
        target_location = context_dest

    if not target_location or target_location == "无":
        return {"messages": [AIMessage(content="请问您想查询哪个城市的天气？")]}

    print(f"   -> Calling tool get_weather for: {target_location}")
    try:
        # 调用天气工具
        weather_result = await get_weather.ainvoke({"location": target_location})
        return {"messages": [AIMessage(content=f"【{target_location}】天气实况:\n{weather_result}")]}
    except Exception as e:
        return {"messages": [AIMessage(content=f"查询 {target_location} 天气时暂时无法获取数据: {str(e)}")]}


# 3.7 侧轨 (修改版：针对当前 State 进行 Context-Aware 的引导)


async def side_chat_node(state: TravelState):
    """
    Side Chat: 处理攻略查询、闲聊。
    现在支持根据 state["step"] 进行上下文引导。
    """
    print("💬 [Node] Side Chat (Guides/Chat)...")
    last_msg = state["messages"][-1].content
    context_dest = state.get("destination")

    # 1. 攻略/指南/玩法
    if any(k in last_msg for k in ["攻略", "指南", "玩", "吃", "景点", "推荐"]):
        print(f"   -> Guide Request: {last_msg}")
        try:
            query = f"{context_dest or ''} {last_msg}"
            guides = await search_travel_guides.ainvoke({"query": query})
            return {"messages": [AIMessage(content=f"为您找到相关攻略信息：\n{guides}")]}
        except Exception as e:
            return {"messages": [AIMessage(content="抱歉，攻略查询暂时不可用。")]}

    # 2. 其他闲聊 (增强：结合当前步骤进行引导)
    current_step = state.get("step", "collect")

    guidance_map = {
        "collect": "请礼貌地引导用户继续提供旅行的目的地、出发地或日期，以便开始规划。",
        "plan": "告诉用户正在努力生成方案，请稍等。",
        "review": "请引导用户对刚才生成的方案进行选择（如：您更倾向于哪个方案？），或者提出修改意见。",
        "searching": "系统正在搜索资源，请让用户稍安勿躁。",
        "selecting": "请引导用户完成机票和酒店的具体选择（如：您决定预订哪趟航班？），或者回复“跳过”。",
        "wait_payment": "请提醒用户当前的订单待支付，需要回复“确认支付”来完成预订。",
        "finish": "行程已规划完毕。可以陪用户闲聊，或者问用户是否想要规划一次新的旅行（如果是，引导其说出新目的地）。"
    }

    advice = guidance_map.get(current_step, "请引导用户回到旅行规划的主题。")

    res = await llm.ainvoke([
        SystemMessage(
            content=f"你是一个风趣幽默的旅行助手。用户发来了闲聊内容：'{last_msg}'。\n请先礼貌或幽默地回应闲聊，然后**必须**根据当前流程状态进行引导。\n\n当前引导目标：{advice}"),
        HumanMessage(content=last_msg)
    ])

    return {"messages": [res]}


# 3.8 智能修改


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

# 注册节点
workflow.add_node("intent_router", intent_router_node)
workflow.add_node("collect", collect_requirements_node)
workflow.add_node("plan", generate_plans_node)
workflow.add_node("review", review_plan_node)
workflow.add_node("search_realtime", search_realtime_node)
workflow.add_node("execute_select", execute_selection_node)  # 负责计算 + 锁单
workflow.add_node("process_payment", process_payment_node)  # 负责支付 + 确认
workflow.add_node("side_chat", side_chat_node)
workflow.add_node("check_weather", check_weather_node)  # 新增节点
workflow.add_node("modify", modify_req_node)


workflow.add_edge(START, "intent_router")

# 路由逻辑


def route_next_step(state: TravelState):
    decision = state.get("router_decision", "continue")
    step = state.get("step", "collect")

    if decision == "modify":
        return "modify"
    if decision == "side_chat":
        return "side_chat"
    if decision == "check_weather":  # 新增路由分支
        return "check_weather"

    # 正常流程流转
    if step == "wait_payment" and decision == "continue":
        # 如果在支付阶段，且用户说"好的/确认"，则进入支付处理
        return "process_payment"

    # 防止 step 为 finish 时返回 "finish" 导致崩溃
    # 注意：下面的 conditional edges 必须包含这里返回的所有可能值
    return step


workflow.add_conditional_edges(
    "intent_router",
    route_next_step,
    {
        "modify": "modify",
        "side_chat": "side_chat",
        "check_weather": "check_weather",
        "collect": "collect",
        "plan": "plan",
        "review": "review",
        "searching": "search_realtime",
        "selecting": "execute_select",
        "wait_payment": "intent_router",  # 循环等待确认
        "process_payment": "process_payment",
        "finish": "side_chat"  # 修复崩溃的关键：当状态为 finish 时，后续 continue 操作流转到 side_chat
    }
)


# 新增：收集完成后自动流转到 Plan 节点的逻辑
def route_after_collect(state: TravelState):
    if state.get("step") == "plan":
        return "plan"
    return END

# 新增：Review 选定方案后，自动流转到 Search Realtime 节点


def route_after_review(state: TravelState):
    if state.get("step") == "searching":
        return "searching"
    return END

# 新增：支付后的流转逻辑 (循环检测)


def route_after_payment(state: TravelState):
    step = state.get("step")
    if step == "finish":
        return END  # 结束本次流程，等待用户新输入（被Router转去side_chat）
    elif step == "selecting":
        return END  # 结束本次Turn，等待用户输入（被Router转去execute_select）
    return END


# 结束边
workflow.add_edge("side_chat", END)
workflow.add_edge("check_weather", END)
# workflow.add_edge("collect", END)  <-- 已删除，改为下方条件边
workflow.add_conditional_edges(
    "collect", route_after_collect, {"plan": "plan", END: END})

# workflow.add_edge("review", END) <-- 已删除，改为下方条件边 (修复您的流程中断问题)
workflow.add_conditional_edges(
    "review", route_after_review, {"searching": "search_realtime", END: END})

workflow.add_edge("search_realtime", END)
workflow.add_edge("execute_select", END)  # 选完后暂停，等用户确认

# process_payment 需要条件跳转，因为可能还没完
workflow.add_conditional_edges(
    "process_payment", route_after_payment, {END: END})

workflow.add_conditional_edges("modify", route_after_modify, {
                               "plan": "plan", END: END})
workflow.add_edge("plan", END)

memory = MemorySaver()
travel_agent = workflow.compile(
    checkpointer=memory,
    interrupt_before=[]
)
