import os
import json
import asyncio
from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_openai import AzureOpenAIEmbeddings, AzureChatOpenAI
from langchain.text_splitter import CharacterTextSplitter
from langchain.docstore.document import Document
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END
from typing import List
from pydantic import BaseModel, Field
from langgraph.checkpoint.memory import MemorySaver
import uuid

load_dotenv()

# Pydantic 状态模型：专注于 RAG 迭代，不包含最终 answer


class RagState(BaseModel):
    query: str = Field(..., description="用户查询")
    documents: List[str] = Field(default_factory=list, description="检索到的文档片段")
    iteration: int = Field(default=0, description="当前迭代次数")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="置信度分数")
    max_iterations: int = Field(default=10, description="最大迭代次数")
    refined_query: str = Field(default="", description="精炼后的查询")

# 输入模型：用于查询验证


class QueryInput(BaseModel):
    query: str = Field(..., min_length=1, description="输入查询")

# 输出模型：返回 RAG 状态，供外部 agent 处理生成


class RagOutput(BaseModel):
    query: str = Field(..., description="最终查询（可能精炼）")
    documents: List[str] = Field(..., description="检索到的文档")
    confidence: float = Field(..., ge=0.0, le=1.0, description="最终置信度")
    iterations_used: int = Field(..., description="实际迭代次数")


class AgenticRag:
    def __init__(self, persist_dir: str = "./chroma_db"):
        # 环境变量处理
        embedding_params = {
            "azure_endpoint": os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT"),
            "api_key": os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY"),
            "api_version": os.getenv("AZURE_OPENAI_EMBEDDING_API_VERSION", "2024-02-15-preview"),
            "azure_deployment": os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-ada-002"),
        }
        llm_params = {
            "azure_endpoint": os.getenv("AZURE_OPENAI_ENDPOINT"),
            "api_key": os.getenv("AZURE_OPENAI_API_KEY"),
            "api_version": os.getenv("AZURE_OPENAI_API_VERSION"),
            "azure_deployment": os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
        }

        try:
            self.embedding = AzureOpenAIEmbeddings(**embedding_params)
            self.llm = AzureChatOpenAI(**llm_params)
        except Exception as e:
            raise ValueError(f"Azure 初始化失败: {e}")

        # Chroma 持久化
        self.vectorstore = Chroma(
            persist_directory=persist_dir,
            embedding_function=self.embedding
        )
        self.retriever = self.vectorstore.as_retriever(search_kwargs={"k": 5})

        self.graph = self.build_graph()

    async def retrieve_documents(self, state: RagState) -> dict:
        # 注意：返回 dict 以兼容 LangGraph 的状态更新
        docs = await self.retriever.ainvoke(state.query)
        return {
            "documents": [doc.page_content for doc in docs],
            "iteration": state.iteration + 1
        }

    async def evaluate(self, state: RagState) -> dict:
        # LLM 评估置信度：升级为结构化输出（用 JSON 模式）
        docs_str = "\n".join(state.documents[-5:])  # 取最近 5 chunks
        eval_prompt = ChatPromptTemplate.from_template(
            """评估以下文档与查询的相关性和准确性：
            查询：{query}
            文档：{docs}

            请输出严格的 JSON 格式：{{"confidence": <0.0-1.0 的浮点数>, "suggestion": "<改进建议，如果 confidence < 0.8 则提供精炼查询，否则 'ok'">}}
            """
        )
        chain = eval_prompt | self.llm
        result = await chain.ainvoke({"query": state.query, "docs": docs_str})

        # 安全解析 JSON
        try:
            eval_data = json.loads(result.content.strip())
            confidence = eval_data.get("confidence", 0.0)
            suggestion = eval_data.get("suggestion", "ok")
        except (json.JSONDecodeError, KeyError):
            # Fallback 如果解析失败
            confidence = 0.5
            suggestion = "解析失败，重试"

        refined_query = suggestion if suggestion != "ok" and confidence < 0.8 else state.query
        return {
            "confidence": confidence,
            "query": refined_query,
            "refined_query": refined_query
        }

    def build_graph(self):
        workflow = StateGraph(RagState)
        workflow.add_node("retrieve", self.retrieve_documents)
        workflow.add_node("evaluate", self.evaluate)

        workflow.set_entry_point("retrieve")
        workflow.add_edge("retrieve", "evaluate")

        # 条件边：agentic 循环，到达阈值后结束（无 generate），返回状态给外部 agent
        def route_eval(state: RagState):
            if state.confidence >= 0.8 or state.iteration >= state.max_iterations:
                return END  # 直接结束
            return "retrieve"

        workflow.add_conditional_edges(
            "evaluate",
            route_eval,
            {"retrieve": "retrieve", END: END}  # 映射 END
        )

        # 加 checkpoint 支持多轮
        compiled = workflow.compile(checkpointer=MemorySaver())
        print("Mermaid 图：")
        print(compiled.get_graph().draw_mermaid())
        return compiled

    async def query(self, query: str, config: dict = None) -> RagOutput:
        # 用 Pydantic 验证输入
        input_data = QueryInput(query=query)

        initial_state_dict = {
            "query": input_data.query,
            "documents": [],
            "iteration": 0,
            "confidence": 0.0,
            "max_iterations": 10,
            "refined_query": input_data.query
        }
        # 创建 Pydantic 状态实例
        initial_state = RagState(**initial_state_dict)

        # 如果 config 为 None，提供默认的 thread_id

        if config is None:
            # 唯一 ID，或用 "default"
            config = {"configurable": {"thread_id": str(uuid.uuid4())}}

        result_dict = await self.graph.ainvoke(initial_state.model_dump(), config)
        # 转换为 Pydantic 输出模型（无 answer）
        output = RagOutput(
            query=result_dict["refined_query"] or result_dict["query"],
            documents=result_dict["documents"][-5:],  # 取最后 5 个文档
            confidence=result_dict["confidence"],
            iterations_used=result_dict["iteration"]
        )
        return output

    async def add_documents(self, documents: List[str]) -> None:
        loop = asyncio.get_running_loop()  # 替换这里，更安全
        doc_objects = [Document(page_content=doc) for doc in documents]
        text_splitter = CharacterTextSplitter(
            chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(doc_objects)
        await loop.run_in_executor(None, self.vectorstore.add_documents, splits)
        await loop.run_in_executor(None, self.vectorstore.persist)
        self.retriever = self.vectorstore.as_retriever()

    async def add_documents_from_file(self, file_path: str) -> None:
        try:
            loop = asyncio.get_running_loop()  # 替换这里，更安全
            content = await loop.run_in_executor(None, lambda: open(file_path, 'r', encoding='utf-8').read())
            await self.add_documents([content])
        except FileNotFoundError:
            print(f"文件 {file_path} 未找到")
        except Exception as e:
            print(f"读取文件时出错: {e}")


# 示例使用（返回状态给外部 agent）
if __name__ == "__main__":
    async def main():
        rag = AgenticRag()
        await rag.add_documents([
            "RAG 是 Retrieval-Augmented Generation，一种结合检索和生成的 AI 方法，用于提升 LLM 的准确性。可以用langchain实现",
            "LangGraph 是 LangChain 的扩展，用于构建状态化多代理工作流。能升级各种 agentic 场景。",
            "Pydantic 提供数据验证和序列化，支持 AI 管道中的模型定义。"
        ])

        result = await rag.query("RAG 和 LangGraph 有什么关系？")
        print("最终查询:", result.query)
        print("文档:", result.documents)
        print("置信度:", result.confidence)
        print("迭代次数:", result.iterations_used)
        # 这里外部 agent 可以用 result.documents + result.query 生成最终 answer

    asyncio.run(main())
