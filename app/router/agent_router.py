import uvicorn
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from langchain_core.messages import HumanMessage, convert_to_messages
from langgraph.types import Command

# 1. 导入业务 Agent
from app.infras.agent.travel_agent import travel_agent

# 2. 导入刚刚抽离的执行器逻辑
from app.infras.agent import run_chat_stream, sse_chat_stream

# 定义 Router
agent_router = APIRouter()

# --- 请求模型 ---


class ChatRequest(BaseModel):
    thread_id: str          # 会话ID
    # 场景1：普通对话，只发最新的一句（推荐）
    message: Optional[str] = None
    # 场景2：高级对话，发送多条或结构化消息（如包含 system prompt 或 多模态数据）
    messages: Optional[List[Dict[str, Any]]] = None
    # 场景3：恢复中断
    resume_action: Optional[str] = None

# --- API 端点 ---


@agent_router.post("/vibe/stream")
async def vibe(req: ChatRequest):
    """
    统一对话接口 (API Layer)。
    负责解析请求参数，并调用 runner 获取流式响应。
    """

    # 1. 准备输入数据 (Input Payload)
    input_payload = {}

    if req.resume_action:
        # A. 恢复模式
        input_payload = Command(resume=req.resume_action)
    elif req.messages:
        # B. 列表模式
        converted_msgs = convert_to_messages(req.messages)
        input_payload = {"messages": converted_msgs}
    elif req.message:
        # C. 简单模式
        input_payload = {"messages": [HumanMessage(content=req.message)]}
    else:
        raise HTTPException(
            status_code=400, detail="Must provide message, messages, or resume_action")

    # 2. 准备配置 (Config)
    config = {"configurable": {"thread_id": req.thread_id}}

    # 3. 调用 Runner 获取生成器
    # 这里我们将 logic 委托给了 agent_runner.py，Router 只负责网络层
    stream_generator = sse_chat_stream(
        agent_graph=travel_agent,
        input_payload=input_payload,
        config=config
    )

    # 4. 返回流式响应
    return StreamingResponse(stream_generator, media_type="text/event-stream")
