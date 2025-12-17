from langchain.callbacks.base import BaseCallbackHandler
from typing import Any, Dict, List
import time


class AgentPerformanceMonitor(BaseCallbackHandler):
    def __init__(self):
        self.start_time = 0
        self.step_count = 0

    # 1. 监听 Agent 启动
    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any) -> None:
        self.start_time = time.time()
        self.step_count = 0
        print(">>> Agent 开始运行")

    # 2. 监听工具调用 (最关键的一步)
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs: Any) -> None:
        print(f"    [监控] 正在调用工具: {serialized.get('name')} | 参数: {input_str}")

    # 3. 监听工具结束
    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        self.step_count += 1
        print(f"    [监控] 工具调用完成。当前步数: {self.step_count}")

    # 4. 监听 Agent 结束
    def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> None:
        duration = time.time() - self.start_time
        print(f">>> Agent 运行结束。总耗时: {duration:.2f}s | 总步数: {self.step_count}")
        # 这里可以将 metrics 发送到你的数据库或 Datadog

# 使用方式
# agent.invoke(input_data, config={"callbacks": [AgentPerformanceMonitor()]})
