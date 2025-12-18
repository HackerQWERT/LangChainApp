import os
import re
import operator
import json
import asyncio
from datetime import datetime
from typing import Annotated, List, Literal, Optional, Dict, Any
from typing_extensions import TypedDict
from dotenv import load_dotenv

from langchain_openai import AzureChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage, AIMessage
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

# --- 规则引擎 ---
from app.infras.agent.rule import evaluate_state, ActionType


# --- 1. 导入真实工具 ---
try:
    from app.infras.func import (
        get_current_time,
        lookup_airport_code,
        search_flights,
        search_hotels,
        search_travel_guides,
        lock_flight,
        lock_hotel,
        confirm_flight,
        confirm_hotel,
        get_weather
    )
except ImportError:
    raise ImportError("请确保 airport_tools.py 模块存在且包含所有必要的工具函数。")

# --- 0. 配置 ---
load_dotenv()
llm = AzureChatOpenAI(
    azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    temperature=0.5,
)

# --- 1. Schema 定义 ---


class RouterOutput(BaseModel):
    """意图路由决策"""
    decision: Literal["update_info", "side_chat", "check_weather", "continue", "confirm_plan"] = Field(
        ..., description="confirm_plan: 当且仅当用户明确选择了某个旅行方案时"
    )
    chosen_index: Optional[int] = Field(
        None, description="如果decision是confirm_plan，这里必须提取索引(0-2)，否则为None")
    reason: str = Field(..., description="理由")


class CollectOutput(BaseModel):
    destination: Optional[str]
    origin: Optional[str]
    dates: Optional[str]
    reply: str


class PlanDetail(BaseModel):
    id: int
    name: str
    price_estimate: str
    details: str


class PlanGenOutput(BaseModel):
    plans: List[PlanDetail]
    reply_text: str


class SelectionAction(BaseModel):
    action_item: Optional[Literal["flight", "hotel"]]
    action_type: Literal["select", "skip", "invalid"]
    selected_id: Optional[str]
    # item_info removed to avoid OpenAI Structured Output schema validation error (Dict[str, Any] is not supported in strict mode)
    reply: str


class GuideOutput(BaseModel):
    guidance: str


class WeatherQuery(BaseModel):
    location: str
    date: Optional[str] = Field(None, description="YYYY-MM-DD format")

# --- 2. State 定义 ---


class TravelState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]

    step: Literal[
        "collect",          # 收集信息
        "plan",             # 规划生成
        "choose_plan",      # 选择方案
        "search_flight",    # 搜索机票
        "select_flight",    # 选择机票
        "pay_flight",       # 支付机票
        "search_hotel",     # 搜索酒店
        "select_hotel",     # 选择酒店
        "pay_hotel",        # 支付酒店
        "summary",          # 总结
        "finish"            # 结束
    ]

    destination: Optional[str]
    origin: Optional[str]
    dates: Optional[str]

    generated_plans: Optional[List[Dict]]
    chosen_plan_index: Optional[int]

    realtime_options: Optional[Dict]
    pending_selection: Optional[Dict]
    booking_status: Optional[Dict]
    booking_results: Optional[Dict]

    router_decision: str

    # --- 安全相关字段 ---
    current_actor: Optional[str]      # "sentinel" | node_name
    action_type: Optional[str]        # "pass" | "block"
    risk_reason: Optional[str]        # 拦截原因

# --- 3. 核心节点 ---


async def intent_router_node(state: TravelState):
    if not state.get("messages"):
        return {"router_decision": "continue"}

    current_step = state.get("step", "collect")

    context_info = ""
    if current_step == "choose_plan":
        plans = state.get("generated_plans", [])
        plan_names = [f"{i}: {p['name']}" for i, p in enumerate(plans)]
        context_info = f"用户需从方案中选择: {plan_names}。"
    elif current_step in ["pay_flight", "pay_hotel"]:
        context_info = "CRITICAL: 支付确认阶段。等待用户输入'确认'或'支付'。"
    elif current_step in ["select_flight", "select_hotel"]:
        context_info = "用户正在选择具体的机票或酒店资源 (如 F1, H1)。这属于 continue 行为，不是 confirm_plan。"

    system_prompt = f"""你是意图分类器。当前步骤: "{current_step}"。
上下文: {context_info}

决策逻辑：
1. **confirm_plan**: (仅在 choose_plan 阶段有效) 用户明确选择了旅行方案(如方案1、方案2)。如果当前步骤不是 choose_plan，绝对不要输出 confirm_plan。
2. **update_info**: 用户想修改核心信息(地点/时间)。
3. **check_weather**: 用户询问天气。
4. **side_chat**: 闲聊 或 无效输入。
5. **continue**: 用户正在配合当前步骤(如回答问题、选择机票(F1/F2)、确认支付)。
   - 注意: 如果当前是 select_flight/select_hotel 阶段，用户输入 F1, H1 等代表选择资源，属于 continue。

必须输出 decision 和 chosen_index (仅confirm_plan需要)。"""

    messages_to_send = [SystemMessage(
        content=system_prompt)] + list(state.get('messages', []))

    structured_llm = llm.with_structured_output(RouterOutput)
    try:
        res: RouterOutput = await structured_llm.ainvoke(messages_to_send)
        decision = res.decision
        chosen_idx = res.chosen_index
    except Exception:
        decision = "continue"
        chosen_idx = None

    print(f"🚦 [Router] Step={current_step} Decision={decision}")

    if decision == "confirm_plan" and chosen_idx is not None:
        return {
            "router_decision": decision,
            "chosen_plan_index": chosen_idx,
        }

    return {"router_decision": decision}


async def collect_requirements_node(state: TravelState):
    print("📋 [Node] Collecting Info...")

    # 1. 获取当前时间 (辅助日期计算)
    try:
        now_str = get_current_time.invoke({})
    except Exception:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    current_slots = {k: state.get(k)
                     for k in ["destination", "origin", "dates"]}

    # 2. 使用 SystemMessage 指导 LLM 理解对话上下文
    system_prompt = f"""你是一个旅行信息收集助手。你的任务是从用户的对话中提取旅行信息。

当前系统时间: {now_str}
已收集信息: {json.dumps(current_slots, ensure_ascii=False)}

**核心语义理解规则 (最重要)**:

1. **"从 X 到 Y" 句式**: X 是出发地 (origin), Y 是目的地 (destination)
2. **"去 X"**: X 是目的地 (destination)
3. **"从 X 出发"**: X 是出发地 (origin)
4. **上下文理解**: 
   - 如果之前问了"您的出发城市是哪里"，用户回答的城市是 origin
   - 如果之前问了"要去日本的哪个城市"，用户回答的城市是 destination
   - 不要把出发地和目的地搞混！

**字段更新规则**:
- destination: 用户要去的地方，必须是具体城市（国家名如"日本"不算）
- origin: 用户出发的地方，必须是具体城市
- dates: 必须转换为 YYYY-MM-DD 格式
- 如果某个字段已有正确值且用户没有明确要修改，返回 null 表示保留原值
- 如果用户只说了国家名，对应字段返回 null，在 reply 中追问具体城市

**回复规则**:
- 如果信息不完整，礼貌追问缺失信息
- 如果信息完整，确认并总结收集到的信息
"""

    # 构建消息列表：SystemMessage + 对话历史
    messages_to_send = [SystemMessage(content=system_prompt)]

    # 添加对话历史 (LangGraph 已经维护了完整的 messages)
    for msg in state.get('messages', []):
        messages_to_send.append(msg)

    structured_llm = llm.with_structured_output(CollectOutput)
    res = await structured_llm.ainvoke(messages_to_send)

    updates = {"messages": [AIMessage(content=res.reply)]}

    # 只在有明确新值时才更新（避免覆盖已有正确值）
    if res.destination:
        updates["destination"] = res.destination
    if res.origin:
        updates["origin"] = res.origin
    if res.dates:
        updates["dates"] = res.dates

    # 检查是否所有必要信息都已收集
    final_destination = res.destination or current_slots["destination"]
    final_origin = res.origin or current_slots["origin"]
    final_dates = res.dates or current_slots["dates"]

    print(
        f"   -> 收集结果: origin={final_origin}, destination={final_destination}, dates={final_dates}")

    if final_destination and final_origin and final_dates:
        updates["step"] = "plan"
    else:
        updates["step"] = "collect"
    return updates


async def generate_plans_node(state: TravelState):
    print("💡 [Node] Planning (Calling Real Guide Search)...")
    dest = state.get('destination')

    # 1. 真实调用：获取旅游攻略
    try:
        guides_res = await search_travel_guides.ainvoke({"query": f"{dest} 旅游攻略 必玩景点"})
    except Exception as e:
        guides_res = f"攻略搜索暂时不可用: {e}"

    # 2. 基于攻略生成方案
    system_prompt = f"""你是专业的旅行规划师。
目的地: {dest}。
参考攻略: {str(guides_res)[:800]}。

任务: 生成3个差异化的旅行方案（如经济、豪华、亲子）。"""

    messages_to_send = [SystemMessage(
        content=system_prompt)] + list(state.get('messages', []))
    structured_llm = llm.with_structured_output(PlanGenOutput)
    res = await structured_llm.ainvoke(messages_to_send)

    plans_data = [p.dict() for p in res.plans]
    pretty_msg = "\n\n" + res.reply_text + "\n" + \
        "\n".join(
            [f"方案 {i}: {p.name} ({p.price_estimate})" for i, p in enumerate(res.plans)])

    return {
        "generated_plans": plans_data,
        "step": "choose_plan",
        "messages": [AIMessage(content=pretty_msg)],
        "booking_status": {"flight": False, "hotel": False}
    }


async def search_flight_node(state: TravelState):
    print("🔍 [Node] Searching Flights...")

    origin_raw = state.get("origin", "Beijing")
    dest_raw = state.get("destination", "Shanghai")
    travel_date = state.get("dates", datetime.now().strftime("%Y-%m-%d"))

    # === 城市名 -> 机场代码转换 ===
    async def get_iata_code(city_name: str) -> str:
        if re.match(r"^[A-Z]{3}$", city_name):
            return city_name

        search_query = city_name
        if any('\u4e00' <= char <= '\u9fff' for char in city_name):
            print(
                f"   -> Detected Chinese in '{city_name}', translating to English...")
            try:
                trans_msg = await llm.ainvoke([HumanMessage(content=f"Please translate '{city_name}' to English city name. Return ONLY the name, no punctuation.")])
                search_query = trans_msg.content.strip()
                print(f"   -> Translated: {city_name} -> {search_query}")
            except Exception as e:
                print(f"   -> Translation failed: {e}")

        print(f"   -> Converting city '{search_query}' to IATA code...")
        try:
            res_str = await lookup_airport_code.ainvoke(search_query)
            match = re.search(r"\(([A-Z]{3})\)", str(res_str))
            if match:
                code = match.group(1)
                print(f"   -> Mapped '{city_name}' to '{code}'")
                return code
            else:
                print(
                    f"   -> Code conversion failed for '{search_query}', using original.")
                return city_name
        except Exception as e:
            print(f"   -> Error looking up code: {e}")
            return city_name

    origin_code, dest_code = await asyncio.gather(
        get_iata_code(origin_raw),
        get_iata_code(dest_raw)
    )

    print(
        f"   -> Calling Flight Search API: {origin_code} -> {dest_code} on {travel_date}")

    flight_res = await search_flights.ainvoke({
        "origin": origin_code,
        "destination": dest_code,
        "date": travel_date
    })

    try:
        raw_flights = json.loads(flight_res) if isinstance(
            flight_res, str) else flight_res
    except:
        raw_flights = [{"error": str(flight_res)}]

    msg = f"已为您查询到 {origin_code} -> {dest_code} 的机票：\n\n"
    if isinstance(raw_flights, list) and len(raw_flights) > 0 and "error" not in raw_flights[0]:
        for i, f in enumerate(raw_flights[:5]):
            airline = f.get('airline', '未知航司')
            fnum = f.get('flight_number', '未知航班号')
            dept = f.get('departure', '未知出发时间')
            arr = f.get('arrival', '未知到达时间')
            dur = f.get('duration', '未知时长')
            price = f.get('price', '未知价格')
            link = f.get('link')

            msg += f"### [F{i+1}] {airline}\n"
            msg += f"- **✈️ 航班**: {fnum}\n"
            msg += f"- **💰 价格**: {price}\n"
            msg += f"- **🛫 出发**: {dept}\n"
            msg += f"- **🛬 到达**: {arr}\n"
            msg += f"- **⏱️ 时长**: {dur}\n"
            if link:
                msg += f"- [🔗 预订链接]({link})\n"
            msg += "\n---\n"
    else:
        err_msg = raw_flights[0].get('error') if isinstance(
            raw_flights, list) else "No data"
        msg += f"未查询到有效航班 ({err_msg})。\n"

    msg += "\n请告诉我您要锁定哪个 **机票** (输入 F1, F2...)。"

    return {
        "realtime_options": {"flights": raw_flights},
        "step": "select_flight",
        "messages": [AIMessage(content=msg)]
    }


async def select_flight_node(state: TravelState):
    print("⚙️ [Node] Locking Flight...")
    options = state.get("realtime_options", {})

    valid_f = []
    if isinstance(options.get('flights'), list):
        valid_f = [f"[F{i+1}] {f.get('flight_number') or f.get('id')}"
                   for i, f in enumerate(options['flights']) if isinstance(f, dict)]

    system_prompt = f"""你是机票选择助手。
可选机票列表: {valid_f}

任务: 识别用户想选哪个机票。
1. 如果用户输入 "F1", "F2" 等编号，请根据列表提取对应的真实 ID (如 "UA 889") 作为 selected_id。
2. 输出 action_type: select/skip/invalid。"""

    messages_to_send = [SystemMessage(
        content=system_prompt)] + list(state.get('messages', []))
    structured_llm = llm.with_structured_output(SelectionAction)
    decision = await structured_llm.ainvoke(messages_to_send)

    if decision.action_type == "select":
        target_id = decision.selected_id
        order_id = "ERR"
        try:
            res = await lock_flight.ainvoke({
                "flight_number": target_id,
                "date": state.get("dates"),
                "from_airport": state.get("origin"),
                "to_airport": state.get("destination"),
                "passenger": "Default User",
                "user_id": "current_user"
            })
            order_id = res
        except Exception as e:
            return {"messages": [AIMessage(content=f"🔒 锁定失败: {str(e)} 请重试。")]}

        pending = {
            "type": "flight",
            "info": {"id": target_id},
            "order_id": order_id
        }
        return {
            "pending_selection": pending,
            "step": "pay_flight",
            "messages": [AIMessage(content=f"已锁定机票 (单号: {order_id})，请回复'确认'以支付。")]
        }

    elif decision.action_type == "skip":
        return {"step": "search_hotel", "messages": [AIMessage(content="已跳过机票预订，即将查询酒店。")]}

    return {"messages": [AIMessage(content="无法识别您的选择，请明确输入机票编号 (如 F1)。")]}


async def pay_flight_node(state: TravelState):
    print("💳 [Node] Paying Flight...")
    pending = state.get("pending_selection")
    if not pending or pending["type"] != "flight":
        return {"step": "search_hotel", "messages": [AIMessage("无待支付机票订单，进入酒店查询。")]}

    order_id = pending["order_id"]
    try:
        await confirm_flight.ainvoke({"order_id": order_id})
    except Exception as e:
        return {"messages": [AIMessage(f"支付确认失败: {e}")]}

    new_results = state.get("booking_results", {}).copy()
    # 保存 航班号 + 订单号
    flight_info = pending["info"].copy()
    flight_info["order_id"] = order_id
    new_results["flight"] = flight_info

    return {
        "booking_results": new_results,
        "pending_selection": None,
        "step": "search_hotel",
        "messages": [AIMessage(f"✅ 机票支付成功！接下来为您查询酒店。")]
    }


async def search_hotel_node(state: TravelState):
    print("🔍 [Node] Searching Hotels...")
    dest_raw = state.get("destination", "Shanghai")
    travel_date = state.get("dates", datetime.now().strftime("%Y-%m-%d"))

    print(f"   -> Calling Hotel Search API: {dest_raw} on {travel_date}")
    hotel_res = await search_hotels.ainvoke({
        "location": dest_raw,
        "check_in": travel_date,
        "check_out": "unknown"
    })

    try:
        raw_hotels = json.loads(hotel_res) if isinstance(
            hotel_res, str) else hotel_res
    except:
        raw_hotels = [{"error": str(hotel_res)}]

    msg = f"\n\n已为您查询到 {dest_raw} 的酒店：\n\n"
    if isinstance(raw_hotels, list) and len(raw_hotels) > 0 and "error" not in raw_hotels[0]:
        for i, h in enumerate(raw_hotels[:5]):
            hname = h.get('name') or h.get('id', 'N/A')
            price = h.get('price', 'N/A')
            rating = h.get('rating', 'N/A')
            reviews = h.get('reviews', 0)
            h_class = h.get('class', 'N/A')
            amenities = h.get('amenities', 'N/A')
            link = h.get('link')
            thumb = h.get('thumbnail')
            desc = h.get('description', '')

            msg += f"### [H{i+1}] {hname}\n"
            if thumb:
                msg += f"![{hname}]({thumb})\n"

            msg += f"- **💰 价格**: {price}\n"
            msg += f"- **⭐ 评分**: {rating} ({reviews} 条评价)\n"
            msg += f"- **🏨 等级**: {h_class}\n"
            if amenities and amenities != "N/A":
                msg += f"- **🛁 设施**: {amenities}\n"
            if desc:
                msg += f"> {desc[:100]}...\n"
            if link:
                msg += f"- [🔗 查看详情]({link})\n"
            msg += "\n---\n"
    else:
        msg += "未查询到结构化酒店信息。\n"

    msg += "\n请告诉我您要锁定哪个 **酒店** (输入 H1, H2...)。"

    return {
        "realtime_options": {"hotels": raw_hotels},
        "step": "select_hotel",
        "messages": [AIMessage(content=msg)]
    }


async def select_hotel_node(state: TravelState):
    print("⚙️ [Node] Locking Hotel...")
    options = state.get("realtime_options", {})

    valid_h = []
    if isinstance(options.get('hotels'), list):
        valid_h = [f"[H{i+1}] {h.get('name') or h.get('id')}"
                   for i, h in enumerate(options['hotels']) if isinstance(h, dict)]

    system_prompt = f"""你是酒店选择助手。
可选酒店列表: {valid_h}

任务: 识别用户想选哪个酒店。
1. 如果用户输入 "H1", "H2" 等编号，请根据列表提取对应的真实 ID (如 "Hilton") 作为 selected_id。
2. 输出 action_type: select/skip/invalid。"""

    messages_to_send = [SystemMessage(
        content=system_prompt)] + list(state.get('messages', []))
    structured_llm = llm.with_structured_output(SelectionAction)
    decision = await structured_llm.ainvoke(messages_to_send)

    if decision.action_type == "select":
        target_id = decision.selected_id
        order_id = "ERR"
        try:
            res = await lock_hotel.ainvoke({
                "hotel_name": target_id,
                "check_in": state.get("dates"),
                "location": state.get("destination"),
                "user_id": "current_user"
            })
            order_id = res
        except Exception as e:
            return {"messages": [AIMessage(content=f"🔒 锁定失败: {str(e)} 请重试。")]}

        pending = {
            "type": "hotel",
            "info": {"id": target_id},
            "order_id": order_id
        }
        return {
            "pending_selection": pending,
            "step": "pay_hotel",
            "messages": [AIMessage(content=f"已锁定酒店 (单号: {order_id})，请回复'确认'以支付。")]
        }

    elif decision.action_type == "skip":
        return {"step": "summary", "messages": [AIMessage(content="已跳过酒店预订。")]}

    return {"messages": [AIMessage(content="无法识别您的选择，请明确输入酒店编号 (如 H1)。")]}


async def pay_hotel_node(state: TravelState):
    print("💳 [Node] Paying Hotel...")
    pending = state.get("pending_selection")
    if not pending or pending["type"] != "hotel":
        return {"step": "summary", "messages": [AIMessage("无待支付酒店订单，生成行程单。")]}

    order_id = pending["order_id"]
    try:
        await confirm_hotel.ainvoke({"order_id": order_id})
    except Exception as e:
        return {"messages": [AIMessage(f"支付确认失败: {e}")]}

    new_results = state.get("booking_results", {}).copy()
    # 保存 酒店名 + 订单号
    hotel_info = pending["info"].copy()
    hotel_info["order_id"] = order_id
    new_results["hotel"] = hotel_info

    return {
        "booking_results": new_results,
        "pending_selection": None,
        "step": "summary",
        "messages": [AIMessage(f"✅ 酒店支付成功！")]
    }


async def generate_summary_node(state: TravelState):
    print("📝 [Node] Generating Summary...")

    # 1. 提取信息
    res = state.get("booking_results", {})

    f_info = res.get('flight', {})
    flight_desc = f"{f_info.get('id', '未预订')} (订单号: {f_info.get('order_id', 'N/A')})"

    h_info = res.get('hotel', {})
    hotel_desc = f"{h_info.get('id', '未预订')} (订单号: {h_info.get('order_id', 'N/A')})"

    plans = state.get("generated_plans", [])
    idx = state.get("chosen_plan_index")
    plan_details = "用户未选择特定方案"
    if plans and idx is not None and 0 <= idx < len(plans):
        p = plans[idx]
        plan_details = f"方案: {p.get('name')}\n预算: {p.get('price_estimate')}\n详情: {p.get('details')}"

    # 2. 生成总结
    system_prompt = f"""你是一名专业的旅行管家。请根据以下信息为用户生成一份最终的【旅行行程单】。

📍 行程概览:
- 目的地: {state.get('destination', '未知')}
- 出发日期: {state.get('dates', '待定')}

📦 已锁定资源:
- ✈️ 航班: {flight_desc}
- 🏨 酒店: {hotel_desc}

🗺️ 规划参考:
{plan_details}

要求:
1. 语气热情、专业。
2. 清晰列出已预订的航班和酒店，**务必包含订单号**以便用户核对。
3. 结合用户的规划参考，给出一两句游玩建议。
4. 使用 Markdown 格式排版。"""

    messages_to_send = [SystemMessage(
        content=system_prompt)] + list(state.get('messages', []))
    ai_msg = await llm.ainvoke(messages_to_send)
    ai_msg.content = "\n\n" + str(ai_msg.content)

    return {"step": "finish", "messages": [ai_msg]}


async def check_weather_node(state: TravelState):
    """【天气节点】 真实调用 get_weather"""
    print("☀️ [Node] Checking Weather (Real Tool)...")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. 提取城市名和日期
    system_prompt = f"""你是天气查询助手。当前时间: {now_str}

任务:
1. 提取城市名称，并转换为英文 (如 Beijing, Shanghai)。
2. 提取日期，并根据当前时间将相对日期 (如"明天", "下周五") 转换为 YYYY-MM-DD 格式。
   - 如果用户未提及日期，date 字段留空。"""

    messages_to_send = [SystemMessage(
        content=system_prompt)] + list(state.get('messages', []))
    structured = llm.with_structured_output(WeatherQuery)
    q = await structured.ainvoke(messages_to_send)

    loc = q.location or state.get("destination") or "Beijing"
    date_param = q.date

    # 2. 真实调用
    try:
        raw_report = await get_weather.ainvoke({"location": loc, "date": date_param})
    except Exception as e:
        raw_report = f"无法获取天气: {e}"

    # 3. 格式化输出
    format_system = f"""你是一名贴心的旅行助手。请将以下原始天气数据转换为用户友好的 Markdown 格式。

📍 地点: {loc}
📅 日期: {date_param if date_param else "近期预报"}
📝 原始数据: {raw_report}

要求:
1. 使用 Emoji 图标 (☀️, 🌧️, 🌡️ 等) 增强可读性。
2. 提取关键信息：天气状况、最高/最低温。
3. 给出一条简短的穿衣或出行建议。"""

    formatted_msg = await llm.ainvoke([SystemMessage(content=format_system)])

    return {"messages": [formatted_msg]}


async def side_chat_node(state: TravelState):
    print("💬 [Node] Side Chat (LLM)...")
    step = state.get("step", "unknown")

    system_prompt = f"""你是一个专业的旅行助手。当前状态: {step}

请根据用户输入进行回复：
1. 如果用户是在闲聊，请友好互动。
2. 如果用户有疑问，请解答。
3. 请保持回复简短自然。"""

    messages_to_send = [SystemMessage(
        content=system_prompt)] + list(state.get('messages', []))
    response = await llm.ainvoke(messages_to_send)
    return {"messages": [response]}


async def guide_node(state: TravelState):
    step = state.get("step", "collect")

    # 明确每个阶段的引导话术目标
    goals = {
        "collect": "引导用户补充完善 目的地/出发地/日期 信息。",
        "plan": "引导用户查看生成的方案。",
        "choose_plan": "引导用户从方案中做出选择 (例如输入 '方案1')。",
        "search_flight": "告知用户正在搜寻机票。",
        "select_flight": "引导用户从列表中选择机票 (例如输入 'F1')。",
        "pay_flight": "引导用户确认支付 (输入 '确认' 或 '支付')。",
        "search_hotel": "告知用户正在搜寻酒店。",
        "select_hotel": "引导用户从列表中选择酒店 (例如输入 'H1')。",
        "pay_hotel": "引导用户确认支付 (输入 '确认' 或 '支付')。",
        "summary": "询问用户是否满意或有其他需求。",
        "finish": "礼貌结束对话。"
    }

    current_goal = goals.get(step, "引导用户进行下一步操作。")

    system_prompt = f"""当前主流程步骤: {step}
引导目标: {current_goal}

任务: 生成一句简短、清晰的引导语 (20字以内)，明确告诉用户接下来该做什么。
不要重复之前的长篇大论，直接给行动指令。"""

    messages_to_send = [SystemMessage(
        content=system_prompt)] + list(state.get('messages', []))
    res = await llm.with_structured_output(GuideOutput).ainvoke(messages_to_send)
    return {"messages": [AIMessage(f"\n\n💁 {res.guidance}")]}


# --- 安全节点 ---


async def sentinel_node(state: TravelState) -> dict:
    """
    【哨兵节点】
    所有关键操作前的"看门人"，执行规则引擎评估。
    """
    current_step = state.get("step", "unknown")
    print(f"🛡️ [Sentinel] 正在扫描 Step: {current_step}...")

    # 调用规则引擎评估完整状态
    result = evaluate_state(dict(state))

    print(f"   => 评估结果: {result.action.value.upper()} | 原因: {result.reason}")

    return {
        "current_actor": "sentinel",
        "action_type": result.action.value,
        "risk_reason": result.reason
    }


async def block_node(state: TravelState) -> dict:
    """
    【拦截节点】
    处理被规则引擎拦截的操作。
    """
    reason = state.get("risk_reason", "操作被系统拦截")

    print(f"🛑 [Block] 操作被拦截: {reason}")

    block_msg = f"""
🛑 **操作已被拦截**

原因: {reason}

如有疑问，请联系客服或稍后重试。
"""

    return {
        "step": "collect",  # 回退到信息收集阶段
        "current_actor": "system",
        "messages": [AIMessage(content=block_msg)]
    }


# --- 4. 构建图与路由逻辑 ---

workflow = StateGraph(TravelState)

workflow.add_node("intent_router", intent_router_node)
workflow.add_node("collect", collect_requirements_node)
workflow.add_node("plan", generate_plans_node)

# New Nodes
workflow.add_node("search_flight", search_flight_node)
workflow.add_node("select_flight", select_flight_node)
workflow.add_node("pay_flight", pay_flight_node)
workflow.add_node("search_hotel", search_hotel_node)
workflow.add_node("select_hotel", select_hotel_node)
workflow.add_node("pay_hotel", pay_hotel_node)

workflow.add_node("summary", generate_summary_node)
workflow.add_node("check_weather", check_weather_node)
workflow.add_node("side_chat", side_chat_node)
workflow.add_node("guide", guide_node)

# --- 安全节点 ---
workflow.add_node("sentinel", sentinel_node)
workflow.add_node("block", block_node)

workflow.add_edge(START, "intent_router")

# 【核心路由逻辑 - 显式直连版】


def route_next_step(state: TravelState):
    decision = state.get("router_decision", "continue")
    step = state.get("step", "collect")

    print(f"🔄 [Route] step={step}, decision={decision}")

    # 1. 全局中断意图
    if decision == "confirm_plan":
        return "search_flight"  # Start flight search after plan confirmation
    if decision == "update_info":
        return "collect"
    if decision == "side_chat":
        return "side_chat"
    if decision == "check_weather":
        return "check_weather"

    # 2. 正常流程
    if step == "collect":
        return "collect"
    elif step == "plan":
        return "plan"
    elif step == "choose_plan":
        return "side_chat"

    # Flight Flow
    elif step == "search_flight":
        return "search_flight"
    elif step == "select_flight":
        return "select_flight"
    elif step == "pay_flight":
        return "sentinel"  # 支付前先经过哨兵检查

    # Hotel Flow
    elif step == "search_hotel":
        return "search_hotel"
    elif step == "select_hotel":
        return "select_hotel"
    elif step == "pay_hotel":
        return "sentinel"  # 支付前先经过哨兵检查

    elif step == "summary":
        return "side_chat"
    elif step == "finish":
        return "side_chat"

    return "side_chat"


def route_after_sentinel(state: TravelState):
    """哨兵节点后的路由逻辑"""
    action = state.get("action_type", "pass")
    step = state.get("step", "collect")

    print(f"🛡️ [Sentinel Route] action={action}, step={step}")

    if action == "block":
        return "block"
    # pass 或 review 都直接放行 (当前不启用人工审核)
    else:
        if step == "pay_flight":
            return "pay_flight"
        elif step == "pay_hotel":
            return "pay_hotel"
        return "guide"


# 【核心字典映射】
workflow.add_conditional_edges("intent_router", route_next_step, {
    "collect": "collect",
    "plan": "plan",
    "search_flight": "search_flight",
    "select_flight": "select_flight",
    "pay_flight": "pay_flight",
    "search_hotel": "search_hotel",
    "select_hotel": "select_hotel",
    "pay_hotel": "pay_hotel",
    "side_chat": "side_chat",
    "check_weather": "check_weather",
    "sentinel": "sentinel",
    "block": "block",
    "guide": "guide",
})

# 哨兵节点后的条件路由
workflow.add_conditional_edges("sentinel", route_after_sentinel, {
    "block": "block",
    "pay_flight": "pay_flight",
    "pay_hotel": "pay_hotel",
    "guide": "guide",
})

# 拦截节点后返回引导
workflow.add_edge("block", "guide")

# 后置连接逻辑
workflow.add_conditional_edges("collect", lambda s: "plan" if s.get(
    "step") == "plan" else END, {"plan": "plan", END: END})

workflow.add_edge("plan", "guide")

# Flight Flow Edges
workflow.add_edge("search_flight", END)
workflow.add_edge("select_flight", END)
workflow.add_conditional_edges("pay_flight", lambda s: "search_hotel" if s.get(
    "step") == "search_hotel" else "guide", {"search_hotel": "search_hotel", "guide": "guide"})

# Hotel Flow Edges
workflow.add_edge("search_hotel", END)
workflow.add_edge("select_hotel", END)
workflow.add_conditional_edges("pay_hotel", lambda s: "summary" if s.get(
    "step") == "summary" else "guide", {"summary": "summary", "guide": "guide"})

workflow.add_edge("check_weather", "guide")
workflow.add_edge("summary", END)
workflow.add_edge("side_chat", "guide")
workflow.add_edge("guide", END)

memory = MemorySaver()
travel_agent = workflow.compile(checkpointer=memory)
