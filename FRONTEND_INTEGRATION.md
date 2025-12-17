# LangChainApp 前端对接文档 (Frontend Integration Guide)

本文档详细说明了如何对接 LangChainApp 的智能旅行代理 API。该接口基于 **Server-Sent Events (SSE)** 协议，支持实时打字机效果和富交互组件。

## 1. 接口定义 (API Specification)

- **Endpoint**: `/vibe/stream`
- **Method**: `POST`
- **Content-Type**: `application/json`
- **Response Type**: `text/event-stream`

### 请求参数 (Request Body)

| 参数名 | 类型 | 必选 | 说明 | 示例 |
| :--- | :--- | :--- | :--- | :--- |
| `thread_id` | `string` | 是 | 会话唯一标识符，用于保持上下文记忆。 | `"user_123"` |
| `message` | `string` | 是 | 用户输入的文本内容。 | `"我想去日本玩"` |

**请求示例:**
```json
{
  "thread_id": "session_001",
  "message": "帮我查一下去东京的机票"
}
```

---

## 2. SSE 事件协议 (Event Protocol)

后端会通过 SSE 流推送不同类型的事件 (`event`)。前端需监听这些事件并渲染对应的 UI。

### 2.1 文本消息 (`message`)

用于展示 AI 的回复。

- **场景**: 闲聊、总结行程、普通问答、以及**格式化的资源展示**（如机票、酒店、天气卡片）。
- **Payload**:
  ```json
  {
    "content": "### [H1] Hilton Tokyo\n- **💰 价格**: ¥1200...", 
    "is_stream": true
  }
  ```
- **前端处理逻辑**:
  - **Markdown 渲染**: `content` 字段包含丰富的 Markdown 格式（标题、列表、加粗、链接、图片），前端**必须**使用 Markdown 渲染器进行展示。
  - **统一追加 (Append)**: 无论是流式字符还是完整文本块，都应追加到当前 AI 回复气泡的末尾。后端已优化换行符 (`\n\n`)，确保追加时段落分明。
  - `is_stream` 字段仅供参考。

### 2.2 状态提示 (`status`)

用于缓解用户等待焦虑，展示系统当前正在做什么。

- **场景**: 开始思考、调用外部工具（搜索机票、查询天气）时。
- **Payload**:
  ```json
  {
    "content": "🤔 正在思考...",
    "node": "plan"
  }
  ```
- **前端处理逻辑**:
  - 在聊天界面底部或状态栏展示 Loading 动画及 `content` 文本。
  - 收到下一个 `message` 或 `control` 事件时，隐藏此状态。

### 2.3 交互组件 (`control`)

用于触发富交互 UI，如卡片选择、表单确认。

- **场景**: 方案确认、机票选择、酒店选择。
- **Payload**:
  ```json
  {
    "type": "select_plan",  // 组件类型
    "options": [...]        // 组件数据
  }
  ```
- **支持的组件类型 (`type`)**:

  | type | 描述 | options 数据结构示例 |
  | :--- | :--- | :--- |
  | `select_plan` | **方案选择卡片**。展示 3 个旅行方案供用户点击。 | `[{"name": "经济游", "price_estimate": "5k", "details": "..."}]` |
  | `select_flight` | **机票列表**。展示航班列表，用户需回复 "F1" 选择。 | `[{"airline": "ANA", "flight_number": "NH904", "price": "¥2000", "departure": "...", "link": "..."}]` |
  | `select_hotel` | **酒店列表**。展示酒店列表，用户需回复 "H1" 选择。 | `[{"name": "Hilton", "price": "¥1200", "rating": "4.5", "thumbnail": "http...", "amenities": "Wifi..."}]` |

- **前端处理逻辑**:
  - **双模展示**: 后端会同时发送格式化好的 Markdown 文本 (`message` 事件) 和结构化数据 (`control` 事件)。
    - **简单模式**: 仅渲染 Markdown 文本，忽略 `control` 事件（用户手动输入 "F1"）。
    - **增强模式**: 渲染 Markdown 文本的同时，利用 `control` 数据在底部展示可点击的交互卡片（点击卡片自动发送 "F1"）。
  - 根据 `type` 渲染对应的 UI 组件。

### 2.4 错误处理 (`error`)

- **Payload**:
  ```json
  {
    "message": "API 调用超时，请重试。"
  }
  ```
- **前端处理逻辑**: 展示红色错误提示或 Toast。

---

## 3. 前端对接示例 (JavaScript/TypeScript)

由于标准 `EventSource` 不支持 POST 请求，推荐使用 `fetch` 配合 `ReadableStream`，或使用第三方库（如 `@microsoft/fetch-event-source`）。

### 方案 A: 使用原生 fetch (推荐)

```javascript
async function chatWithAgent(threadId, userMessage) {
  const response = await fetch('http://localhost:8000/api/vibe/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      thread_id: threadId,
      message: userMessage,
    }),
  });

  if (!response.ok) {
    console.error("Network error");
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value, { stream: true });
    buffer += chunk;

    // 手动解析 SSE 格式 (event: ... \n data: ...)
    const lines = buffer.split('\n\n');
    buffer = lines.pop(); // 保留未完成的块

    for (const line of lines) {
      const eventMatch = line.match(/^event: (.*)$/m);
      const dataMatch = line.match(/^data: (.*)$/m);

      if (eventMatch && dataMatch) {
        const eventType = eventMatch[1];
        const data = JSON.parse(dataMatch[1]);

        handleEvent(eventType, data);
      }
    }
  }
}

function handleEvent(type, data) {
  switch (type) {
    case 'message':
      if (data.is_stream) {
        console.log("正在输入:", data.content); // 追加到 UI
      } else {
        console.log("完整回复:", data.content); // 显示完整块
      }
      break;
    case 'status':
      console.log("系统状态:", data.content); // 显示 Loading
      break;
    case 'control':
      console.log("渲染组件:", data.type, data.options); // 渲染卡片
      break;
    case 'error':
      console.error("错误:", data.message);
      break;
  }
}
```

### 方案 B: 使用 @microsoft/fetch-event-source (更稳健)

```typescript
import { fetchEventSource } from '@microsoft/fetch-event-source';

await fetchEventSource('http://localhost:8000/api/vibe/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ thread_id: '123', message: '你好' }),
  
  onmessage(msg) {
    const { event, data } = msg;
    const payload = JSON.parse(data);
    
    if (event === 'message') {
      // 处理文本
    } else if (event === 'control') {
      // 处理组件
    }
    // ...
  }
});
```
