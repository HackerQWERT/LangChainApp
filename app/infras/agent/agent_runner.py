import asyncio
from langchain_core.messages import HumanMessage
# 导入上面定义的 graph app
from .travel_agent import graph_app


async def run_chat_stream(user_input: str, user_id: str = "default_user"):
    """
    执行 Agent 并流式输出回复
    """
    print(f"\n🔵 用户({user_id}): {user_input}")
    print("🟢 Agent: ", end="", flush=True)

    inputs = {
        "messages": [HumanMessage(content=user_input)],
        "user_id": user_id
    }

    # --- 核心流式逻辑 ---
    # version="v2" 是 LangChain 标准化的流式事件 API
    async for event in graph_app.astream_events(inputs, version="v2"):
        kind = event["event"]

        # 1. 捕获 LLM 的文本流 (Token)
        if kind == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content:
                # 实时打印到控制台，或者这里通过 WebSocket 发给前端
                print(content, end="", flush=True)

        # 2. (可选) 捕获工具调用状态，用于前端展示 "正在搜索..." UI
        elif kind == "on_tool_start":
            print(
                f"\n   ⚙️  [系统调用工具]: {event['name']} ... ", end="", flush=True)

        elif kind == "on_tool_end":
            print("完成。", end="\n🟢 Agent: ", flush=True)

    print("\n--------------------------------------------------")


# --- 模拟运行 ---
if __name__ == "__main__":

    async def main():
        # 场景 1: 假设用户没有订票 (你的 DB Tools 返回空)
        print(">>> 场景 1: 新用户交互")
        await run_chat_stream("我想去纽约玩几天，帮我看看机票")

        # 模拟用户确认预订 (这里只是对话演示，真实情况会调用 book_flight tool)
        await run_chat_stream("好的，帮我订一张去纽约的票")

        # 场景 2: 假设用户已经订票了 (你可以手动去数据库插一条数据，或者修改 mock)
        # 此时 Agent 应该直接进入 Planner 模式
        print("\n>>> 场景 2: 已订票用户交互 (假设上一轮已经订票成功)")
        await run_chat_stream("我接下来该怎么玩？帮我规划一下")

    asyncio.run(main())
