from app.infras.agent import graph_app as app
from langchain_core.messages import HumanMessage


async def run_interactive():
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
        snapshot = app.get_state(config)
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
                async for event in app.astream(None, config):
                    pass  # 节点内部有 print，这里仅驱动
                continue
            else:
                print("[系统]: ⚠️  模拟器限制：请先输入 'pay' 完成流程。")
                continue

        # 2. 正常对话输入
        user_input = input("\nUser: ")
        if user_input.lower() in ["q", "quit"]:
            break

        # 3. 发送给 Agent
        # print("Agent: ", end="", flush=True) # 节点内部已有详细 print，这里不再重复

        # 使用 astream 驱动图运行
        async for event in app.astream({"messages": [HumanMessage(content=user_input)]}, config):
            pass

        # 4. 打印当前状态快照 (Debug)
        snapshot = app.get_state(config)
        step = snapshot.values.get('step')
        dest = snapshot.values.get('destination')
        # 如果最后一条消息是 Agent 发的，且没在节点里打印（防止漏打），可以在这里补
        # 但目前的节点设计都包含了 print，所以这里只打 Debug 状态
        print(f"   🛠️ [State]: Step={step}, Dest={dest}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_interactive())
