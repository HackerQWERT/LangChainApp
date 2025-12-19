import os
import asyncio
from tavily import TavilyClient

# --- 旅行搜索服务部分 (Tavily SDK版) ---


async def tavily_search(query: str, include_full_content: bool = False) -> str:
    """
    使用官方 tavily-python 库搜索旅行指南。

    Args:
        query: 搜索查询词
        include_full_content: 是否包含完整网页内容（默认 False，只返回摘要）
                              设为 True 可获取完整内容，但响应会更慢且消耗更多 token
    """
    api_key = os.environ.get("TAVILY_API_KEY")

    if not api_key:
        return "Error: TAVILY_API_KEY is not set in environment variables. Unable to perform live search."

    client = TavilyClient(api_key=api_key)

    try:
        # TavilyClient.search 是同步方法，使用 asyncio.to_thread 避免阻塞 Event Loop
        response = await asyncio.to_thread(
            client.search,
            query=query,
            search_depth="advanced" if include_full_content else "basic",
            include_answer=True,  # 包含 AI 生成的总结回答
            include_raw_content=include_full_content,  # 是否包含完整网页内容
            max_results=3
        )

        # 解析返回结果 (SDK 返回的是 Python 字典)
        results = []

        # 1. Tavily 的直接回答（这是 AI 生成的摘要，Agent 可直接使用）
        if response.get("answer"):
            results.append(f"## AI Summary\n{response['answer']}")

        # 2. 具体的搜索结果
        for i, res in enumerate(response.get("results", []), 1):
            title = res.get("title", "No Title")
            url = res.get("url", "")

            # 优先使用完整内容，否则使用摘要
            if include_full_content and res.get("raw_content"):
                # 完整内容可能很长，截取前 2000 字符
                raw_content = res.get("raw_content", "")[:2000]
                content = f"[Full Content]\n{raw_content}"
            else:
                content = res.get("content", "")

            results.append(
                f"## Source {i}: {title}\n"
                f"URL: {url}\n"
                f"{content}\n"
            )

        return "\n---\n".join(results)

    except Exception as e:
        return f"Error executing Tavily Search: {str(e)}"
