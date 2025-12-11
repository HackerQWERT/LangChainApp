import os
import asyncio
from tavily import TavilyClient

# --- 旅行搜索服务部分 (Tavily SDK版) ---


async def tavily_search(query: str) -> str:
    """
    使用官方 tavily-python 库搜索旅行指南。
    """
    # 优先从环境变量获取，如果没有则可以使用默认值（如您提供的测试Key）
    # 建议生产环境还是配置在环境变量中
    api_key = os.environ.get("TAVILY_API_KEY")

    if not api_key:
        return "Error: TAVILY_API_KEY is not set in environment variables. Unable to perform live search."

    # 初始化客户端
    client = TavilyClient(api_key=api_key)

    try:
        # TavilyClient.search 是同步方法，使用 asyncio.to_thread 避免阻塞 Event Loop
        response = await asyncio.to_thread(
            client.search,
            query=query,
            search_depth="basic",  # 或 "advanced"
            include_answer=True,  # 包含 AI 生成的总结回答
            max_results=3
        )

        # 解析返回结果 (SDK 返回的是 Python 字典)
        results = []

        # 1. Tavily 的直接回答
        if response.get("answer"):
            results.append(f"Summary: {response['answer']}")

        # 2. 具体的搜索结果
        for res in response.get("results", []):
            title = res.get("title", "No Title")
            content = res.get("content", "")
            url = res.get("url", "")
            results.append(
                f"Source: {title}\nURL: {url}\nContent: {content}\n")

        return "\n---\n".join(results)

    except Exception as e:
        return f"Error executing Tavily Search: {str(e)}"
