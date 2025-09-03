"""
API router for arXiv data processing operations.
Provides a single endpoint to fetch arXiv papers and store them in the database.
"""

import logging
import os
import asyncio
from typing import Optional, List
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Query, UploadFile, File
from pydantic import BaseModel

from src.agent.resume_manager import resume_manager
from src.db.database import DatabaseManager
from src.agent.utils import search_person_role_with_tavily, search_person_homepage_with_tavily, _extract_homepage_link_with_llm
from .models import SupplementRolesRequest, DataEnrichmentRequest, ProcessRoleRequest

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
            f"[API] fetch-arxiv-today starting: thread_id={config['configurable']['thread_id']}, range={start_date}..{end_date}, "
            f"categories={cats_label}, max_results={config['configurable'].get('max_results', 200)}"
        )

        # 初始调用图
        result = await graph.ainvoke({}, config=config)

        status = result.get("processing_status")
        logger.info(f"[API] fetch-arxiv-today completed: status={status}, fetched={result.get('fetched', 0)}, inserted={result.get('inserted', 0)}, skipped={result.get('skipped', 0)}")
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
            logger.info(f"[SESSION] Resuming session {resume_session_id} with {len(id_list)} pending papers")
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
            logger.info(f"[SESSION] Created new session {session_id} for {len(id_list)} papers")

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
        logger.info(f"[API] fetch-arxiv-by-id starting: thread_id={actual_thread_id}, ids_count={len(id_list)}, ids_sample={preview}, session_id={config['configurable']['session_id']}")

        # 初始调用图
        result = await graph.ainvoke({}, config=config)
            
        status = result.get("processing_status")
        session_id_used = config['configurable']['session_id']
        
        logger.info(f"[API] fetch-arxiv-by-id completed: status={status}, fetched={result.get('fetched', 0)}, inserted={result.get('inserted', 0)}, skipped={result.get('skipped', 0)}, session_id={session_id_used}")
        
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


@router.post("/upload-papers-json")
async def upload_papers_json(request: Request, file: UploadFile = File(...)):
    """Upload a JSON file containing paper IDs and start batch processing.
    
    JSON file format:
    {
        "paper_ids": ["2301.00001", "2301.00002", ...],
        "batch_size": 10  // optional, default is 10
    }
    or simple array format:
    ["2301.00001", "2301.00002", ...]
    """
    import json
    import asyncio
    from datetime import datetime, timezone
    
    try:
        # Validate file type
        if not file.filename.endswith('.json'):
            raise HTTPException(status_code=400, detail="File must be a JSON file")
        
        # Read file content
        content = await file.read()
        try:
            data = json.loads(content.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON format: {str(e)}")
        
        # Parse paper ID list
        if isinstance(data, list):
            # Simple array format
            paper_ids = data
            batch_size = 10
        elif isinstance(data, dict):
            # Object format
            paper_ids = data.get("paper_ids", [])
            batch_size = data.get("batch_size", 10)
        else:
            raise HTTPException(status_code=400, detail="JSON must be an array or object with 'paper_ids' field")
        
        # Validate paper ID list
        if not paper_ids or not isinstance(paper_ids, list):
            raise HTTPException(status_code=400, detail="paper_ids must be a non-empty list")
        
        # Clean and validate paper IDs
        cleaned_ids = []
        for pid in paper_ids:
            if isinstance(pid, str) and pid.strip():
                cleaned_ids.append(pid.strip())
        
        if not cleaned_ids:
            raise HTTPException(status_code=400, detail="No valid paper IDs found")
        
        # Validate batch size
        if not isinstance(batch_size, int) or batch_size < 1 or batch_size > 100:
            batch_size = 10
        
        logger.info(f"[UPLOAD] Processing JSON upload: {len(cleaned_ids)} papers, batch_size={batch_size}")
        
        # Create batch processing session
        session_id = resume_manager.create_session(
            source_file=file.filename,
            paper_ids=cleaned_ids
        )
        
        # Start single LangGraph processing (internal batching)
        async def process_papers():
            """Single LangGraph processing with internal batching"""
            try:
                graph = request.app.state.data_processing_graph
                
                # Build config for single processing call
                config = {
                    "configurable": {
                        "thread_id": session_id,
                        "id_list": cleaned_ids,
                        "session_id": session_id,
                        "resume_mode": False,
                        "source_file": file.filename
                    }
                }
                
                logger.info(f"[PROCESSING] Starting LangGraph processing for {len(cleaned_ids)} papers")
                
                # Execute single processing call (LangGraph handles internal batching)
                result = await graph.ainvoke({}, config=config)
                
                # Log completion with results
                inserted = result.get("inserted", 0)
                skipped = result.get("skipped", 0)
                fetched = result.get("fetched", 0)
                successful_batches = result.get("successful_batches", 0)
                total_batches = result.get("total_batches", 0)
                
                logger.info(f"[PROCESSING] ✅ Completed: {fetched} fetched, {inserted} inserted, {skipped} skipped")
                logger.info(f"[PROCESSING] Batch summary: {successful_batches}/{total_batches} batches successful")
                
                # Update session status
                if result.get("processing_status") == "completed":
                    resume_manager.update_session_status(session_id, "completed")
                elif result.get("processing_status") == "error":
                    resume_manager.update_session_status(session_id, "error")
                
            except Exception as e:
                logger.error(f"Fatal error in processing for session {session_id}: {str(e)}")
                resume_manager.update_session_status(session_id, "error")
        
        # Start background task
        asyncio.create_task(process_papers())
        
        return {
            "status": "success",
            "message": "File uploaded and batch processing started",
            "session_id": session_id,
            "total_papers": len(cleaned_ids),
            "batch_size": batch_size,
            "filename": file.filename
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing uploaded file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process uploaded file: {str(e)}")


@router.post("/supplement-roles")
async def supplement_roles_api(
    request: Request,
    body: SupplementRolesRequest
) -> dict:
    """Supplement NULL role fields in author_affiliation table using Tavily API.
    
    Args:
        batch_size: Number of records to process in each batch (default: 50)
        max_records: Maximum number of records to process (default: 5000)
        start_id: Start ID for processing range (inclusive, optional)
        end_id: End ID for processing range (inclusive, optional)
        
    Returns:
        Dict with processing status and statistics
    """
    logger.info("=== SUPPLEMENT ROLES API CALLED ===")
    
    try:
        # Check if Tavily is enabled
        tavily_enabled = os.getenv("TAVILY_ENABLED", "false").lower() in ("true", "1", "yes", "on")
        if not tavily_enabled:
            raise HTTPException(
                status_code=400, 
                detail="Tavily API is not enabled. Please set TAVILY_ENABLED=true in your environment."
            )
        
        # Initialize database connection
        db_uri = os.getenv("DATABASE_URL")
        if not db_uri:
            raise HTTPException(status_code=500, detail="Database URL not configured")
        
        await DatabaseManager.initialize(db_uri)
        pool = await DatabaseManager.get_pool()
        
        # Statistics tracking
        total_processed = 0
        total_updated = 0
        total_failed = 0
        api_quota_exhausted = False
        
        # Batch processing delay (from environment or default)
        batch_delay = float(os.getenv("TAVILY_BATCH_DELAY", "2.0"))
        
        # Extract parameters from request body
        batch_size = body.batch_size
        max_records = body.max_records
        start_id = body.start_id
        end_id = body.end_id
        
        logger.info(f"Starting role supplementation with batch_size={batch_size}, max_records={max_records}, start_id={start_id}, end_id={end_id}")
        
        # Get total count of records to process (only NULL roles in specified range)
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Build WHERE clause for ID range filtering and NULL roles
                where_conditions = ["role IS NULL"]
                params = []
                
                if start_id is not None:
                    where_conditions.append("id >= %s")
                    params.append(start_id)
                
                if end_id is not None:
                    where_conditions.append("id <= %s")
                    params.append(end_id)
                
                where_clause = "WHERE " + " AND ".join(where_conditions)
                
                query = f"SELECT COUNT(*) FROM author_affiliation {where_clause}"
                await cur.execute(query, params)
                total_null_records = (await cur.fetchone())[0]
        
        logger.info(f"Total records with NULL roles in specified range: {total_null_records}")
        
        # Process records in batches, only fetching NULL role records in specified range
        offset = 0
        
        while offset < total_null_records and total_processed < max_records and not api_quota_exhausted:
            # Fetch a batch of records (only NULL roles in specified range)
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    # Build WHERE clause for ID range filtering and NULL roles
                    where_conditions = ["aa.role IS NULL"]
                    params = []
                    
                    if start_id is not None:
                        where_conditions.append("aa.id >= %s")
                        params.append(start_id)
                    
                    if end_id is not None:
                        where_conditions.append("aa.id <= %s")
                        params.append(end_id)
                    
                    where_clause = "WHERE " + " AND ".join(where_conditions)
                    
                    # Add LIMIT and OFFSET parameters
                    params.extend([batch_size, offset])
                    
                    query = f"""
                        SELECT aa.id, aa.author_id, aa.affiliation_id, 
                               a.author_name_en, af.aff_name, aa.role
                        FROM author_affiliation aa
                        JOIN authors a ON a.id = aa.author_id
                        JOIN affiliations af ON af.id = aa.affiliation_id
                        {where_clause}
                        ORDER BY aa.id ASC
                        LIMIT %s OFFSET %s
                    """
                    
                    await cur.execute(query, params)
                    rows = await cur.fetchall()
            
            if not rows:
                logger.info("No more records found")
                break
            
            logger.info(f"Processing batch of {len(rows)} records (offset: {offset})...")
            
            # Process each record in the batch
            batch_updated = 0
            batch_failed = 0
            batch_skipped = 0
            batch_processed = 0  # Count of records actually processed (called Tavily API)
            
            for i, (aa_id, author_id, affiliation_id, author_name, aff_name, current_role) in enumerate(rows):
                # All records should have NULL role since we filtered for them
                # No need to check current_role since query already filters for NULL roles
                
                try:
                    # Add delay between API calls to avoid rate limiting
                    if total_processed > 0:  # Add delay for all API calls except the first
                        await asyncio.sleep(batch_delay)
                    
                    # Call Tavily API to get role information
                    tavily_result = await search_person_role_with_tavily(author_name, aff_name)
                    batch_processed += 1  # Count this as a processed record
                    
                    if tavily_result and tavily_result.get("search_successful"):
                        extracted_role = tavily_result.get("extracted_role")
                        if extracted_role and extracted_role.strip():
                            # Update the role in database
                            async with pool.connection() as conn:
                                async with conn.cursor() as cur:
                                    await cur.execute(
                                        "UPDATE author_affiliation SET role = %s WHERE id = %s",
                                        (extracted_role.strip(), aa_id)
                                    )
                                    await conn.commit()
                            
                            batch_updated += 1
                            logger.info(f"Updated role for {author_name} at {aff_name}: {extracted_role}")
                        else:
                            batch_failed += 1
                            logger.debug(f"No role extracted for {author_name} at {aff_name}")
                    else:
                        batch_failed += 1
                        logger.debug(f"Tavily search failed for {author_name} at {aff_name}")
                    
                    # Check if we've reached the max_records limit
                    if (total_processed + batch_processed) >= max_records:
                        logger.info(f"Reached max_records limit ({max_records}), stopping processing")
                        break
                
                except Exception as e:
                    batch_processed += 1  # Count this as a processed record even if it failed
                    error_msg = str(e).lower()
                    # Check for API quota exhaustion
                    if "quota" in error_msg or "limit" in error_msg or "exceeded" in error_msg:
                        logger.error(f"Tavily API quota exhausted: {e}")
                        api_quota_exhausted = True
                        break
                    else:
                        batch_failed += 1
                        logger.error(f"Error processing {author_name} at {aff_name}: {e}")
                    
                    # Check if we've reached the max_records limit
                    if (total_processed + batch_processed) >= max_records:
                        logger.info(f"Reached max_records limit ({max_records}), stopping processing")
                        break
            
            # Update counters
            total_processed += batch_processed  # Only count records that actually called Tavily API
            total_updated += batch_updated
            total_failed += batch_failed
            offset += batch_size
            
            logger.info(f"Batch completed: {batch_updated} updated, {batch_failed} failed, {batch_skipped} skipped")
            
            # Break if API quota is exhausted
            if api_quota_exhausted:
                break
        
        # Prepare response
        status = "completed" if not api_quota_exhausted else "quota_exhausted"
        message = f"Role supplementation {status}. Processed: {total_processed}, Updated: {total_updated}, Failed: {total_failed}"
        
        if api_quota_exhausted:
            message += ". Tavily API quota exhausted."
        
        logger.info(f"Role supplementation finished: {message}")
        
        return {
            "status": status,
            "message": message,
            "statistics": {
                "total_processed": total_processed,
                "total_updated": total_updated,
                "total_failed": total_failed,
                "api_quota_exhausted": api_quota_exhausted
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in role supplementation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Role supplementation failed: {str(e)}")


@router.post("/data-enrichment")
async def data_enrichment_api(body: DataEnrichmentRequest):
    """
    Enrich author data by fetching homepage links using Tavily API.
    
    This endpoint processes authors in the specified ID range and attempts to find
    their homepage links by querying Tavily API with the format:
    "What is the link to {author_name_en}'s homepage at {affiliation_name}?"
    
    The response from Tavily is then processed by an LLM to extract the unique link.
    """
    try:
        # Get environment variables
        batch_delay = float(os.getenv("TAVILY_BATCH_DELAY", "2.0"))
        
        # Extract parameters from request body
        batch_size = body.batch_size
        max_records = body.max_records
        start_id = body.start_id
        end_id = body.end_id
        
        logger.info(f"Starting data enrichment with batch_size={batch_size}, max_records={max_records}, start_id={start_id}, end_id={end_id}")
        
        # Initialize database manager
        db_manager = DatabaseManager()
        
        # Build WHERE clause for ID range filtering
        where_conditions = []
        params = []
        
        if start_id is not None:
            where_conditions.append("a.id >= %s")
            params.append(start_id)
        
        if end_id is not None:
            where_conditions.append("a.id <= %s")
            params.append(end_id)
        
        # Add condition for authors without homepage links
        where_conditions.append("a.homepage IS NULL")
        
        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        
        # Get total count of authors without homepage links in the specified range
        count_query = f"""
            SELECT COUNT(*) as total
            FROM authors a
            WHERE {where_clause}
        """
        
        async with db_manager.get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(count_query, params)
                total_null_records = (await cur.fetchone())[0]
        logger.info(f"Found {total_null_records} authors without homepage links in the specified range")
        
        if total_null_records == 0:
            return {
                "status": "completed",
                "message": "No authors found without homepage links in the specified range",
                "processed_count": 0,
                "updated_count": 0,
                "failed_count": 0,
                "api_quota_exhausted": False
            }
        
        # Initialize counters
        total_processed = 0
        total_updated = 0
        total_failed = 0
        offset = 0
        api_quota_exhausted = False
        
        # Process in batches
        while offset < total_null_records and total_processed < max_records and not api_quota_exhausted:
            # Calculate actual batch size
            remaining_records = min(total_null_records - offset, max_records - total_processed)
            current_batch_size = min(batch_size, remaining_records)
            
            # Query for authors without homepage links in the current batch
            query = f"""
                SELECT a.id, a.author_name_en, af.aff_name
                FROM authors a
                LEFT JOIN author_affiliation aa ON a.id = aa.author_id
                LEFT JOIN affiliations af ON aa.affiliation_id = af.id
                WHERE {where_clause}
                ORDER BY a.id
                LIMIT %s OFFSET %s
            """
            
            batch_params = params + [current_batch_size, offset]
            async with db_manager.get_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, batch_params)
                    authors = await cur.fetchall()
            
            logger.info(f"Processing batch {offset // batch_size + 1}: {len(authors)} authors")
            
            # Process each author in the batch
            batch_processed = 0
            batch_updated = 0
            batch_failed = 0
            
            for author in authors:
                try:
                    author_id = author[0]
                    author_name = author[1]
                    aff_name = author[2] or "unknown affiliation"
                    
                    batch_processed += 1
                    
                    # Call Tavily API to search for homepage link
                    search_result = await search_person_homepage_with_tavily(author_name, aff_name)
                    
                    if search_result and search_result.get('search_successful'):
                        # Extract homepage link from Tavily response
                        tavily_answer = search_result.get('answer', '')
                        
                        if tavily_answer:
                            # Use LLM to extract homepage link from Tavily response
                            tavily_results = search_result.get('results', [])
                            extracted_link = _extract_homepage_link_with_llm(
                                author_name, aff_name, tavily_answer, tavily_results
                            )
                            
                            if extracted_link:
                                logger.info(f"Extracted homepage link for {author_name}: {extracted_link}")
                                
                                # Update author's homepage in database
                                update_query = "UPDATE authors SET homepage = %s WHERE id = %s"
                                async with db_manager.get_connection() as conn:
                                    async with conn.cursor() as cur:
                                        await cur.execute(update_query, [extracted_link, author_id])
                                
                                batch_updated += 1
                                logger.info(f"Updated homepage for author {author_id}: {author_name}")
                            else:
                                logger.info(f"LLM could not extract valid homepage link for {author_name}")
                        else:
                            logger.info(f"No homepage answer found for {author_name}")
                    else:
                        # Check if search failed due to quota exhaustion
                        if search_result and search_result.get('error') == 'API quota exhausted':
                            logger.error(f"Tavily API quota exhausted while processing {author_name}")
                            api_quota_exhausted = True
                            break
                        else:
                            logger.warning(f"Homepage search failed for {author_name}: {search_result.get('error') if search_result else 'Unknown error'}")
                    
                    # Apply delay between requests
                    await asyncio.sleep(batch_delay)
                    
                    # Check if we've reached the max_records limit
                    if (total_processed + batch_processed) >= max_records:
                        logger.info(f"Reached max_records limit ({max_records}), stopping processing")
                        break
                
                except Exception as e:
                    batch_processed += 1
                    error_msg = str(e).lower()
                    # Check for API quota exhaustion
                    if "quota" in error_msg or "limit" in error_msg or "exceeded" in error_msg:
                        logger.error(f"Tavily API quota exhausted: {e}")
                        api_quota_exhausted = True
                        break
                    else:
                        batch_failed += 1
                        logger.error(f"Error processing {author_name} at {aff_name}: {e}")
                    
                    # Check if we've reached the max_records limit
                    if (total_processed + batch_processed) >= max_records:
                        logger.info(f"Reached max_records limit ({max_records}), stopping processing")
                        break
            
            # Update counters
            total_processed += batch_processed
            total_updated += batch_updated
            total_failed += batch_failed
            offset += batch_size
            
            logger.info(f"Batch completed: {batch_updated} updated, {batch_failed} failed")
            
            # Break if API quota is exhausted
            if api_quota_exhausted:
                break
        
        # Prepare response
        status = "completed" if not api_quota_exhausted else "quota_exhausted"
        message = f"Data enrichment {status}. Processed: {total_processed}, Updated: {total_updated}, Failed: {total_failed}"
        
        if api_quota_exhausted:
            message += ". Tavily API quota exhausted."
        
        logger.info(f"Data enrichment finished: {message}")
        
        return {
            "status": status,
            "message": message,
            "processed_count": total_processed,
            "updated_count": total_updated,
            "failed_count": total_failed,
            "api_quota_exhausted": api_quota_exhausted
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in data enrichment: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Data enrichment failed: {str(e)}")


@router.post("/process-role")
async def process_role_api(body: ProcessRoleRequest):
    """
    Process role data by updating author_affiliation table's role field
    according to the role mapping table defined in resource/role_mapping.py.
    
    This endpoint processes author_affiliation records in the specified ID range
    and standardizes the role field values using predefined mappings.
    """
    try:
        # Import role mapping
        import sys
        import os
        sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        from resource.role_mapping import role_mapping
        
        # Extract parameters from request body
        batch_size = body.batch_size
        max_records = body.max_records
        start_id = body.start_id
        end_id = body.end_id
        
        logger.info(f"Starting role processing with batch_size={batch_size}, max_records={max_records}, start_id={start_id}, end_id={end_id}")
        
        # Initialize database manager
        db_manager = DatabaseManager()
        
        # Build WHERE clause for ID range filtering
        where_conditions = []
        params = []
        
        if start_id is not None:
            where_conditions.append("aa.id >= %s")
            params.append(start_id)
        
        if end_id is not None:
            where_conditions.append("aa.id <= %s")
            params.append(end_id)
        
        # Add condition for records with role data that needs processing
        where_conditions.append("aa.role IS NOT NULL AND aa.role != ''")
        
        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        
        # Get total count of author_affiliation records in the specified range
        count_query = f"""
            SELECT COUNT(*) as total
            FROM author_affiliation aa
            WHERE {where_clause}
        """
        
        async with db_manager.get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(count_query, params)
                total_records = (await cur.fetchone())[0]
        
        logger.info(f"Found {total_records} author_affiliation records with role data in the specified range")
        
        if total_records == 0:
            return {
                "status": "completed",
                "message": "No author_affiliation records found with role data in the specified range",
                "processed_count": 0,
                "updated_count": 0,
                "failed_count": 0
            }
        
        # Initialize counters
        total_processed = 0
        total_updated = 0
        total_failed = 0
        offset = 0
        
        # Process in batches
        while offset < total_records and total_processed < max_records:
            # Calculate actual batch size
            remaining_records = min(total_records - offset, max_records - total_processed)
            current_batch_size = min(batch_size, remaining_records)
            
            # Query for author_affiliation records in the current batch
            query = f"""
                SELECT aa.id, aa.role
                FROM author_affiliation aa
                WHERE {where_clause}
                ORDER BY aa.id
                LIMIT %s OFFSET %s
            """
            
            batch_params = params + [current_batch_size, offset]
            async with db_manager.get_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, batch_params)
                    records = await cur.fetchall()
            
            logger.info(f"Processing batch {offset // batch_size + 1}: {len(records)} records")
            
            # Process each record in the batch
            batch_processed = 0
            batch_updated = 0
            batch_failed = 0
            
            for record in records:
                try:
                    record_id = record[0]
                    current_role = record[1]
                    
                    batch_processed += 1
                    
                    # Check if current role needs mapping
                    mapped_role = None
                    current_role_lower = current_role.lower().strip()
                    
                    # Find matching role in mapping table
                    for original_role, standard_role in role_mapping.items():
                        if original_role.lower() in current_role_lower or current_role_lower in original_role.lower():
                            mapped_role = standard_role
                            break
                    
                    # If no exact match found, try partial matching
                    if not mapped_role:
                        for original_role, standard_role in role_mapping.items():
                            # Check for partial matches (keywords)
                            original_keywords = original_role.lower().split()
                            current_keywords = current_role_lower.split()
                            
                            # If any keyword from original role is found in current role
                            if any(keyword in current_role_lower for keyword in original_keywords):
                                mapped_role = standard_role
                                break
                    
                    # Update role if mapping found and different from current
                    if mapped_role and mapped_role != current_role:
                        logger.info(f"Mapping role '{current_role}' to '{mapped_role}' for record {record_id}")
                        
                        # Update role in database
                        update_query = "UPDATE author_affiliation SET role = %s WHERE id = %s"
                        async with db_manager.get_connection() as conn:
                            async with conn.cursor() as cur:
                                await cur.execute(update_query, [mapped_role, record_id])
                        
                        batch_updated += 1
                        logger.info(f"Updated role for record {record_id}: '{current_role}' -> '{mapped_role}'")
                    else:
                        logger.info(f"No mapping needed for role '{current_role}' in record {record_id}")
                    
                    # Check if we've reached the max_records limit
                    if (total_processed + batch_processed) >= max_records:
                        logger.info(f"Reached max_records limit ({max_records}), stopping processing")
                        break
                
                except Exception as e:
                    batch_processed += 1
                    batch_failed += 1
                    logger.error(f"Error processing record {record_id}: {e}")
                    
                    # Check if we've reached the max_records limit
                    if (total_processed + batch_processed) >= max_records:
                        logger.info(f"Reached max_records limit ({max_records}), stopping processing")
                        break
            
            # Update counters
            total_processed += batch_processed
            total_updated += batch_updated
            total_failed += batch_failed
            offset += batch_size
            
            logger.info(f"Batch completed: {batch_updated} updated, {batch_failed} failed")
        
        # Prepare response
        status = "completed"
        message = f"Role processing {status}. Processed: {total_processed}, Updated: {total_updated}, Failed: {total_failed}"
        
        logger.info(f"Role processing finished: {message}")
        
        return {
            "status": status,
            "message": message,
            "processed_count": total_processed,
            "updated_count": total_updated,
            "failed_count": total_failed
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in role processing: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Role processing failed: {str(e)}")