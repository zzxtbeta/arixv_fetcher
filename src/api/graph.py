"""API endpoints for chat operations (minimal)."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"])


class ChatRequest(BaseModel):
    """Minimal chat request body."""
    text: str = Field(..., description="User input text")
    thread_id: Optional[str] = Field(default=None, description="Optional thread id")
    model: Optional[str] = Field(default=None, description="Optional override model name")


class ChatResponse(BaseModel):
    """Minimal chat response body."""
    reply: str


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: Request, body: ChatRequest) -> ChatResponse:
    """Execute a single-turn chat via the minimal chat graph and return assistant reply."""
    try:
        graph = request.app.state.graph

        initial_state = {"messages": [HumanMessage(content=body.text)]}
        # Provide default thread_id to satisfy checkpointer
        config = {"configurable": {"thread_id": body.thread_id or "chat_default"}}
        if body.model:
            config["configurable"]["model"] = body.model

        result = await graph.ainvoke(initial_state, config=config)
        messages = result.get("messages", [])
        if not messages:
            raise HTTPException(status_code=500, detail="No response from chat graph")

        # The last message is expected to be assistant
        reply = getattr(messages[-1], "content", None) or ""
        return ChatResponse(reply=reply)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat endpoint error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}") 