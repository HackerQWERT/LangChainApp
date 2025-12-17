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

### 7. 🏗️ 技术架构特性
- **RAG 增强检索**：包含 `GraphRag` 和 `AgenticRag` 实现，支持基于知识图谱的高级检索。
- **SSE 实时流式交互**：支持 Server-Sent Events 协议，实现打字机效果及前端交互组件（如卡片选择）的实时推送。
- **可视化调试**：提供控制台流式输出，清晰展示 Agent 的思考过程 (Thinking Process) 和工具调用。

### 8. 📡 SSE 通信协议 (API Protocol)

后端通过 `/vibe/stream` 接口提供 Server-Sent Events (SSE) 流式响应，前端需根据 `event` 类型进行不同渲染：

| Event Type | 用途 | Data Payload 示例 | 前端处理逻辑 |
| :--- | :--- | :--- | :--- |
| `message` | 文本消息 | `{"content": "你好...", "is_stream": true}` | 统一执行**追加**逻辑。`is_stream` 标识是否为打字机字符流。 |
| `control` | 交互组件 | `{"type": "select_plan", "options": [...]}` | 渲染对应的 UI 组件（如方案选择卡片、机票列表）。 |
| `status` | 状态提示 | `{"content": "🤔 正在思考...", "node": "plan"}` | 展示 Loading 动画或状态栏提示，缓解等待焦虑。 |
| `error` | 错误信息 | `{"message": "API 调用失败..."}` | 展示错误 Toast 或警告。 |

**流式策略 (Streaming Strategy):**
- **白名单流式**: 仅 `summary` (总结) 和 `side_chat` (闲聊) 节点开启打字机效果。
- **结构化缓冲**: `plan`, `collect`, `guide` 等输出 JSON 的节点，会在后端缓冲完整后，通过 `message` (is_stream=false) 或 `control` 事件一次性发送，防止前端显示 JSON 乱码。

**详细节点流式配置表:**

| 节点名 | 输出类型 | 应该流式 (Streaming) | 应该等待 (OnChainEnd) | 原因 |
| :--- | :--- | :--- | :--- | :--- |
| `intent_router` | Structured (JSON) | ❌ | ❌ | 内部路由逻辑，无需展示 |
| `collect` | Structured (JSON) | ❌ | ✅ | 输出 JSON，需解析后展示 |
| `plan` | Structured (JSON) | ❌ | ✅ | 输出复杂 JSON (方案列表)，需解析 |
| `search_flight` | Tool + Text | ❌ | ✅ | 输出包含 API 数据，需解析 |
| `select_flight` | Structured (JSON) | ❌ | ✅ | 内部决策逻辑，输出确认文本 |
| `pay_flight` | Tool + Text | ❌ | ✅ | 支付结果，短文本 |
| `search_hotel` | Tool + Text | ❌ | ✅ | 同机票搜索 |
| `select_hotel` | Structured (JSON) | ❌ | ✅ | 同机票选择 |
| `pay_hotel` | Tool + Text | ❌ | ✅ | 同机票支付 |
| `summary` | Pure Text | ✅ | ❌ | 纯文本生成，适合打字机效果 |
| `check_weather` | Structured (JSON) | ❌ | ✅ | 内部先提取 JSON 再调用工具 |
| `side_chat` | Pure Text | ✅ | ❌ | 纯文本闲聊，适合打字机效果 |
| `guide` | Structured (JSON) | ❌ | ✅ | 输出 JSON，不能流式！ |

### 9. 🧩 核心节点说明 (Graph Nodes)

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
