"""
API router for arXiv data processing operations.
Provides a single endpoint to fetch arXiv papers and store them in the database.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data", tags=["data-processing"])


@router.post("/fetch-arxiv-today")
async def fetch_arxiv_today_api(
    request: Request,
    thread_id: Optional[str] = None,
    days: Optional[int] = None,
    categories: Optional[str] = None,
    max_results: Optional[int] = None,
):
    """Fetch arXiv papers within a time window and persist them.

    Args:
        thread_id: Optional thread id used by LangGraph checkpointer.
        days: Optional number of days to include (default 1 = today UTC).
        categories: Optional comma-separated categories (e.g. "cs.AI,cs.CV"). Use "all" or "*" to include all categories.
        max_results: Optional max results hint for arXiv query.
    """
    try:
        graph = request.app.state.data_processing_graph
        config = {"configurable": {"thread_id": thread_id or "arxiv_daily"}}
        if days is not None and days > 0:
            config["configurable"]["days"] = int(days)
        if categories is not None:
            if categories.strip().lower() in ("all", "*"):
                config["configurable"]["categories"] = []
            else:
                parsed = [c.strip() for c in categories.split(",") if c.strip()]
                if parsed:
                    config["configurable"]["categories"] = parsed
        if max_results is not None and max_results > 0:
            config["configurable"]["max_results"] = int(max_results)

        result = await graph.ainvoke({}, config=config)

        status = result.get("processing_status")
        if status == "completed":
            return {
                "status": "success",
                "inserted": result.get("inserted", 0),
                "skipped": result.get("skipped", 0),
                "fetched": result.get("fetched", 0),
            }
        if status == "error":
            raise HTTPException(status_code=500, detail=result.get("error_message", "unknown error"))

        return {
            "status": "ok",
            "message": f"graph finished with status={status}",
            "inserted": result.get("inserted", 0),
            "skipped": result.get("skipped", 0),
            "fetched": result.get("fetched", 0),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in fetch_arxiv_today_api: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}") 