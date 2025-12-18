from langchain.callbacks.base import BaseCallbackHandler
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage
from langchain_core.outputs import LLMResult
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import time
import json


class LogLevel(Enum):
    """日志级别"""
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3


@dataclass
class NodeExecution:
    """节点执行记录"""
    name: str
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    status: str = "running"
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    # 新增：节点输出内容
    output_message: Optional[str] = None  # 节点输出的消息内容
    output_data: Optional[Dict[str, Any]] = None  # 节点输出的结构化数据


@dataclass
class LLMExecution:
    """LLM 调用记录"""
    node_context: str  # 来自哪个节点
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: Optional[str] = None


@dataclass
class ToolExecution:
    """工具调用记录"""
    name: str
    node_context: str  # 来自哪个节点
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    input_preview: Optional[str] = None
    output_preview: Optional[str] = None
    status: str = "running"
    error: Optional[str] = None


@dataclass
class RouterDecision:
    """路由决策记录"""
    step: str
    decision: str
    reason: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class NodeOutput:
    """节点输出记录"""
    node_name: str
    timestamp: float
    message_content: Optional[str] = None  # AI 消息内容
    state_updates: Optional[Dict[str, Any]] = None  # 状态更新
    plans: Optional[List[Dict]] = None  # 生成的方案 (plan 节点)
    options: Optional[Dict[str, List]] = None  # 搜索结果选项 (flights/hotels)


@dataclass
class WorkflowTrace:
    """完整的工作流追踪"""
    session_id: str
    user_input: str
    start_time: float
    end_time: Optional[float] = None

    nodes: List[NodeExecution] = field(default_factory=list)
    llm_calls: List[LLMExecution] = field(default_factory=list)
    tool_calls: List[ToolExecution] = field(default_factory=list)
    router_decisions: List[RouterDecision] = field(default_factory=list)
    node_outputs: List[NodeOutput] = field(default_factory=list)  # 新增：节点输出列表

    final_response: Optional[str] = None
    status: str = "running"  # running, completed, error
    error: Optional[str] = None


class AgentPerformanceMonitor(BaseCallbackHandler):
    """
    LangGraph Agent 高级性能监控回调处理器。

    功能特性:
    =========
    1. 🔍 细粒度追踪: LLM 调用、工具执行、节点生命周期
    2. 🚦 路由决策监控: 捕获 Router 的 step/decision 变化
    3. 📊 详细统计报告: Token 消耗、耗时分析、调用链路
    4. 🎨 美化输出: 可自定义日志级别和格式
    5. ⚠️ 错误追踪: 完整的异常上下文记录
    6. 📤 数据导出: 支持 JSON 格式导出追踪数据

    使用示例:
    ========
    monitor = AgentPerformanceMonitor(
        log_level=LogLevel.INFO,
        show_tool_io=True,
        max_preview_length=200
    )
    result = await agent.ainvoke(inputs, config={"callbacks": [monitor]})
    monitor.print_summary()
    """

    def __init__(
        self,
        log_level: LogLevel = LogLevel.INFO,
        show_tool_io: bool = True,
        show_router_decisions: bool = True,
        max_preview_length: int = 150,
        session_id: Optional[str] = None,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ):
        """
        初始化监控器。

        Args:
            log_level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
            show_tool_io: 是否显示工具输入输出预览
            show_router_decisions: 是否显示路由决策
            max_preview_length: 预览文本的最大长度
            session_id: 会话 ID (用于追踪)
            on_event: 事件回调函数，用于外部系统集成
        """
        self.log_level = log_level
        self.show_tool_io = show_tool_io
        self.show_router_decisions = show_router_decisions
        self.max_preview_length = max_preview_length
        self.on_event = on_event

        # 追踪数据
        self.trace = WorkflowTrace(
            session_id=session_id or datetime.now().strftime("%Y%m%d_%H%M%S"),
            user_input="",
            start_time=0
        )

        # 运行时状态
        self._current_node: Optional[str] = None
        self._current_llm: Optional[LLMExecution] = None
        self._current_tool: Optional[ToolExecution] = None
        self._node_stack: List[str] = []  # 节点调用栈
        self._last_step: Optional[str] = None  # 上一次的 step 值

        # 统计累计
        self.total_tokens = {"prompt": 0, "completion": 0, "total": 0}

        # 需要忽略的内部节点名
        self._ignored_nodes = {
            "LangGraph", "RunnableSequence", "RunnableLambda",
            "ChannelWrite", "ChannelRead", "__start__", "__end__",
            "RunnableParallel", "RunnableAssign", "ChatPromptTemplate"
        }

        # 已知的 LangGraph 节点名 (用于从 tags 中识别)
        self._known_nodes = {
            "intent_router", "collect", "plan", "search_flight", "select_flight",
            "pay_flight", "search_hotel", "select_hotel", "pay_hotel",
            "summary", "check_weather", "side_chat", "guide"
        }

    def _log(self, level: LogLevel, message: str, indent: int = 0):
        """统一日志输出"""
        if level.value >= self.log_level.value:
            prefix = "   " * indent
            print(f"{prefix}{message}")

    def _emit_event(self, event_type: str, data: Dict[str, Any]):
        """发送事件到外部系统"""
        if self.on_event:
            self.on_event(event_type, data)

    def _truncate(self, text: str) -> str:
        """截断过长文本"""
        if len(text) > self.max_preview_length:
            return text[:self.max_preview_length] + "..."
        return text

    def _get_node_icon(self, node_name: str) -> str:
        """根据节点名称获取图标"""
        icons = {
            "collect": "📋",
            "router": "🚦",
            "plan": "📝",
            "search_flight": "✈️",
            "search_hotel": "🏨",
            "select_flight": "🎫",
            "select_hotel": "🛏️",
            "pay_flight": "💳",
            "pay_hotel": "💰",
            "check_weather": "🌤️",
            "summary": "📊",
            "side_chat": "💬",
            "guide": "🗺️",
        }
        return icons.get(node_name, "📍")

    # ===== Chain 生命周期 =====

    def on_chain_start(
        self, serialized: Optional[Dict[str, Any]], inputs: Dict[str, Any], **kwargs: Any
    ) -> Any:
        """当 Chain (或 Graph 节点) 开始运行时触发"""

        # 工作流开始
        if not self.trace.start_time:
            self.trace.start_time = time.time()
            # 尝试提取用户输入
            if "messages" in inputs and inputs["messages"]:
                first_msg = inputs["messages"][0]
                if hasattr(first_msg, "content"):
                    self.trace.user_input = first_msg.content
            self._log(LogLevel.INFO, f"\n🚀 [Monitor] Agent Workflow Started")
            self._emit_event("workflow_start", {"time": self.trace.start_time})

        # 多种方式提取节点名称 (LangGraph 兼容)
        name = None

        # 方式1: 从 kwargs 中获取 (LangGraph 常用)
        if "name" in kwargs:
            name = kwargs["name"]

        # 方式2: 从 tags 中获取 (LangGraph 节点可能放在 tags 里)
        if not name and "tags" in kwargs:
            tags = kwargs["tags"]
            for tag in tags:
                if tag.startswith("graph:step:"):
                    name = tag.replace("graph:step:", "")
                    break
                # LangGraph 节点名称通常是简单字符串
                if tag in self._known_nodes:
                    name = tag
                    break

        # 方式3: 从 serialized 中获取
        if not name and serialized:
            name = serialized.get("name")
            if not name:
                # 可能是 id 列表的最后一个元素
                id_val = serialized.get("id")
                if isinstance(id_val, list) and id_val:
                    name = id_val[-1]
                elif isinstance(id_val, str):
                    name = id_val

        if not name or name in self._ignored_nodes:
            return

        # 记录节点开始
        self._node_stack.append(name)
        self._current_node = name

        node_exec = NodeExecution(
            name=name,
            start_time=time.time(),
            metadata={"inputs_keys": list(
                inputs.keys()) if isinstance(inputs, dict) else []}
        )
        self.trace.nodes.append(node_exec)

        icon = self._get_node_icon(name)
        self._log(LogLevel.INFO, f"{icon} [Node] Entering: {name}", indent=0)
        self._emit_event(
            "node_start", {"name": name, "time": node_exec.start_time})

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> Any:
        """当 Chain 结束时触发"""
        # 从 kwargs 提取节点名称 (与 on_chain_start 保持一致)
        name = kwargs.get("name")
        if not name and "tags" in kwargs:
            tags = kwargs["tags"]
            for tag in tags:
                if tag.startswith("graph:step:"):
                    name = tag.replace("graph:step:", "")
                    break
                if tag in self._known_nodes:
                    name = tag
                    break

        # 如果找到了对应的节点名，更新记录并捕获输出
        if name and name in [n.name for n in self.trace.nodes]:
            for node in reversed(self.trace.nodes):
                if node.name == name and node.end_time is None:
                    node.end_time = time.time()
                    node.duration = node.end_time - node.start_time
                    node.status = "completed"

                    # 捕获节点输出
                    if isinstance(outputs, dict):
                        self._capture_node_output(name, outputs, node)

                    # 从栈中移除
                    if name in self._node_stack:
                        self._node_stack.remove(name)
                    break
        elif self._node_stack:
            # 回退逻辑: 按栈顺序处理
            node_name = self._node_stack.pop()
            for node in reversed(self.trace.nodes):
                if node.name == node_name and node.end_time is None:
                    node.end_time = time.time()
                    node.duration = node.end_time - node.start_time
                    node.status = "completed"

                    # 捕获节点输出
                    if isinstance(outputs, dict):
                        self._capture_node_output(node_name, outputs, node)
                    break

        # 检测路由决策 (从 outputs 中提取 step 和 decision)
        if self.show_router_decisions and isinstance(outputs, dict):
            self._detect_router_decision(outputs, name or "unknown")

        self._current_node = self._node_stack[-1] if self._node_stack else None

    def _capture_node_output(self, node_name: str, outputs: Dict[str, Any], node: NodeExecution):
        """捕获节点输出内容"""
        node_output = NodeOutput(
            node_name=node_name,
            timestamp=time.time()
        )

        # 提取消息内容
        if "messages" in outputs and outputs["messages"]:
            messages = outputs["messages"]
            # 获取最后一条 AI 消息
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    content = msg.content
                    node_output.message_content = content
                    node.output_message = self._truncate(
                        content) if content else None
                    break
                elif hasattr(msg, "content"):
                    content = msg.content
                    node_output.message_content = content
                    node.output_message = self._truncate(
                        content) if content else None
                    break

        # 提取方案 (plan 节点)
        if "generated_plans" in outputs:
            node_output.plans = outputs["generated_plans"]
            node.output_data = {"plans": outputs["generated_plans"]}

        # 提取搜索选项 (search_flight/search_hotel 节点)
        if "realtime_options" in outputs:
            options = outputs["realtime_options"]
            node_output.options = options
            node.output_data = {"options": options}

        # 提取状态更新
        state_keys = ["step", "destination",
                      "origin", "dates", "selected_plan_index"]
        state_updates = {k: outputs[k]
                         for k in state_keys if k in outputs and outputs[k]}
        if state_updates:
            node_output.state_updates = state_updates

        self.trace.node_outputs.append(node_output)

        # 打印节点输出摘要
        if node_output.message_content:
            preview = self._truncate(node_output.message_content)
            icon = self._get_node_icon(node_name)
            self._log(LogLevel.INFO, f"   💬 [Output] {preview}", indent=0)

    def on_chain_error(self, error: BaseException, **kwargs: Any) -> Any:
        """当 Chain 出错时触发"""
        error_msg = str(error)
        self._log(LogLevel.ERROR, f"❌ [Error] {error_msg}")

        # 更新当前节点状态
        if self.trace.nodes:
            self.trace.nodes[-1].status = "error"
            self.trace.nodes[-1].error = error_msg

        self.trace.status = "error"
        self.trace.error = error_msg
        self._emit_event(
            "error", {"error": error_msg, "node": self._current_node})

    def _detect_router_decision(self, outputs: Dict[str, Any], node_name: str):
        """检测并记录路由决策"""
        step = outputs.get("step")

        # 如果 step 发生变化，说明有路由决策
        if step and step != self._last_step:
            # 尝试从消息中提取决策信息
            decision = None
            reason = None

            if "messages" in outputs:
                for msg in reversed(outputs["messages"]):
                    if isinstance(msg, AIMessage) and hasattr(msg, "additional_kwargs"):
                        # 某些场景下，路由决策可能在 additional_kwargs 中
                        pass

            # 根据 step 变化推断决策
            decision_record = RouterDecision(
                step=step,
                decision=f"{self._last_step or 'start'} → {step}",
                reason=reason
            )
            self.trace.router_decisions.append(decision_record)

            self._log(
                LogLevel.INFO,
                f"🚦 [Router] Step={step} Decision={decision or 'transition'}",
                indent=0
            )
            self._emit_event("router_decision", {
                "from": self._last_step,
                "to": step,
                "reason": reason
            })

            self._last_step = step

    # ===== LLM 调用监控 =====

    def on_chat_model_start(
        self, serialized: Dict[str, Any], messages: List[List[BaseMessage]], **kwargs: Any
    ) -> Any:
        """当 Chat Model 开始生成时触发"""
        model_name = serialized.get(
            "id", ["unknown"])[-1] if serialized else "unknown"

        self._current_llm = LLMExecution(
            node_context=self._current_node or "unknown",
            start_time=time.time(),
            model=model_name
        )

        self._log(LogLevel.INFO, f"🤖 [LLM] Request Started...", indent=0)
        self._emit_event("llm_start", {
            "node": self._current_node,
            "model": model_name
        })

    def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> Any:
        """当普通 LLM 开始生成时触发"""
        self.on_chat_model_start(serialized, [], **kwargs)

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        """当 LLM 生成结束时触发"""
        if self._current_llm:
            self._current_llm.end_time = time.time()
            self._current_llm.duration = self._current_llm.end_time - self._current_llm.start_time

            # 提取 Token 使用情况
            if response.llm_output and "token_usage" in response.llm_output:
                usage = response.llm_output["token_usage"]
                self._current_llm.prompt_tokens = usage.get("prompt_tokens", 0)
                self._current_llm.completion_tokens = usage.get(
                    "completion_tokens", 0)
                self._current_llm.total_tokens = usage.get("total_tokens", 0)

                # 累加总计
                self.total_tokens["prompt"] += self._current_llm.prompt_tokens
                self.total_tokens["completion"] += self._current_llm.completion_tokens
                self.total_tokens["total"] += self._current_llm.total_tokens

            self.trace.llm_calls.append(self._current_llm)

            token_str = f"Tokens: {self._current_llm.total_tokens or 'N/A'}"
            self._log(
                LogLevel.INFO,
                f"✅ [LLM] Completed in {self._current_llm.duration:.2f}s | {token_str}",
                indent=0
            )
            self._emit_event("llm_end", {
                "duration": self._current_llm.duration,
                "tokens": self._current_llm.total_tokens,
                "node": self._current_llm.node_context
            })

            self._current_llm = None

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> Any:
        """当 LLM 出错时触发"""
        self._log(LogLevel.ERROR, f"❌ [LLM Error] {error}")
        if self._current_llm:
            self._current_llm.end_time = time.time()
            self._current_llm.duration = self._current_llm.end_time - self._current_llm.start_time
            self.trace.llm_calls.append(self._current_llm)
            self._current_llm = None

    # ===== 工具调用监控 =====

    def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs: Any
    ) -> Any:
        """当工具开始调用时触发"""
        tool_name = serialized.get("name", "unknown_tool")

        self._current_tool = ToolExecution(
            name=tool_name,
            node_context=self._current_node or "unknown",
            start_time=time.time(),
            input_preview=self._truncate(
                input_str) if self.show_tool_io else None
        )

        self._log(LogLevel.INFO,
                  f"🛠️ [Tool] Call Started: {tool_name}", indent=0)

        if self.show_tool_io and self.log_level == LogLevel.DEBUG:
            self._log(LogLevel.DEBUG,
                      f"   Input: {self._current_tool.input_preview}", indent=1)

        self._emit_event("tool_start", {
            "name": tool_name,
            "node": self._current_node,
            "input": input_str[:100] if self.show_tool_io else None
        })

    def on_tool_end(self, output: str, **kwargs: Any) -> Any:
        """当工具调用结束时触发"""
        if self._current_tool:
            self._current_tool.end_time = time.time()
            self._current_tool.duration = self._current_tool.end_time - \
                self._current_tool.start_time
            self._current_tool.status = "completed"
            self._current_tool.output_preview = self._truncate(
                output) if self.show_tool_io else None

            self.trace.tool_calls.append(self._current_tool)

            self._log(
                LogLevel.INFO,
                f"🔧 [Tool] Completed: {self._current_tool.name} in {self._current_tool.duration:.2f}s",
                indent=0
            )

            if self.show_tool_io and self.log_level == LogLevel.DEBUG:
                self._log(
                    LogLevel.DEBUG, f"   Output: {self._current_tool.output_preview}", indent=1)

            self._emit_event("tool_end", {
                "name": self._current_tool.name,
                "duration": self._current_tool.duration,
                "output": output[:100] if self.show_tool_io else None
            })

            self._current_tool = None

    def on_tool_error(self, error: BaseException, **kwargs: Any) -> Any:
        """当工具调用出错时触发"""
        error_msg = str(error)
        self._log(LogLevel.ERROR, f"❌ [Tool Error] {error_msg}")

        if self._current_tool:
            self._current_tool.end_time = time.time()
            self._current_tool.duration = self._current_tool.end_time - \
                self._current_tool.start_time
            self._current_tool.status = "error"
            self._current_tool.error = error_msg
            self.trace.tool_calls.append(self._current_tool)
            self._current_tool = None

        self._emit_event("tool_error", {"error": error_msg})

    # ===== 统计报告 =====

    def print_summary(self, detailed: bool = True):
        """
        打印执行摘要报告。

        Args:
            detailed: 是否显示详细信息
        """
        if not self.trace.start_time:
            print("⚠️ No execution data to summarize.")
            return

        self.trace.end_time = time.time()
        total_duration = self.trace.end_time - self.trace.start_time

        print("\n" + "=" * 60)
        print("📊 AGENT EXECUTION SUMMARY")
        print("=" * 60)

        # 基本信息
        print(f"\n🆔 Session: {self.trace.session_id}")
        print(f"💬 User Input: {self._truncate(self.trace.user_input)}")
        print(f"⏱️ Total Duration: {total_duration:.2f}s")
        print(f"📌 Status: {self.trace.status}")

        # 节点统计
        print(f"\n📍 Nodes Executed: {len(self.trace.nodes)}")
        if detailed and self.trace.nodes:
            for node in self.trace.nodes:
                status_icon = "✅" if node.status == "completed" else "❌"
                duration_str = f"{node.duration:.2f}s" if node.duration else "N/A"
                output_preview = ""
                if node.output_message:
                    output_preview = f"\n      💬 {node.output_message}"
                print(
                    f"   {status_icon} {node.name}: {duration_str}{output_preview}")

        # LLM 调用统计
        print(f"\n🤖 LLM Calls: {len(self.trace.llm_calls)}")
        if self.trace.llm_calls:
            total_llm_time = sum(c.duration or 0 for c in self.trace.llm_calls)
            print(f"   Total LLM Time: {total_llm_time:.2f}s")
            print(f"   Total Tokens: {self.total_tokens['total']}")
            print(f"   ├─ Prompt: {self.total_tokens['prompt']}")
            print(f"   └─ Completion: {self.total_tokens['completion']}")

        # 工具调用统计
        print(f"\n🛠️ Tool Calls: {len(self.trace.tool_calls)}")
        if detailed and self.trace.tool_calls:
            for tool in self.trace.tool_calls:
                status_icon = "✅" if tool.status == "completed" else "❌"
                duration_str = f"{tool.duration:.2f}s" if tool.duration else "N/A"
                print(f"   {status_icon} {tool.name}: {duration_str}")

        # 节点输出详情 (新增)
        if detailed and self.trace.node_outputs:
            print(f"\n📝 Node Outputs: {len(self.trace.node_outputs)}")
            for output in self.trace.node_outputs:
                icon = self._get_node_icon(output.node_name)
                print(f"   {icon} {output.node_name}:")
                if output.message_content:
                    # 显示更长的内容
                    content_preview = output.message_content[:300] + "..." if len(
                        output.message_content) > 300 else output.message_content
                    # 处理多行内容
                    lines = content_preview.split('\n')
                    for i, line in enumerate(lines[:5]):  # 最多显示5行
                        prefix = "      " if i == 0 else "      "
                        print(f"{prefix}{line}")
                    if len(lines) > 5:
                        print(f"      ... ({len(lines) - 5} more lines)")
                if output.plans:
                    print(
                        f"      📋 Plans: {len(output.plans)} options generated")
                if output.options:
                    for key, val in output.options.items():
                        if isinstance(val, list):
                            print(f"      🔍 {key}: {len(val)} results")
                if output.state_updates:
                    print(f"      🔄 State: {output.state_updates}")

        # 路由决策
        if self.trace.router_decisions:
            print(f"\n🚦 Router Decisions: {len(self.trace.router_decisions)}")
            if detailed:
                for decision in self.trace.router_decisions:
                    print(f"   → {decision.decision}")

        # 错误信息
        if self.trace.error:
            print(f"\n❌ Error: {self.trace.error}")

        print("\n" + "=" * 60)

    def get_trace_json(self) -> str:
        """导出追踪数据为 JSON 格式"""
        def serialize(obj):
            if hasattr(obj, "__dict__"):
                d = {}
                for k, v in obj.__dict__.items():
                    if not k.startswith("_"):
                        d[k] = serialize(v)
                return d
            elif isinstance(obj, list):
                return [serialize(i) for i in obj]
            elif isinstance(obj, dict):
                return {k: serialize(v) for k, v in obj.items()}
            elif isinstance(obj, Enum):
                return obj.value
            else:
                return obj

        return json.dumps(serialize(self.trace), ensure_ascii=False, indent=2)

    def reset(self):
        """重置监控器状态，用于新的会话"""
        self.trace = WorkflowTrace(
            session_id=datetime.now().strftime("%Y%m%d_%H%M%S"),
            user_input="",
            start_time=0
        )
        self._current_node = None
        self._current_llm = None
        self._current_tool = None
        self._node_stack = []
        self._last_step = None
        self.total_tokens = {"prompt": 0, "completion": 0, "total": 0}


# ===== 便捷工厂函数 =====

def create_monitor(
    verbose: bool = False,
    session_id: Optional[str] = None
) -> AgentPerformanceMonitor:
    """
    创建监控器的便捷工厂函数。

    Args:
        verbose: 是否开启详细模式 (DEBUG 级别)
        session_id: 可选的会话 ID

    Returns:
        配置好的 AgentPerformanceMonitor 实例
    """
    return AgentPerformanceMonitor(
        log_level=LogLevel.DEBUG if verbose else LogLevel.INFO,
        show_tool_io=True,
        show_router_decisions=True,
        session_id=session_id
    )
