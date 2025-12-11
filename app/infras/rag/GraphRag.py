import asyncio
import os
import json
from graphrag.config import create_settings, ConfigType
from graphrag.index import index
from graphrag.query import query

# --- 1. 配置项目路径 ---
PROJECT_ROOT = "./official_graphrag_project"
INPUT_DIR = os.path.join(PROJECT_ROOT, "input")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")

# --- 2. 模拟你的输入数据 ---
# 官方库读取文件，所以我们先创建文件。
# 这是你原来 add_data 中的文本。
SAMPLE_TEXTS = [
    "Alice works at CompanyX and knows Bob. Bob is CEO of CompanyY.",
    "Charlie invested in CompanyX."
]


def setup_project():
    """创建 GraphRAG 所需的项目结构和输入数据。"""
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 重要的：你需要确保 settings.yaml 和 .env 文件在这个根目录下
    if not os.path.exists(os.path.join(PROJECT_ROOT, "settings.yaml")):
        print(f"⚠️ 警告: 请确保 {PROJECT_ROOT} 目录下存在 'settings.yaml' 和 '.env' 文件！")
        # 实际项目中，通常是运行 graphrag init

    # 将你的文本保存到一个文件供 GraphRAG 读取
    input_file_path = os.path.join(INPUT_DIR, "sample_data.txt")
    with open(input_file_path, "w", encoding="utf-8") as f:
        f.write("\n\n---\n\n".join(SAMPLE_TEXTS))  # 用分隔符分开

    print(f"项目结构准备完毕。数据已写入: {input_file_path}")


async def main():

    # 准备工作
    setup_project()

    # 1. 替换你的 GrapRag.__init__ 和 add_data (构建/索引阶段)
    # -------------------------------------------------------------
    print("\n--- 阶段 1: 运行索引 (替换 add_data) ---")
    print("这将调用 LLM API 并构建图谱。")

    try:
        # 加载配置
        config = create_settings(PROJECT_ROOT, ConfigType.all)
    except Exception as e:
        print(
            f"致命错误：配置加载失败。请检查 {PROJECT_ROOT} 下的 settings.yaml 和 .env。错误: {e}")
        return

    # 运行官方索引API
    await index(config=config)
    print("索引完成。图谱数据已在 'output' 文件夹中。")

    # 2. 替换你的 GrapRag.query (查询阶段)
    # -------------------------------------

    # 模拟你查询 "Alice" 的逻辑 (本地查询最适合实体查找)
    query_text = "Alice 的角色和她与周围人的关系是什么？"

    print(f"\n--- 阶段 2: 运行查询 (替换 query) ---")
    print(f"查询内容: {query_text}")

    # 运行官方查询API
    result = await query(
        question=query_text,
        config=config,
        query_type="local"  # 'local' 用于查找特定实体及其邻居
    )

    print("\n✅ 最终答案 (LLM 总结):")
    print(result.response)

    print("\n✅ 用于总结的图谱源信息 (实体和关系):")
    # 官方库返回的是用于生成答案的节点/社区列表
    for source in result.sources:
        # source 是一个字典，包含 name, type, description 等
        print(f"- {source.get('name', 'N/A')} ({source.get('type', 'N/A')})")


# 运行主函数
if __name__ == "__main__":
    asyncio.run(main())
