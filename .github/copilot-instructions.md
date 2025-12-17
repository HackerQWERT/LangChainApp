# Copilot Instructions for LangChainApp

This is a Python-based AI Agent application using **FastAPI** and **LangGraph**. The project implements a travel agent capable of searching flights, hotels, and weather, utilizing Azure OpenAI.

## 🏗 Architecture Overview

- **Framework**: FastAPI (`app/main.py`) served via Uvicorn.
- **Agent Engine**: LangGraph (`app/infras/agent/travel_agent.py`) managing state and workflow.
- **Directory Structure**:
  - `app/infras/agent/`: Core agent logic, graph definitions, and runners.
  - `app/infras/func/`: Agent tools and functions (the "skills" of the agent).
  - `app/infras/third_api/`: Wrappers for external APIs (Amadeus, OpenWeather, Tavily).
  - `app/infras/rag/`: RAG implementations (GraphRAG, AgenticRAG).
  - `app/router/`: FastAPI route handlers.
  - `tests/`: Pytest suite.

## 🚀 Development Workflow

- **Run Server**: Execute `python start.py`. This starts the API at `http://localhost:8000`.
  - API Docs: `http://localhost:8000/scalar/v1` or `/docs`.
- **Run Tests**: Use `pytest`. Configuration is in `pyproject.toml`.
- **Dependency Management**: Dependencies are listed in `pyproject.toml`.

## 🧩 Agent Development Patterns

### 1. Defining Agents (LangGraph)
- Agents are defined as `StateGraph` in `app/infras/agent/travel_agent.py`.
- Use `TypedDict` or Pydantic models for graph state.
- **Streaming**: The project uses a custom SSE (Server-Sent Events) implementation in `app/infras/agent/agent_runner.py`.
  - `sse_chat_stream`: Handles protocol adaptation for the frontend.
  - `run_chat_stream`: Console-based streaming for debugging.

### 2. Adding Tools
1.  **Implement Logic**: Create the function in `app/infras/func/`.
2.  **External Calls**: If it calls an external API, put the low-level wrapper in `app/infras/third_api/`.
3.  **Register**: Import and add the tool to the agent's tool node in `app/infras/agent/travel_agent.py`.

### 3. RAG Integration
- RAG components are located in `app/infras/rag/`.
- `GraphRag.py` and `AgenticRag.py` suggest advanced retrieval strategies.

## 📝 Coding Conventions

- **Async/Await**: The codebase is heavily asynchronous (FastAPI + LangChain async methods). Always use `async def` for route handlers and agent nodes.
- **Type Hinting**: Use Python type hints extensively.
- **Configuration**: Environment variables are loaded via `python-dotenv`. Ensure `.env` is present (see `app/infras/agent/travel_agent.py` for keys like `AZURE_OPENAI_API_KEY`).
- **Error Handling**: Agent runners should catch exceptions to prevent server crashes during streaming.

## 🔍 Key Files
- `start.py`: Entry point for the dev server.
- `app/infras/agent/travel_agent.py`: Main agent graph definition.
- `app/infras/agent/agent_runner.py`: Streaming logic (SSE & Console).
- `app/router/agent_router.py`: Endpoint handling agent requests.
