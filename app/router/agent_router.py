import uvicorn
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from langchain_core.messages import HumanMessage

# 1. 导入业务 Agent
from app.infras.agent.travel_agent import travel_agent

# 2. 导入刚刚抽离的执行器逻辑
from app.infras.agent import run_chat_stream, sse_chat_stream

# 定义 Router
agent_router = APIRouter()

# --- 请求模型 ---


class ChatRequest(BaseModel):
    thread_id: str          # 会话ID
    message: str            # 用户输入文本

# --- API 端点 ---


@agent_router.post("/vibe/stream")
async def vibe(req: ChatRequest):
    """
    统一对话接口 (API Layer)。
    负责解析请求参数，并调用 runner 获取流式响应。
    """

    # 1. 准备输入数据 (Input Payload)
    input_payload = {"messages": [HumanMessage(content=req.message)]}

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
