# LangChainApp 智能旅行代理系统

本项目是一个基于 **FastAPI** 和 **LangGraph** 构建的智能旅行代理 AI 应用。它利用 Azure OpenAI 的推理能力，为用户提供从行程规划到预订的一站式服务。

## 🌟 核心功能列表

### 1. 🧠 智能意图识别 (Intent Routing)
- **多轮对话管理**：能够精准识别用户意图，自动路由到不同状态（如：更新信息、闲聊、查询天气、确认方案）。
- **上下文理解**：区分“闲聊”与“业务指令”，在支付等关键阶段锁定上下文，确保流程安全。

### 2. 📋 旅行需求收集 (Requirement Collection)
- **智能信息抽取**：自动从自然语言对话中提取 `出发地`、`目的地` 和 `日期`。
- **智能校验与补全**：
  - **日期标准化**：将“下周五”、“后天”等口语转换为标准 `YYYY-MM-DD` 格式。
  - **地点精确化**：强制要求具体城市名（如“东京”），自动追问模糊信息。

### 3. 🗺️ 智能行程规划 (Travel Planning)
- **攻略检索**：集成 **Tavily** 搜索引擎，实时获取目的地的最新旅游攻略和必玩景点。
- **多方案生成**：基于攻略自动生成 3 个差异化的旅行方案（经济型、豪华型、亲子游），包含价格预估和详细安排。

### 4. ✈️ 机票服务 (Flight Services)
- **智能机场代码转换**：内置全球机场数据库 (`airportsdata`)，支持中文城市名自动转换为 IATA 代码。
- **实时航班搜索**：集成 Google Flights (SerpApi) 搜索实时航班。
- **全流程预订**：支持 `搜索` -> `选择` -> `锁定订单` -> `模拟支付` 的完整闭环。

### 5. 🏨 酒店服务 (Hotel Services)
- **酒店搜索**：根据目的地和日期搜索可用酒店资源。
- **预订流程**：支持房源选择、锁定及模拟支付确认。

### 6. ☀️ 天气查询 (Weather Services)
- **实时天气**：集成 OpenWeather API，提供目的地实时天气报告，辅助出行决策。

### 7. 🛡️ 安全规则引擎 (Security Rule Engine)
- **策略模式架构**：基于 `BaseRule` 抽象类实现可扩展的规则系统，支持动态添加新规则。
- **内置安全规则**：
  - `PIISafetyRule`：检测身份证号、信用卡号、护照号等敏感信息泄露
  - `PromptInjectionRule`：防御提示词注入攻击（如"忽略之前的指令"）
  - `FinancialTransactionRule`：支付步骤风控检查
  - `NightCurfewRule`：夜间 (23:00-06:00) 预订限制
  - `SensitiveLocationRule`：敏感地区预订拦截
- **三级响应机制**：`PASS`（放行）、`BLOCK`（拦截）、`REVIEW`（人工审核，可选启用）
- **哨兵节点**：在支付等关键步骤前自动执行规则检查

### 8. 🏗️ 技术架构特性
- **RAG 增强检索**：包含 `GraphRag` 和 `AgenticRag` 实现，支持基于知识图谱的高级检索。
- **SSE 实时流式交互**：支持 Server-Sent Events 协议，实现打字机效果及前端交互组件（如卡片选择）的实时推送。
- **可视化调试**：提供控制台流式输出，清晰展示 Agent 的思考过程 (Thinking Process) 和工具调用。

### 9. 📡 SSE 通信协议 (API Protocol)

后端通过 `/vibe/stream` 接口提供 Server-Sent Events (SSE) 流式响应，前端需根据 `event` 类型进行不同渲染：

| Event Type | 用途 | Data Payload 示例 | 前端处理逻辑 |
| :--- | :--- | :--- | :--- |
| `message` | 文本消息 | `{"content": "你好...", "is_stream": true}` | 统一执行**追加**逻辑。`is_stream` 标识是否为打字机字符流。 |
| `control` | 交互组件 | `{"type": "select_plan", "options": [...]}` | 渲染对应的 UI 组件（如方案选择卡片、机票列表）。 |
| `control` | 安全拦截 | `{"type": "blocked", "reason": "检测到敏感信息"}` | 展示拦截警告，提示用户操作被阻止。 |
| `status` | 状态提示 | `{"content": "🤔 正在思考...", "node": "plan"}` | 展示 Loading 动画或状态栏提示，缓解等待焦虑。 |
| `error` | 错误信息 | `{"message": "API 调用失败..."}` | 展示错误 Toast 或警告。 |

**流式策略 (Streaming Strategy):**
- **全缓冲模式 (Full Buffering)**: 为确保前端展示的稳定性，目前所有节点（包括 `summary` 和 `side_chat`）均采用 `on_chain_end` 事件触发输出。
- **格式化输出**: 后端已针对 Markdown 渲染进行了优化，确保段落分明 (`\n\n`)，并使用 Emoji 和卡片式排版增强可读性。

**详细节点流式配置表:**

| 节点名 | 输出类型 | 处理方式 | 原因 |
| :--- | :--- | :--- | :--- |
| `intent_router` | Structured (JSON) | 内部处理 | 路由逻辑，无需展示 |
| `collect` | Structured (JSON) | Buffered | 输出 JSON，需解析后展示 |
| `plan` | Structured (JSON) | Buffered | 输出复杂 JSON (方案列表)，需解析 |
| `search_flight` | Tool + Text | Buffered | 输出包含 API 数据，需解析 |
| `select_flight` | Structured (JSON) | Buffered | 内部决策逻辑，输出确认文本 |
| `pay_flight` | Tool + Text | Buffered | 支付结果，短文本 |
| `search_hotel` | Tool + Text | Buffered | 同机票搜索 |
| `select_hotel` | Structured (JSON) | Buffered | 同机票选择 |
| `pay_hotel` | Tool + Text | Buffered | 同机票支付 |
| `summary` | Pure Text | Buffered | 确保完整生成后再发送，避免断流 |
| `check_weather` | Structured (JSON) | Buffered | 内部先提取 JSON 再调用工具 |
| `side_chat` | Pure Text | Buffered | 确保完整生成后再发送 |
| `guide` | Structured (JSON) | Buffered | 输出 JSON，不能流式！ |
| `sentinel` | Internal | Internal | 安全规则检查，无输出 |
| `block` | Text | Buffered | 拦截提示信息 |

### 10. 🧩 核心节点说明 (Graph Nodes)

LangGraph 状态机包含以下核心节点，负责不同的业务逻辑：

| 节点 ID | 功能描述 | 输出类型 |
| :--- | :--- | :--- |
| `intent_router` | **意图路由**。分析用户输入，决定下一步是收集信息、闲聊还是执行特定任务。 | 内部状态 (State Update) |
| `collect` | **信息收集**。负责多轮对话以获取完整的出发地、目的地和日期。 | JSON (Structured) |
| `plan` | **方案生成**。调用搜索工具获取攻略，并生成 3 个推荐方案。 | JSON + Control Event |
| `search_flight` | **机票搜索**。将城市名转为机场代码，调用 API 搜索实时航班。 | JSON + Control Event |
| `select_flight` | **机票锁定**。处理用户的选择指令 (如 "F1")，锁定特定航班。 | Text |
| `pay_flight` | **机票支付**。模拟支付流程，生成订单号。 | Text |
| `search_hotel` | **酒店搜索**。搜索目的地酒店资源。 | JSON + Control Event |
| `select_hotel` | **酒店锁定**。处理用户的选择指令 (如 "H1")，锁定特定酒店。 | Text |
| `pay_hotel` | **酒店支付**。模拟支付流程，生成订单号。 | Text |
| `summary` | **行程总结**。汇总所有预订信息，生成最终的 Markdown 行程单。 | Stream Text |
| `check_weather` | **天气查询**。提取地点并调用天气 API。 | Text |
| `side_chat` | **智能闲聊**。处理非业务指令，提供人性化的对话互动。 | Stream Text |
| `guide` | **流程引导**。在每个步骤结束后，生成简短的下一步操作提示。 | Text (Buffered) |
| `sentinel` | **安全哨兵**。在支付等关键步骤前执行规则引擎检查，决定放行或拦截。 | 内部状态 (State Update) |
| `block` | **拦截处理**。当规则引擎触发拦截时，生成友好的拦截提示并回退流程。 | Text |

## 🚀 开发指南 (Developer Guide)

### 🏗️ 架构概述 (Architecture Overview)

- **框架**: FastAPI (`app/main.py`) 通过 Uvicorn 提供服务。
- **代理引擎**: LangGraph (`app/infras/agent/travel_agent.py`) 管理状态和流程。
- **目录结构**:
  - `app/infras/agent/`: 核心代理逻辑、图定义、运行器和规则引擎 (`rule.py`)。
  - `app/infras/func/`: 代理工具和函数（代理的“技能”）。
  - `app/infras/third_api/`: 外部 API 包装器（Amadeus、OpenWeather、Tavily）。
  - `app/infras/rag/`: RAG 实现（GraphRAG、AgenticRAG）。
  - `app/router/`: FastAPI 路由处理器。
  - `tests/`: Pytest 测试套件。

### 🚀 开发工作流程 (Development Workflow)

- **运行服务器**: 执行 `python start.py`。这将在 `http://localhost:8000` 启动 API。
  - API 文档: `http://localhost:8000/scalar/v1` 或 `/docs`。
- **运行测试**: 使用 `pytest`。配置在 `pyproject.toml` 中。
- **依赖管理**: 依赖项列在 `pyproject.toml` 中。

### 🧩 代理开发模式 (Agent Development Patterns)

#### 1. 定义代理 (LangGraph)
- 代理在 `app/infras/agent/travel_agent.py` 中定义为 `StateGraph`。
- 使用 `TypedDict` 或 Pydantic 模型作为图状态。
- **流式**: 项目使用 `app/infras/agent/agent_runner.py` 中的自定义 SSE (Server-Sent Events) 实现。
  - `sse_chat_stream`: 处理前端的协议适配。
  - `run_chat_stream`: 控制台流式调试。

#### 2. 添加工具
1. **实现逻辑**: 在 `app/infras/func/` 中创建函数。
2. **外部调用**: 如果调用外部 API，将低级包装器放在 `app/infras/third_api/` 中。
3. **注册**: 在 `app/infras/agent/travel_agent.py` 中导入并添加到代理的工具节点。

#### 3. RAG 集成
- RAG 组件位于 `app/infras/rag/`。
- `GraphRag.py` 和 `AgenticRag.py` 建议高级检索策略。

### 📝 编码约定 (Coding Conventions)

- **Async/Await**: 代码库大量使用异步（FastAPI + LangChain 异步方法）。路由处理器和代理节点始终使用 `async def`。
- **类型提示**: 广泛使用 Python 类型提示。
- **配置**: 通过 `python-dotenv` 加载环境变量。确保 `.env` 文件存在（见 `app/infras/agent/travel_agent.py` 中的密钥，如 `AZURE_OPENAI_API_KEY`）。
- **错误处理**: 代理运行器应捕获异常，以防止流式期间服务器崩溃。

### 🔍 关键文件 (Key Files)
- `start.py`: 开发服务器入口点。
- `app/infras/agent/travel_agent.py`: 主代理图定义。
- `app/infras/agent/agent_runner.py`: 流式逻辑（SSE 和控制台）。
- `app/infras/agent/rule.py`: 安全规则引擎（策略模式实现）。
- `app/router/agent_router.py`: 处理代理请求的端点。
