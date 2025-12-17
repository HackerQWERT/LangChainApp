import os
from dotenv import load_dotenv
from langsmith import evaluate
from ragas import evaluate as ragas_evaluate
from ragas.metrics import context_recall
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.text_splitter import CharacterTextSplitter
from langchain.docstore.document import Document
from datasets import Dataset

load_dotenv()

# 设置环境变量
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME = os.getenv(
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME")
AZURE_OPENAI_EMBEDDING_API_KEY = os.getenv("AZURE_"
                                           "OPENAI_EMBEDDING_API_KEY")
AZURE_OPENAI_EMBEDDING_API_VERSION = os.getenv(
    "AZURE_OPENAI_EMBEDDING_API_VERSION")
AZURE_OPENAI_EMBEDDING_ENDPOINT = os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

# 初始化嵌入模型
embeddings = AzureOpenAIEmbeddings(
    azure_endpoint=AZURE_OPENAI_EMBEDDING_ENDPOINT,
    api_key=AZURE_OPENAI_EMBEDDING_API_KEY,
    api_version=AZURE_OPENAI_EMBEDDING_API_VERSION,
    azure_deployment=AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME,
)

# 初始化LLM
llm = AzureChatOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_OPENAI_API_VERSION,
    azure_deployment=AZURE_OPENAI_DEPLOYMENT_NAME,
)

# 准备示例文档
docs = [
    Document(page_content="RAG（Retrieval-Augmented Generation）是一种结合检索和生成的AI技术。它首先从知识库中检索相关信息，然后基于这些信息生成回答。"),
    Document(page_content="LangChain是一个用于构建LLM应用的框架，支持RAG、代理和链式调用。"),
    Document(
        page_content="评估RAG系统通常使用指标如context_recall、context_precision和answer_relevancy。")
]

# 分割文档
text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
splits = text_splitter.split_documents(docs)

# 创建向量存储
vectorstore = Chroma.from_documents(
    documents=splits, embedding=embeddings, persist_directory="./chroma_db")
retriever = vectorstore.as_retriever()

# 定义RAG链


def my_rag_chain(inputs):
    question = inputs["question"]
    docs = retriever.get_relevant_documents(question)
    contexts = [d.page_content for d in docs]

    # 简单的生成回答（实际应用中应该使用更复杂的链）
    answer = f"基于检索到的信息，回答：{question}"

    return {
        "answer": answer,
        "contexts": contexts
    }


# 创建示例数据集
data = {
    "question": ["什么是RAG？", "LangChain是什么？", "如何评估RAG系统？"],
    "ground_truth": [
        "RAG是一种结合检索和生成的AI技术。",
        "LangChain是一个用于构建LLM应用的框架。",
        "使用指标如context_recall、context_precision和answer_relevancy。"
    ]
}
dataset = Dataset.from_dict(data)

# 运行评估
if __name__ == "__main__":
    results = ragas_evaluate(
        dataset=dataset,
        metrics=[context_recall],
        llm=llm,
        embeddings=embeddings,
        run_config=None
    )
    print("评估结果:")
    print(results)
