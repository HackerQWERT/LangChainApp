import asyncio
import sys
import os

# 1. 确保项目根目录在 sys.path 中
sys.path.append(os.getcwd())

try:
    # 导入您的业务 Agent
    from app.infras.agent.travel_agent import travel_agent
    # 导入抽离的 Runner
    from app.infras.agent import run_chat_stream, run_monitor_stream
    # 导入性能监控
    from app.infras.evaluate.evaluate_agent import AgentPerformanceMonitor
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    print("请确保以下文件存在:")
    print("  - app/infras/agent/travel_agent.py")
    print("  - app/infras/agent/__init__.py")
    exit(1)


async def main():
    print("🚀 启动交互式测试终端 (按 'q' 或 'exit' 退出)")
    print("   输入 'debug' 切换调试模式")
    print("--------------------------------------------------")

    # 您可以在这里修改 user_id 来模拟不同用户
    user_id = "interactive_tester_001"
    verbose_mode = False  # 调试模式开关

    while True:
        try:
            # 1. 获取用户输入
            mode_indicator = " [DEBUG]" if verbose_mode else ""
            user_input = input(
                f"\n👉 请输入{mode_indicator} (User: {user_id}): ").strip()

            if not user_input:
                continue

            if user_input.lower() in ["q", "exit", "quit"]:
                print("👋 退出测试。")
                break

            if user_input.lower() == "clear":
                print("\n" * 100)
                continue

            if user_input.lower() == "debug":
                verbose_mode = not verbose_mode
                status = "开启" if verbose_mode else "关闭"
                print(f"🔧 调试模式已{status}")
                continue

            # 2. 调用 Agent 处理
            # 使用 run_monitor_stream 来查看详细的子链 (Sub-chains) 树状结构
            # await run_monitor_stream(travel_agent, user_input, user_id, verbose=verbose_mode)
            await run_chat_stream(travel_agent, user_input, user_id)

        except KeyboardInterrupt:
            print("\n👋 用户强制退出。")
            break
        except Exception as e:
            print(f"❌ 未知错误: {e}")

if __name__ == "__main__":
    if sys.platform == "win32":
        # Windows下解决 asyncio 事件循环问题
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
