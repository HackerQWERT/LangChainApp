from langchain_core.messages import HumanMessage
from app.infras.agent import graph_app
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))


async def run_demo():
    # 线程 ID (模拟用户 Session)
    config = {"configurable": {"thread_id": "user_vip_001"}}

    print("\n========== 开始对话 ==========\n")

    # 1. 用户提出模糊需求
    print("User: 我想去日本玩。")
    async for event in graph_app.astream({"messages": [HumanMessage(content="我想去日本玩")]}, config):
        pass  # 这里可以打印 event 查看过程

    # 获取最后回复
    snapshot = graph_app.get_state(config)
    print(f"Agent: {snapshot.values['messages'][-1].content}")
    print(
        f"[State Debug]: {snapshot.values.get('destination')}, Step: {snapshot.values.get('step')}")

    # 2. 补充信息
    print("\nUser: 从上海出发，下周五走，预算 1万左右。")
    async for event in graph_app.astream({"messages": [HumanMessage(content="从上海出发，下周五走，预算 1万左右")]}, config):
        pass

    snapshot = graph_app.get_state(config)
    print(f"Agent: {snapshot.values['messages'][-1].content}")
    # 此时 Step 应该变成了 'plan' 或 'review'

    # 3. 突然插入闲聊 (侧轨测试)
    print("\nUser: 日本最近冷吗？")
    async for event in graph_app.astream({"messages": [HumanMessage(content="日本最近冷吗？")]}, config):
        pass

    snapshot = graph_app.get_state(config)
    print(f"Agent (侧轨): {snapshot.values['messages'][-1].content}")
    # 此时 Step 应该保持不变，不会因为问了天气就丢失进度

    # 4. 改需求测试 (Smart Modify 测试)
    # 以前会重置，现在应该直接进入 plan
    print("\nUser: 还是改去泰国吧，预算加到 1.5万。")
    async for event in graph_app.astream({"messages": [HumanMessage(content="还是改去泰国吧，预算加到 1.5万。")]}, config):
        pass

    snapshot = graph_app.get_state(config)
    print(f"Agent: {snapshot.values['messages'][-1].content}")
    print(
        f"[State Debug]: Dest={snapshot.values.get('destination')}, Step={snapshot.values.get('step')}")

    # 5. 选择方案 (回到主流程)
    print("\nUser: 选方案 2。")
    async for event in graph_app.astream({"messages": [HumanMessage(content="选方案 2")]}, config):
        pass

    snapshot = graph_app.get_state(config)
    print(f"Agent: {snapshot.values['messages'][-1].content}")

    # 6. 触发 interrupt (wait_payment)
    print(f"\n[System]: 检测到中断。Next: {snapshot.next}")

    # 7. 模拟支付回调
    print("\n[System]: 支付回调收到，继续...")
    async for event in graph_app.astream(None, config):
        pass

    snapshot = graph_app.get_state(config)
    print(f"Agent (最终结果): {snapshot.values['messages'][-1].content}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_demo())
