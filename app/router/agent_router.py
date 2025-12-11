import uvicorn
import json
from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from langchain_core.messages import HumanMessage, BaseMessage, trim_messages
from langchain_core.messages import convert_to_messages
from langgraph.types import Command

# 修改为您的命名空间
from app.infras.agent import travel_agent

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
    统一对话接口。
    LangGraph 会根据 thread_id 自动加载历史记录，前端只需发送最新的增量消息即可。
    """

    # 1. 构造 LangGraph 的输入
    config = {"configurable": {"thread_id": req.thread_id}}

    input_payload = {}

    if req.resume_action:
        # A. 恢复模式：发送 Command
        input_payload = Command(resume=req.resume_action)
    elif req.messages:
        # B. 列表模式：前端发送了标准的消息列表（例如 [{"role": "user", "content": "..."}]）
        # 用于初始化或一次性发送多条指令
        converted_msgs = convert_to_messages(req.messages)
        input_payload = {"messages": converted_msgs}
    elif req.message:
        # C. 简单模式（最常用）：前端只发了最新的字符串
        input_payload = {"messages": [HumanMessage(content=req.message)]}
    else:
        raise HTTPException(
            status_code=400, detail="Must provide message, messages, or resume_action")

    # 2. 流式响应生成器
    async def event_generator():
        try:
            # 使用 travel_agent 替代 app_graph
            async for event in travel_agent.astream_events(
                input_payload,
                version="v2",
                config=config
            ):
                kind = event["event"]

                # A. 捕获 LLM 的文本输出
                if kind == "on_chat_model_stream":
                    # 过滤掉 Supervisor 自身的输出，只显示 Worker 的
                    if event.get("metadata", {}).get("langgraph_node") != "_supervisor":
                        content = event["data"]["chunk"].content
                        if content:
                            # SSE 格式: data: {json}\n\n
                            data = json.dumps(
                                {"type": "delta", "content": content}, ensure_ascii=False)
                            yield f"data: {data}\n\n"

                # B. 捕获工具调用 (可选显示)
                elif kind == "on_tool_start":
                    data = json.dumps(
                        {"type": "tool", "name": event["name"]}, ensure_ascii=False)
                    yield f"data: {data}\n\n"

                # C. 捕获中断请求 (Interrupt)
                # 注意：流式过程中很难捕捉到完整的中断 payload，通常在流结束后检查状态

        except Exception as e:
            data = json.dumps(
                {"type": "error", "content": str(e)}, ensure_ascii=False)
            yield f"data: {data}\n\n"

        # 流结束后，检查是否处于中断状态
        # 这是获取 "human_approval_node" 中 interrupt(msg) 内容的最佳时机
        final_state = travel_agent.get_state(config)
        if final_state.tasks and final_state.tasks[0].interrupts:
            # 获取中断时传出来的数据 (就是 rules.py 里定义的 interrupt_msg)
            interrupt_data = final_state.tasks[0].interrupts[0].value
            data = json.dumps({
                "type": "interrupt",
                "payload": interrupt_data
            }, ensure_ascii=False)
            yield f"data: {data}\n\n"

        # SSE 规范通常建议发送一个结束信号，方便客户端关闭连接（可选）
        yield "data: [DONE]\n\n"

    from fastapi.responses import StreamingResponse
    # 修改 media_type 为 text/event-stream
    return StreamingResponse(event_generator(), media_type="text/event-stream")
