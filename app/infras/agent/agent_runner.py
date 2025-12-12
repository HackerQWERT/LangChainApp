import asyncio
from langchain_core.messages import HumanMessage


async def run_chat_stream(agent_graph, user_input: str, user_id: str = "default_user"):
    """
    通用的 Agent 流式运行器。
    负责将 Agent 的思考过程和结果漂亮地打印到控制台。

    Args:
        agent_graph: 编译好的 LangGraph 对象
        user_input: 用户输入的文本
        user_id: 线程 ID，用于记忆功能
    """
    print(f"\n🔵 用户({user_id}): {user_input}")
    print("🟢 Agent: ", end="", flush=True)

    # 构造输入
    inputs = {
        "messages": [HumanMessage(content=user_input)],
        # user_id 不需要传入 state，而是作为 thread_id 传入 config
    }

    config = {"configurable": {"thread_id": user_id}}

    try:
        # 使用 astream_events v2 API 获取细粒度的流式事件
        async for event in agent_graph.astream_events(inputs, version="v2", config=config):
            kind = event["event"]

            # 1. 捕获 LLM 的文本流 (on_chat_model_stream)
            # 这是 LLM 生成回复的过程
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if hasattr(chunk, "content") and chunk.content:
                    print(chunk.content, end="", flush=True)

            # 2. 捕获工具调用开始 (on_tool_start)
            # 用于显示系统正在做什么，增加交互感
            elif kind == "on_tool_start":
                print(
                    f"\n   ⚙️  [系统调用工具]: {event['name']} ... ", end="", flush=True)

            # 3. 捕获工具调用结束 (on_tool_end)
            elif kind == "on_tool_end":
                print("完成。", end="\n🟢 Agent: ", flush=True)

    except Exception as e:
        print(f"\n❌ 运行过程中发生错误: {e}")

    print("\n" + "-" * 60)
