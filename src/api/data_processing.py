"""
API router for arXiv data processing operations.
Provides a single endpoint to fetch arXiv papers and store them in the database.
"""

import logging
from typing import Optional, List
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel

from src.agent.resume_manager import resume_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data", tags=["data-processing"])

def _gen_thread_id(prefix: str) -> str:
    try:
        import time, secrets
        return f"{prefix}-{int(time.time()*1000)}-{secrets.token_hex(4)}"
    except Exception:
        from datetime import datetime
        return f"{prefix}-{datetime.utcnow().timestamp()}"


class FetchArxivRequest(BaseModel):
    thread_id: Optional[str] = None
    categories: Optional[str] = None
    max_results: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None

@router.post("/fetch-arxiv-today")
async def fetch_arxiv_today_api(
    request: Request,
    req_data: FetchArxivRequest = None,
    thread_id: Optional[str] = Query(None),
    categories: Optional[str] = Query(None),
    max_results: Optional[int] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """Fetch arXiv papers by explicit date range or default to the last day window.
    
    Args:
        req_data: Request data containing thread_id, categories, max_results, start_date, end_date
    """
    logger.info("=== FETCH ARXIV TODAY API CALLED ===")
    try:
        graph = request.app.state.data_processing_graph
        # Use query parameters first, fallback to request body
        final_thread_id = thread_id or (req_data.thread_id if req_data else None) or _gen_thread_id("arxiv-daily")
        final_start_date = start_date or (req_data.start_date if req_data else None)
        final_end_date = end_date or (req_data.end_date if req_data else None)
        final_categories = categories or (req_data.categories if req_data else None)
        final_max_results = max_results or (req_data.max_results if req_data else None)
        
        cfg = {"thread_id": final_thread_id}

        # Extract parameters from merged data
        start_date = final_start_date
        end_date = final_end_date
        categories = final_categories
        max_results = final_max_results

        # Defaults for date range: [today-1, today] in UTC
        if not start_date or not end_date:
            today = datetime.now(timezone.utc).date()
            if not start_date:
                start_date = (today - timedelta(days=1)).isoformat()
            if not end_date:
                end_date = today.isoformat()
        
        config = {"configurable": cfg | {"start_date": start_date, "end_date": end_date}}

        if categories is not None:
            if categories.strip().lower() in ("all", "*"):
                config["configurable"]["categories"] = []
            else:
                parsed = [c.strip() for c in categories.split(",") if c.strip()]
                if parsed:
                    config["configurable"]["categories"] = parsed
        if max_results is not None and max_results > 0:
            config["configurable"]["max_results"] = int(max_results)

        cats_label = categories if categories else "(env default)"
        logger.info(
            f"API fetch-arxiv-today: thread_id={config['configurable']['thread_id']}, range={start_date}..{end_date}, "
            f"categories={cats_label}, max_results={config['configurable'].get('max_results', 200)}"
        )

        result = await graph.ainvoke({}, config=config)

        status = result.get("processing_status")
        logger.info(f"API fetch-arxiv-today done: status={status}, fetched={result.get('fetched', 0)}, inserted={result.get('inserted', 0)}, skipped={result.get('skipped', 0)}")
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


@router.post("/fetch-arxiv-by-id")
async def fetch_arxiv_by_id_api(
    request: Request,
    ids: str,
    thread_id: Optional[str] = None,
    resume_session_id: Optional[str] = Query(None, description="Resume from existing session ID"),
):
    """Fetch arXiv papers by explicit arXiv IDs and persist them.

    Args:
        ids: Comma-separated arXiv IDs (e.g. "2504.14636,2504.14645").
        thread_id: Optional thread id used by LangGraph checkpointer.
        resume_session_id: Optional session ID to resume from previous processing.
    """
    try:
        # 处理恢复模式
        if resume_session_id:
            session = resume_manager.get_session(resume_session_id)
            if not session:
                raise HTTPException(status_code=404, detail=f"Session {resume_session_id} not found")
            
            if session.status == "completed":
                return {
                    "status": "already_completed",
                    "session_id": resume_session_id,
                    "inserted": session.total_inserted,
                    "skipped": session.total_skipped,
                    "fetched": session.total_papers,
                    "message": "Session already completed"
                }
            
            # 获取待处理的论文ID
            pending_ids = resume_manager.get_pending_paper_ids(resume_session_id)
            if not pending_ids:
                return {
                    "status": "no_pending_papers",
                    "session_id": resume_session_id,
                    "message": "No pending papers to process"
                }
            
            id_list = pending_ids
            logger.info(f"Resuming session {resume_session_id} with {len(id_list)} pending papers")
        else:
            # 新的处理请求
            id_list: List[str] = [s.strip() for s in (ids or "").split(",") if s.strip()]
            if not id_list:
                raise HTTPException(status_code=400, detail="ids is required (comma-separated arXiv IDs)")
            
            # 创建新的会话
            session_id = resume_manager.create_session(
                source_file="api_upload",
                paper_ids=id_list
            )
            logger.info(f"Created new session {session_id} for {len(id_list)} papers")

        graph = request.app.state.data_processing_graph
        actual_thread_id = thread_id or _gen_thread_id("arxiv-by-id")
        
        # 配置包含会话信息
        config = {
            "configurable": {
                "thread_id": actual_thread_id,
                "id_list": id_list,
                "session_id": resume_session_id or session_id,
                "resume_mode": resume_session_id is not None
            }
        }

        preview = ",".join(id_list[:5]) + ("..." if len(id_list) > 5 else "")
        logger.info(f"API fetch-arxiv-by-id: thread_id={actual_thread_id}, ids_count={len(id_list)}, ids_sample={preview}, session_id={config['configurable']['session_id']}")

        result = await graph.ainvoke({}, config=config)
            
        status = result.get("processing_status")
        session_id_used = config['configurable']['session_id']
        
        logger.info(f"API fetch-arxiv-by-id done: status={status}, fetched={result.get('fetched', 0)}, inserted={result.get('inserted', 0)}, skipped={result.get('skipped', 0)}, session_id={session_id_used}")
        
        # 根据处理状态返回不同响应
        if status == "completed":
            return {
                "status": "success",
                "session_id": session_id_used,
                "inserted": result.get("inserted", 0),
                "skipped": result.get("skipped", 0),
                "fetched": result.get("fetched", 0),
                "total_papers": result.get("total_papers", 0),
                "processed_papers": len(result.get("processed_paper_ids", [])),
                "failed_papers": len(result.get("failed_paper_ids", [])),
                "message": "All papers processed successfully"
            }
        elif status == "batch_completed":
            # 流式处理中的批次完成状态
            current_batch = result.get("current_batch_index", 0)
            total_papers = result.get("total_papers", 0)
            processed_count = len(result.get("processed_paper_ids", []))
            failed_count = len(result.get("failed_paper_ids", []))
            
            return {
                "status": "batch_completed",
                "session_id": session_id_used,
                "inserted": result.get("inserted", 0),
                "skipped": result.get("skipped", 0),
                "current_batch": current_batch,
                "total_papers": total_papers,
                "processed_papers": processed_count,
                "failed_papers": failed_count,
                "progress_percentage": round((processed_count / total_papers) * 100, 2) if total_papers > 0 else 0,
                "message": f"Batch {current_batch} completed. Processing continues automatically."
            }
        elif status == "api_quota_exhausted":
            return {
                "status": "api_quota_exhausted",
                "session_id": session_id_used,
                "inserted": result.get("inserted", 0),
                "skipped": result.get("skipped", 0),
                "fetched": result.get("fetched", 0),
                "total_papers": result.get("total_papers", 0),
                "processed_papers": len(result.get("processed_paper_ids", [])),
                "failed_papers": len(result.get("failed_paper_ids", [])),
                "message": "Tavily API quota exhausted. Use the session_id to resume processing later.",
                "resume_endpoint": f"/data/fetch-arxiv-by-id?resume_session_id={session_id_used}"
            }
        elif status == "error":
            raise HTTPException(status_code=500, detail=result.get("error_message", "unknown error"))

        return {
            "status": "ok",
            "session_id": session_id_used,
            "message": f"graph finished with status={status}",
            "inserted": result.get("inserted", 0),
            "skipped": result.get("skipped", 0),
            "fetched": result.get("fetched", 0),
            "total_papers": result.get("total_papers", 0),
            "processed_papers": len(result.get("processed_paper_ids", [])),
            "failed_papers": len(result.get("failed_paper_ids", []))
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in fetch_arxiv_by_id_api: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}") 


# ---------------- Resume Management Endpoints ----------------

@router.get("/sessions")
async def list_sessions():
    """List all processing sessions."""
    try:
        sessions = resume_manager.list_sessions()
        return {
            "status": "success",
            "sessions": [
                {
                    "session_id": session.session_id,
                    "status": session.status.value if hasattr(session.status, 'value') else session.status,
                    "total_papers": session.total_papers,
                    "completed_papers": session.processed_papers,
                    "failed_papers": session.failed_papers,
                    "pending_papers": session.total_papers - session.processed_papers - session.failed_papers - session.skipped_papers,
                    "total_inserted": getattr(session, 'total_inserted', 0),
                    "total_skipped": getattr(session, 'total_skipped', 0),
                    "created_at": session.start_time,
                    "updated_at": session.last_update_time,
                    "error_message": session.error_message
                }
                for session in sessions
            ]
        }
    except Exception as e:
        logger.error(f"Error listing sessions: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/sessions/{session_id}")
async def get_session_details(session_id: str):
    """Get detailed information about a specific session."""
    try:
        session = resume_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        
        # Load paper records separately
        records = resume_manager._load_records(session_id)
        
        return {
            "status": "success",
            "session": {
                "session_id": session.session_id,
                "status": session.status.value if hasattr(session.status, 'value') else session.status,
                "total_papers": session.total_papers,
                "total_inserted": getattr(session, 'total_inserted', 0),
                "total_skipped": getattr(session, 'total_skipped', 0),
                "created_at": session.start_time,
                "updated_at": session.last_update_time,
                "error_message": session.error_message,
                "papers": {
                    paper_id: {
                        "status": paper.status.value if hasattr(paper.status, 'value') else paper.status,
                        "error_message": paper.error_message,
                        "processing_time": paper.processing_time,
                        "created_at": paper.last_attempt_time,
                        "updated_at": paper.last_attempt_time
                    }
                    for paper_id, paper in records.items()
                }
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session details: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a processing session."""
    try:
        success = resume_manager.delete_session(session_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        
        return {
            "status": "success",
            "message": f"Session {session_id} deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/sessions/{session_id}/pending-papers")
async def get_pending_papers(session_id: str):
    """Get list of pending paper IDs for a session."""
    try:
        pending_ids = resume_manager.get_pending_paper_ids(session_id)
        if pending_ids is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        
        return {
            "status": "success",
            "session_id": session_id,
            "pending_paper_ids": pending_ids,
            "count": len(pending_ids)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting pending papers: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


# ---------------- Enrichment endpoint for existing affiliations (QS) ----------------

@router.post("/enrich-affiliations-qsrank")
async def enrich_affiliations_qs_api(request: Request, force_country: bool = False, force_rank: bool = False) -> dict:
    """Enrich existing affiliations with QS country and rankings (2025/2024).

    - Matches by institution name ignoring spaces/case.
    - Updates country only if currently empty (or forced by force_country=true).
    - Upserts affiliation_rankings for QS 2025 and QS 2024 (or overwrite if force_rank=true).
    """
    try:
        import os, re
        from src.db.database import DatabaseManager
        from src.agent.data_graph import _get_qs_map, _get_qs_names, _ensure_qs_ranking_systems, _find_qs_record_for_aff

        db_uri = os.getenv("DATABASE_URL")
        if not db_uri:
            raise HTTPException(status_code=500, detail="DATABASE_URL not set")

        await DatabaseManager.initialize(db_uri)
        pool = await DatabaseManager.get_pool()

        qs_map = _get_qs_map()
        qs_names = _get_qs_names()
        if not qs_map:
            logger.warning("QS CSV mapping is empty or missing; no enrichment will be applied.")

        total = 0
        matched = 0
        country_updated = 0
        ranks_2025 = 0
        ranks_2024 = 0

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # ensure ranking systems present
                sys_ids = await _ensure_qs_ranking_systems(cur)

                # iterate affiliations by batches
                batch = 1000
                last_id = 0
                while True:
                    await cur.execute(
                        "SELECT id, aff_name, COALESCE(country, '') FROM affiliations WHERE id > %s ORDER BY id ASC LIMIT %s",
                        (last_id, batch),
                    )
                    rows = await cur.fetchall()
                    if not rows:
                        break
                    for aff_id, aff_name, country in rows:
                        total += 1
                        name = (aff_name or "").strip()
                        rec = _find_qs_record_for_aff(name, qs_map, qs_names)
                        if not rec:
                            last_id = aff_id
                            continue
                        matched += 1
                        # country
                        rec_country = (rec.get("country") or "").strip()
                        if rec_country and (force_country or not country):
                            await cur.execute(
                                "UPDATE affiliations SET country = %s WHERE id = %s",
                                (rec_country, aff_id),
                            )
                            country_updated += 1
                        # rankings 2025/2024
                        if rec.get("r2025") and sys_ids.get(2025):
                            if force_rank:
                                await cur.execute(
                                    "DELETE FROM affiliation_rankings WHERE aff_id = %s AND rank_system_id = %s AND rank_year = %s",
                                    (aff_id, sys_ids[2025], 2025),
                                )
                            await cur.execute(
                                """
                                INSERT INTO affiliation_rankings (aff_id, rank_system_id, rank_value, rank_year)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (aff_id, rank_system_id, rank_year) DO NOTHING
                                """,
                                (aff_id, sys_ids[2025], str(rec["r2025"]).strip(), 2025),
                            )
                            ranks_2025 += 1
                        if rec.get("r2024") and sys_ids.get(2024):
                            if force_rank:
                                await cur.execute(
                                    "DELETE FROM affiliation_rankings WHERE aff_id = %s AND rank_system_id = %s AND rank_year = %s",
                                    (aff_id, sys_ids[2024], 2024),
                                )
                            await cur.execute(
                                """
                                INSERT INTO affiliation_rankings (aff_id, rank_system_id, rank_value, rank_year)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (aff_id, rank_system_id, rank_year) DO NOTHING
                                """,
                                (aff_id, sys_ids[2024], str(rec["r2024"]).strip(), 2024),
                            )
                            ranks_2024 += 1
                        last_id = aff_id

        logger.info(
            f"API enrich-affiliations-qsrank done: seen={total}, matched={matched}, country_updated={country_updated}, ranks_2025={ranks_2025}, ranks_2024={ranks_2024}"
        )
        return {
            "status": "success",
            "seen": total,
            "matched": matched,
            "country_updated": country_updated,
            "ranks_2025": ranks_2025,
            "ranks_2024": ranks_2024,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in enrich_affiliations_qs_api: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}") 


# ---------------- Temporary backfill endpoint: latest_time for author_affiliation ----------------


# ---------------- Temporary ORCID enrichment endpoint for existing data ----------------

@router.post("/enrich-orcid")
async def enrich_orcid_api(
    request: Request,
    only_missing: bool = True,
    batch_size: int = 200,
    max_rows: int = 2000,
) -> dict:
    """Backfill ORCID for existing authors/affiliations.

    - For each existing (author_id, affiliation_id), query ORCID with author_name_en + aff_name.
    - Strict name match; institution fuzzy match consistent with QS alignment (normalized variants + similarity).
    - Update authors.orcid (only if NULL) and author_affiliation.role/start_date/end_date conservatively.
    """
    try:
        import os
        import asyncio
        from typing import Any, Dict, Optional
        from src.db.database import DatabaseManager
        from src.agent.utils import orcid_search_and_pick, best_aff_match_for_institution, parse_orcid_date

        db_uri = os.getenv("DATABASE_URL")
        if not db_uri:
            raise HTTPException(status_code=500, detail="DATABASE_URL not set")

        await DatabaseManager.initialize(db_uri)
        pool = await DatabaseManager.get_pool()

        # concurrency control for ORCID lookups
        try:
            orcid_max = int(os.getenv("ORCID_MAX_CONCURRENCY", "5"))
        except Exception:
            orcid_max = 5
        sem = asyncio.Semaphore(orcid_max)

        async def lookup_one(author_name: str, aff_name: str) -> Optional[Dict[str, Any]]:
            async with sem:
                info = await asyncio.to_thread(orcid_search_and_pick, author_name, aff_name, 10)
                if not info:
                    return None
                best = best_aff_match_for_institution(aff_name, info)
                if not best:
                    return None
                    
                # Combine role and department for complete role information
                role_title = (best.get("role") or "").strip()
                department = (best.get("department") or "").strip()
                
                # Only store actual roles, not department names as roles
                if role_title and department:
                    role = f"{role_title} ({department})"
                elif role_title:
                    role = role_title
                else:
                    # Don't use department as role if no actual role exists
                    role = None
                    
                sd = parse_orcid_date(best.get("start_date") or "")
                ed = parse_orcid_date(best.get("end_date") or "")
                return {"orcid": info.get("orcid_id"), "role": role, "start_date": sd, "end_date": ed}

        total = 0
        matched = 0
        author_orcid_updated = 0
        role_updated = 0
        start_updated = 0
        end_updated = 0

        last_id = 0
        processed = 0
        while processed < max_rows:
            # fetch a batch of rows to process outside of transaction
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    where_missing = " AND (aa.role IS NULL OR aa.start_date IS NULL OR aa.end_date IS NULL OR a.orcid IS NULL)" if only_missing else ""
                    await cur.execute(
                        f"""
                        SELECT aa.id, aa.author_id, aa.affiliation_id, aa.role, aa.start_date, aa.end_date,
                               a.author_name_en, a.orcid, f.aff_name
                        FROM author_affiliation aa
                        JOIN authors a ON a.id = aa.author_id
                        JOIN affiliations f ON f.id = aa.affiliation_id
                        WHERE aa.id > %s{where_missing}
                        ORDER BY aa.id ASC
                        LIMIT %s
                        """,
                        (last_id, batch_size),
                    )
                    rows = await cur.fetchall()
            if not rows:
                break

            # parallel ORCID lookups (network) without holding DB transaction
            tasks = []
            for rid, author_id, aff_id, role0, sd0, ed0, author_name, author_orcid, aff_name in rows:
                total += 1
                tasks.append(lookup_one(author_name or "", aff_name or ""))
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # write updates serially to avoid deadlocks
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    for (row, res) in zip(rows, results):
                        rid, author_id, aff_id, role0, sd0, ed0, author_name, author_orcid, aff_name = row
                        last_id = rid
                        if isinstance(res, Exception) or not res:
                            continue
                        matched += 1
                        # authors.orcid
                        if res.get("orcid"):
                            try:
                                await cur.execute(
                                    "UPDATE authors SET orcid = COALESCE(orcid, %s) WHERE id = %s",
                                    (res["orcid"], author_id),
                                )
                                # count if previously null
                                if not author_orcid:
                                    author_orcid_updated += 1
                            except Exception:
                                pass
                        # role/start/end
                        if res.get("role"):
                            try:
                                if only_missing:
                                    # Only update if current value is NULL
                                    await cur.execute(
                                        "UPDATE author_affiliation SET role = COALESCE(role, %s) WHERE author_id = %s AND affiliation_id = %s",
                                        (res["role"], author_id, aff_id),
                                    )
                                    # Count only if originally NULL
                                    if not role0:
                                        role_updated += 1
                                else:
                                    # Direct overwrite
                                    await cur.execute(
                                        "UPDATE author_affiliation SET role = %s WHERE author_id = %s AND affiliation_id = %s",
                                        (res["role"], author_id, aff_id),
                                    )
                                    # Count all updates in overwrite mode
                                    role_updated += 1
                            except Exception:
                                pass
                        if res.get("start_date"):
                            try:
                                if only_missing:
                                    # Use LEAST to keep the earliest date, only update if NULL
                                    await cur.execute(
                                        "UPDATE author_affiliation SET start_date = LEAST(COALESCE(start_date, %s), %s) WHERE author_id = %s AND affiliation_id = %s",
                                        (res["start_date"], res["start_date"], author_id, aff_id),
                                    )
                                    # Count only if originally NULL
                                    if not sd0:
                                        start_updated += 1
                                else:
                                    # Direct overwrite with earliest date
                                    await cur.execute(
                                        "UPDATE author_affiliation SET start_date = LEAST(COALESCE(start_date, %s), %s) WHERE author_id = %s AND affiliation_id = %s",
                                        (res["start_date"], res["start_date"], author_id, aff_id),
                                    )
                                    # Count all updates in overwrite mode
                                    start_updated += 1
                            except Exception:
                                pass
                        if res.get("end_date"):
                            try:
                                if only_missing:
                                    # Use GREATEST to keep the latest date, only update if NULL
                                    await cur.execute(
                                        "UPDATE author_affiliation SET end_date = GREATEST(COALESCE(end_date, %s), %s) WHERE author_id = %s AND affiliation_id = %s",
                                        (res["end_date"], res["end_date"], author_id, aff_id),
                                    )
                                    # Count only if originally NULL
                                    if not ed0:
                                        end_updated += 1
                                else:
                                    # Direct overwrite with latest date
                                    await cur.execute(
                                        "UPDATE author_affiliation SET end_date = GREATEST(COALESCE(end_date, %s), %s) WHERE author_id = %s AND affiliation_id = %s",
                                        (res["end_date"], res["end_date"], author_id, aff_id),
                                    )
                                    # Count all updates in overwrite mode
                                    end_updated += 1
                            except Exception:
                                pass
                                pass
                        processed += 1
                        if processed >= max_rows:
                            break

        logger.info(
            f"API enrich-orcid done: seen={total}, matched={matched}, author_orcid_updated={author_orcid_updated}, role_updated={role_updated}, start_updated={start_updated}, end_updated={end_updated}"
        )
        return {
            "status": "success",
            "seen": total,
            "matched": matched,
            "author_orcid_updated": author_orcid_updated,
            "role_updated": role_updated,
            "start_updated": start_updated,
            "end_updated": end_updated,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in enrich_orcid_api: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/enrich-orcid-author")
async def enrich_orcid_for_author(request: Request, author_id: int) -> dict:
    """Enrich a single author's ORCID by author_id.
    
    Args:
        author_id: The ID of the author to enrich
        
    Process:
    - Fetch author's name and known affiliations from DB
    - Search ORCID candidates with strict name match
    - Update author.orcid if found
    - Update author_affiliation.role/start_date/end_date based on ORCID data
    """
    from src.db.database import DatabaseManager
    from src.agent.utils import orcid_search_and_pick, best_aff_match_for_institution, parse_orcid_date
    import os
    
    try:
        db_uri = os.getenv("DATABASE_URL")
        await DatabaseManager.initialize(db_uri)
        pool = await DatabaseManager.get_pool()
        
        orcid_updated = False
        affiliations_updated = 0
        
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Get author info
                await cur.execute(
                    "SELECT author_name_en, orcid FROM authors WHERE id = %s",
                    (author_id,)
                )
                author_row = await cur.fetchone()
                if not author_row:
                    raise HTTPException(status_code=404, detail=f"Author {author_id} not found")
                
                author_name, current_orcid = author_row
                
                # Get author's affiliations
                await cur.execute(
                    """
                    SELECT aa.affiliation_id, a.aff_name, aa.role, aa.start_date, aa.end_date
                    FROM author_affiliation aa 
                    JOIN affiliations a ON aa.affiliation_id = a.id 
                    WHERE aa.author_id = %s
                    """,
                    (author_id,)
                )
                aff_rows = await cur.fetchall()
                
                if aff_rows:
                    # Use first affiliation for ORCID search
                    aff_name = aff_rows[0][1]
                    
                    # Search ORCID
                    info = orcid_search_and_pick(author_name, aff_name, 10)
                    if info:
                        # Update author ORCID if not exists
                        orcid_id = info.get("orcid_id")
                        if orcid_id and not current_orcid:
                            await cur.execute(
                                "UPDATE authors SET orcid = %s WHERE id = %s",
                                (orcid_id, author_id)
                            )
                            orcid_updated = True
                            current_orcid = orcid_id
                        
                        # Update affiliation data for each affiliation
                        for aff_id, aff_name_db, current_role, current_start, current_end in aff_rows:
                            # Find best matching affiliation in ORCID data
                            best = best_aff_match_for_institution(aff_name_db, info)
                            if best:
                                # Prepare update data
                                role_title = (best.get("role") or "").strip()
                                department = (best.get("department") or "").strip()
                                
                                # Combine role and department for complete role information
                                if role_title and department:
                                    role = f"{role_title} ({department})"
                                elif role_title:
                                    role = role_title
                                else:
                                    role = None
                                    
                                start_date = parse_orcid_date(best.get("start_date") or "")
                                end_date = parse_orcid_date(best.get("end_date") or "")
                                
                                # Update role if not exists
                                if role and not current_role:
                                    await cur.execute(
                                        "UPDATE author_affiliation SET role = %s WHERE author_id = %s AND affiliation_id = %s",
                                        (role, author_id, aff_id)
                                    )
                                    affiliations_updated += 1
                                
                                # Update start_date (keep earliest)
                                if start_date:
                                    await cur.execute(
                                        "UPDATE author_affiliation SET start_date = LEAST(COALESCE(start_date, %s), %s) WHERE author_id = %s AND affiliation_id = %s",
                                        (start_date, start_date, author_id, aff_id)
                                    )
                                
                                # Update end_date (keep latest)
                                if end_date:
                                    await cur.execute(
                                        "UPDATE author_affiliation SET end_date = GREATEST(COALESCE(end_date, %s), %s) WHERE author_id = %s AND affiliation_id = %s",
                                        (end_date, end_date, author_id, aff_id)
                                    )
        
        return {
            "status": "success",
            "author_id": author_id,
            "author_name": author_name,
            "orcid_updated": orcid_updated,
            "current_orcid": current_orcid,
            "affiliations_updated": affiliations_updated
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in enrich_orcid_for_author: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")