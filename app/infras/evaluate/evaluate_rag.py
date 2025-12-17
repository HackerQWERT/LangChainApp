from langsmith import evaluate
from ragas import evaluate as ragas_evaluate
from ragas.metrics import context_recall
from langchain_openai import ChatOpenAI

# 1. 定义你的RAG链（必须返回 retriver 检索到的 context）


def my_rag_chain(inputs):
    # 假设你的链返回这样的结构
    # 实际调用你的 retriever
    docs = retriever.invoke(inputs["question"])
    return {
        "answer": "Generated answer...",
        "contexts": [d.page_content for d in docs]  # 必须提取出文本列表
    }


# 2. 运行评估
# Ragas 的 context_recall 需要: question, ground_truth, contexts
results = evaluate(
    my_rag_chain,
    data="<你的Dataset名称>",
    evaluators=[context_recall],  # 直接使用 Ragas 的指标
    experiment_prefix="ragas-recall-test",
    metadata={"version": "1.0"}
)
