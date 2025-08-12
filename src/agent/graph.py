"""Minimal chat workflow: start -> chat -> end"""

import os
from typing import Dict, Any

from langgraph.graph import StateGraph, START, END
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.state import OverallState
from src.agent.configuration import Configuration


SYSTEM_PROMPT = "You are a helpful assistant."


async def chat_node(state: OverallState, config: RunnableConfig) -> Dict[str, Any]:
    """Single chat turn: respond to the latest user message and append assistant reply."""
    configurable = Configuration.from_runnable_config(config)
    messages = state.get("messages", [])

    if not messages:
        return {"messages": [SystemMessage(content=SYSTEM_PROMPT)]}

    llm = ChatOpenAI(
        model=configurable.model,
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=0.5,
    )
    response = await llm.ainvoke([
        SystemMessage(content=SYSTEM_PROMPT),
        *messages,
    ])

    return {"messages": [response]}


# Build workflow graph
builder = StateGraph(OverallState, config_schema=Configuration)

builder.add_node("chat", chat_node)

builder.add_edge(START, "chat")
builder.add_edge("chat", END)

# Compile default graph
graph = builder.compile()


async def build_graph(checkpointer=None, store=None):
    """Compile the chat graph with optional checkpointer and store."""
    return builder.compile(checkpointer=checkpointer, store=store)