"""
测试 Tavily 搜索功能
用于验证 search_travel_guides 工具返回的数据结构和内容
"""

from dotenv import load_dotenv
import asyncio
import os
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# 加载环境变量
load_dotenv()


async def test_tavily_search():
    """测试 Tavily 搜索功能 - 对比普通模式和完整内容模式"""
    from app.infras.third_api.tavily import tavily_search

    query = "上海外滩旅游攻略"

    print("=" * 60)
    print("🔍 Tavily 搜索功能测试 - 对比两种模式")
    print("=" * 60)

    # 模式 1: 普通模式（只返回摘要）
    print(f"\n📝 查询: {query}")
    print("\n" + "=" * 40)
    print("📦 模式 1: 普通模式 (include_full_content=False)")
    print("=" * 40)

    try:
        result = await tavily_search(query, include_full_content=False)
        print(f"内容长度: {len(result)} 字符")
        print(f"\n{result[:1500]}...")  # 只显示前 1500 字符
    except Exception as e:
        print(f"❌ 错误: {e}")

    print("\n" + "=" * 40)
    print("📦 模式 2: 完整内容模式 (include_full_content=True)")
    print("=" * 40)

    try:
        result_full = await tavily_search(query, include_full_content=True)
        print(f"内容长度: {len(result_full)} 字符")
        print(f"\n{result_full[:2000]}...")  # 只显示前 2000 字符
    except Exception as e:
        print(f"❌ 错误: {e}")


async def test_search_travel_guides_tool():
    """测试 search_travel_guides 工具（带 @tool 装饰器）"""
    from app.infras.func.agent_func import search_travel_guides

    print("\n" + "=" * 60)
    print("🛠️ search_travel_guides 工具测试")
    print("=" * 60)

    query = "杭州西湖一日游攻略"
    print(f"\n📝 查询: {query}")
    print("-" * 50)

    try:
        # 注意: @tool 装饰的函数需要通过 .invoke() 调用
        result = await search_travel_guides.ainvoke({"query": query})
        print(f"✅ 返回结果:\n{result}")
    except Exception as e:
        print(f"❌ 错误: {e}")


async def test_raw_tavily_response():
    """测试原始 Tavily API 响应，查看完整数据结构"""
    from tavily import TavilyClient

    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        print("❌ TAVILY_API_KEY 未设置")
        return

    print("\n" + "=" * 60)
    print("📊 原始 Tavily API 响应结构")
    print("=" * 60)

    client = TavilyClient(api_key=api_key)

    query = "东京迪士尼乐园攻略"
    print(f"\n📝 查询: {query}")
    print("-" * 50)

    try:
        response = await asyncio.to_thread(
            client.search,
            query=query,
            search_depth="basic",
            include_answer=True,
            max_results=3
        )

        # 打印完整的响应结构
        print("\n🔑 响应包含的键:")
        for key in response.keys():
            print(f"  - {key}: {type(response[key]).__name__}")

        print("\n📌 AI 生成的摘要 (answer):")
        print(response.get("answer", "无"))

        print("\n📚 搜索结果 (results):")
        for i, res in enumerate(response.get("results", []), 1):
            print(f"\n  [{i}] {res.get('title', 'No Title')}")
            print(f"      URL: {res.get('url', 'N/A')}")
            print(f"      Score: {res.get('score', 'N/A')}")
            print(f"      Content: {res.get('content', '')[:200]}...")

    except Exception as e:
        print(f"❌ 错误: {e}")


async def main():
    """运行所有测试"""
    # 1. 测试原始 Tavily 搜索
    await test_tavily_search()

    # 2. 测试 search_travel_guides 工具
    await test_search_travel_guides_tool()

    # 3. 查看原始 API 响应结构
    await test_raw_tavily_response()


if __name__ == "__main__":
    asyncio.run(main())
