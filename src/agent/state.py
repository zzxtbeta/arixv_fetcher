
from __future__ import annotations
from typing_extensions import TypedDict, Annotated
from langgraph.graph import add_messages
from typing import List, Optional, Dict, Any
import operator


class OverallState(TypedDict, total=False):
    """Minimal chat state."""
    messages: Annotated[list, add_messages]


class DataProcessingState(TypedDict, total=False):
    """State for arXiv processing graph operations."""
    processing_status: str
    error_message: str
    # Raw fetched papers from arXiv
    raw_papers: List[Dict[str, Any]]
    # Enriched papers accumulator (parallel-safe concatenate)
    papers: Annotated[List[Dict[str, Any]], operator.add]
    fetched: int
    inserted: int
    skipped: int
    categories: List[str]


