
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
    # 断点续传相关字段
    session_id: Optional[str]  # 处理会话ID
    resume_mode: bool  # 是否为恢复模式
    processed_paper_ids: List[str]  # 已处理的论文ID列表
    failed_paper_ids: List[str]  # 处理失败的论文ID列表
    api_exhausted: Annotated[bool, lambda x, y: y]  # API额度是否耗尽（取最新值）
    current_batch_index: int  # 当前批次索引


