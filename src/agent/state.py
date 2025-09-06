
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
    # 使用 Annotated 处理并发状态更新，取最新值
    processing_status: Annotated[str, lambda x, y: y if y else x]
    error_message: Annotated[str, lambda x, y: y if y else x]
    # Raw fetched papers from arXiv
    raw_papers: List[Dict[str, Any]]
    # Enriched papers accumulator (parallel-safe concatenate)
    papers: Annotated[List[Dict[str, Any]], operator.add]
    fetched: Annotated[int, lambda x, y: max(x or 0, y or 0)]
    inserted: Annotated[int, lambda x, y: max(x or 0, y or 0)]
    skipped: Annotated[int, lambda x, y: max(x or 0, y or 0)]
    categories: List[str]
    # 断点续传相关字段
    session_id: Optional[str]  # 处理会话ID
    resume_mode: bool  # 是否为恢复模式
    processed_paper_ids: List[str]  # 已处理的论文ID列表
    failed_paper_ids: List[str]  # 处理失败的论文ID列表
    api_exhausted: Annotated[bool, lambda x, y: y if y is not None else x]  # API额度是否耗尽（取最新值）
    current_batch_index: Annotated[int, lambda x, y: max(x or 0, y or 0)]  # 当前批次索引


