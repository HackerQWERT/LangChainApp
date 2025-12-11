import asyncio
import os
import sys
from langchain_core.messages import HumanMessage

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


async def run_interactive():
    # 注意：这里根据你的实际目录结构可能需要调整 import
    # 假设你的 production_agent.py 在 app.infras.agent.travel_agent
    from app.infras.agent.travel_agent import graph_app

    # 允许用户自定义 ID，方便测试记忆功能
    thread_id = input("请输入模拟 User ID (回车默认 'user_001'): ") or "user_001"
    config = {"configurable": {"thread_id": thread_id}}

    print(f"\n========== 开始交互式对话 (ID: {thread_id}) ==========")
    print("指令说明:")
    print(" - 输入 'q' 或 'quit' 退出")
    print(" - 当系统暂停等待支付时，输入 'pay' 模拟支付回调")
    print("====================================================\n")

    while True:
        # 1. 检查是否处于中断状态 (Wait Payment)
        snapshot = graph_app.get_state(config)
        next_steps = snapshot.next if hasattr(snapshot, 'next') else []

        if next_steps and "wait_payment" in next_steps:
            print("\n[系统]: ⏸️  流程已在支付节点挂起 (Interrupt)。")
            print("   (模拟场景：用户正在收银台付款...)")
            user_input = input("User (输入 'pay' 确认支付, 或 'q' 退出): ")

            if user_input.lower() in ["q", "quit"]:
                break

            if user_input.lower() == "pay":
                print("\n[系统]: 收到支付回调，恢复执行...")
                # 恢复执行：传入 None 继续
                async for event in graph_app.astream(None, config):
                    _print_event_message(event)
                continue
            else:
                print("[系统]: ⚠️  模拟器限制：请先输入 'pay' 完成流程。")
                continue

        # 2. 正常对话输入
        user_input = input("\nUser: ")
        if user_input.lower() in ["q", "quit"]:
            break

        # 3. 发送给 Agent
        # 这里移除了 pass，改为解析并打印 event
        async for event in graph_app.astream({"messages": [HumanMessage(content=user_input)]}, config):
            _print_event_message(event)

        # 4. 打印当前状态快照 (Debug)
        snapshot = graph_app.get_state(config)
        step = snapshot.values.get('step')
        dest = snapshot.values.get('destination')
        print(f"   🛠️ [State]: Step={step}, Dest={dest}")


def _print_event_message(event):
    """辅助函数：从 LangGraph 事件中提取并打印 AI 回复"""
    for node_name, values in event.items():
        # values 是节点返回的字典，通常包含 'messages'
        if "messages" in values and values["messages"]:
            last_msg = values["messages"][-1]
            if hasattr(last_msg, "content") and last_msg.content:
                # 打印 AI 的回复内容
                print(f"\nAgent: {last_msg.content}")


if __name__ == "__main__":
    try:
        asyncio.run(run_interactive())
    except KeyboardInterrupt:
        print("\n\n程序已退出。")
