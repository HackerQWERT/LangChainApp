import uvicorn
from app.infras.agent.travel_agent import travel_agent
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage, AIMessage
from app import main
# 使用LangChain调用OpenAI兼容API
# model = ChatOpenAI(
#     model="gemini-2.5-pro",
#     api_key="sk-BlhmNRZgk4fFb3Zed1vwMF2jGxCixE6BLH4CfPvdzWslUlDd",
#     base_url="https://hiapi.online/v1"
# )

# messages = [
#     SystemMessage(content="You are a helpful assistant"),``
#     HumanMessage(content="Hello"),
# ]

# response = model.invoke(messages)
# print(response.content)


if __name__ == "__main__":

    """启动FastAPI服务器"""
    print("启动LangChain Travel App服务器...")
    print("访问 http://localhost:8000 查看API文档")
    print("访问 http://localhost:8000/agent 使用POST请求调用agent")
    uvicorn.run(main.app, host="127.0.0.1", port=8000)
