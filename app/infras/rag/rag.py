import os
from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_openai import AzureOpenAIEmbeddings
from langchain.text_splitter import CharacterTextSplitter
from langchain.docstore.document import Document


# 嵌入模型

load_dotenv()

# 嵌入模型部署（可选，如果不同）
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME = os.getenv(
    "AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME")
AZURE_OPENAI_EMBEDDING_API_KEY = os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY")
AZURE_OPENAI_EMBEDDING_API_VERSION = os.getenv(
    "AZURE_OPENAI_EMBEDDING_API_VERSION")
AZURE_OPENAI_EMBEDDING_ENDPOINT = os.getenv("AZURE_OPENAI_EMBEDDING_ENDPOINT")

os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME"] = AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME
os.environ["AZURE_OPENAI_EMBEDDING_API_KEY"] = AZURE_OPENAI_EMBEDDING_API_KEY
os.environ["AZURE_OPENAI_EMBEDDING_API_VERSION"] = AZURE_OPENAI_EMBEDDING_API_VERSION
os.environ["AZURE_OPENAI_EMBEDDING_ENDPOINT"] = AZURE_OPENAI_EMBEDDING_ENDPOINT


# 准备文档（示例）
docs = [Document(page_content="这是一个测试文档，关于 RAG 的知识。")]

# 分割 + 嵌入
text_splitter = CharacterTextSplitter(chunk_size=1000, chunk_overlap=0)
splits = text_splitter.split_documents(docs)
embeddings = AzureOpenAIEmbeddings(
    azure_endpoint=AZURE_OPENAI_EMBEDDING_ENDPOINT,
    api_key=AZURE_OPENAI_EMBEDDING_API_KEY,
    api_version=AZURE_OPENAI_EMBEDDING_API_VERSION,
    azure_deployment=AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME,
)  # 或用本地 HuggingFaceEmbeddings()

# 创建嵌入式向量库
vectorstore = Chroma.from_documents(documents=splits, embedding=embeddings)

# 查询 RAG
retriever = vectorstore.as_retriever()
query = "什么是 RAG？"
results = retriever.get_relevant_documents(query)
print(results[0].page_content)  # 输出相关片段
