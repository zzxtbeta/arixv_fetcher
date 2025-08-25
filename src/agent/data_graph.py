"""
ArXiv data processing graph: fetch latest arXiv papers within a date window and persist into database.

- Query arXiv API with submittedDate/lastUpdatedDate range (search_query)
- Retrieve full metadata from arXiv Atom feed
- Extract affiliations from first-page PDF via LLM (parallel per paper using Send)
- Create normalized schema and persist authors/categories/affiliations associations
"""

import os
import logging
import asyncio
import re
import json
from datetime import datetime, timezone, timedelta, time as dt_time
from typing import Dict, Any, List, Optional
from difflib import SequenceMatcher

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import SystemMessage, HumanMessage

from src.agent.state import DataProcessingState
from src.db.database import DatabaseManager
from src.agent.prompts import AFFILIATION_SYSTEM_PROMPT, build_affiliation_user_prompt
from src.agent.utils import (
    # ArXiv utilities
    search_papers_by_ids, search_papers_by_range, search_papers_by_window, iso_to_date,
    # LLM utilities
    create_llm, download_first_page_text_with_retries,
    # ORCID utilities
    orcid_candidates_by_name, best_aff_match_for_institution, parse_orcid_date,
    normalize_aff_variants, norm_string,
    # QS utilities
    get_qs_map, get_qs_names, ensure_qs_ranking_systems, enrich_affiliation_from_qs,
    # Database utilities
    create_schema_if_not_exists,
    # Tavily utilities
    search_person_role_with_tavily
)
from src.agent.resume_manager import resume_manager, ProcessingStatus
from src.agent.openalex_utils import get_author_academic_metrics

logger = logging.getLogger(__name__)

# Bounded concurrency for Send tasks to avoid PDF/LLM rate limits
_AFF_MAX = int(os.getenv("AFFILIATION_MAX_CONCURRENCY", "5"))
_AFF_SEM = asyncio.Semaphore(_AFF_MAX)
# Bounded concurrency for ORCID lookups
_ORCID_MAX = int(os.getenv("ORCID_MAX_CONCURRENCY", "5"))
_ORCID_SEM = asyncio.Semaphore(_ORCID_MAX)

# Tavily API batch processing delay configuration
_TAVILY_BATCH_DELAY = float(os.getenv("TAVILY_BATCH_DELAY", "2.0"))

# Database batch processing concurrency control
_BATCH_MAX_CONCURRENCY = int(os.getenv("BATCH_MAX_CONCURRENCY", "3"))  # Limit concurrent batches for Supabase
_BATCH_SEM = asyncio.Semaphore(_BATCH_MAX_CONCURRENCY)

# ---------------------- Node Functions ----------------------

async def fetch_arxiv_today(state: DataProcessingState, config: RunnableConfig) -> DataProcessingState:
    """Fetch latest papers from arXiv by date window, explicit date range or id_list.
    
    Modified for streaming processing: handles batch fetching and processing.
    """
    try:
        cfg = config.get("configurable", {}) if isinstance(config, dict) else {}
        
        # 检查是否为恢复模式
        session_id = cfg.get("session_id")
        resume_mode = cfg.get("resume_mode", False)
        
        # 获取批处理配置
        batch_size = int(os.getenv("BATCH_SIZE", "10"))
        current_batch_index = state.get("current_batch_index", 0)
        
        # Optional id_list overrides window/range query
        id_list = cfg.get("id_list")
        if isinstance(id_list, str):
            id_list = [s.strip() for s in id_list.split(",") if s.strip()]

        categories: List[str] = cfg.get("categories") or [
            c.strip() for c in os.getenv("ARXIV_CATEGORIES", "cs.AI,cs.CV").split(",") if c.strip()
        ]
        days: int = int(cfg.get("days", 1))
        max_results: int = int(cfg.get("max_results", 200))
        start_date: Optional[str] = cfg.get("start_date")
        end_date: Optional[str] = cfg.get("end_date")
        
        # 如果是恢复模式，只处理待处理的论文
        if resume_mode and session_id:
            pending_papers = resume_manager.get_pending_papers(session_id)
            if pending_papers:
                id_list = pending_papers
                logger.info(f"Resume mode: processing {len(pending_papers)} pending papers")
            else:
                logger.info("Resume mode: no pending papers found")
                return {
                    "processing_status": "completed",
                    "raw_papers": [],
                    "fetched": 0,
                    "papers": [],
                    "categories": categories,
                    "session_id": session_id,
                    "resume_mode": resume_mode,
                    "processed_paper_ids": [],
                    "failed_paper_ids": [],
                    "api_exhausted": False,
                    "current_batch_index": 0,
                    "total_papers": 0,
                    "all_paper_ids": []
                }
        
        # 如果是新的批量处理且有id_list，创建会话
        if id_list and not session_id:
            session_id = resume_manager.create_session(
                source_file=cfg.get("source_file", "unknown"),
                paper_ids=id_list
            )
            logger.info(f"Created new processing session: {session_id}")

        # 流式处理逻辑：分批获取和处理论文
        if id_list:
            # 获取所有论文ID列表
            all_paper_ids = state.get("all_paper_ids", id_list)
            total_papers = len(all_paper_ids)
            
            # 计算当前批次的范围
            batch_start = current_batch_index * batch_size
            batch_end = min(batch_start + batch_size, total_papers)
            
            if batch_start >= total_papers:
                # 所有批次都已处理完成
                logger.info(f"All batches completed. Total papers processed: {total_papers}")
                return {
                    "processing_status": "completed",
                    "raw_papers": [],
                    "fetched": 0,
                    "papers": [],
                    "categories": categories,
                    "session_id": session_id,
                    "resume_mode": resume_mode,
                    "processed_paper_ids": state.get("processed_paper_ids", []),
                    "failed_paper_ids": state.get("failed_paper_ids", []),
                    "api_exhausted": False,
                    "current_batch_index": current_batch_index,
                    "total_papers": total_papers,
                    "all_paper_ids": all_paper_ids
                }
            
            # 获取当前批次的论文ID
            current_batch_ids = all_paper_ids[batch_start:batch_end]
            logger.info(f"Processing batch {current_batch_index + 1}/{(total_papers + batch_size - 1) // batch_size}: papers {batch_start + 1}-{batch_end}")
            
            # 获取当前批次的论文数据
            raw = await asyncio.to_thread(search_papers_by_ids, current_batch_ids)
            logger.info(f"arXiv fetch batch {current_batch_index + 1}: fetched {len(raw)} papers")
            
            return {
                "processing_status": "fetched",
                "raw_papers": raw,
                "fetched": len(raw),
                "papers": [],
                "categories": categories,
                "session_id": session_id,
                "resume_mode": resume_mode,
                "processed_paper_ids": state.get("processed_paper_ids", []),
                "failed_paper_ids": state.get("failed_paper_ids", []),
                "api_exhausted": False,
                "current_batch_index": current_batch_index,
                "total_papers": total_papers,
                "all_paper_ids": all_paper_ids
            }
        else:
            # 非ID列表模式：按日期范围或窗口获取（保持原有逻辑）
            if start_date and end_date:
                try:
                    sd = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    ed = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    start_dt = datetime.combine(sd.date(), dt_time(0, 0, tzinfo=timezone.utc))
                    end_dt = datetime.combine(ed.date(), dt_time(23, 59, tzinfo=timezone.utc))
                    raw = await asyncio.to_thread(search_papers_by_range, categories, start_dt, end_dt, max_results)
                    cats_label = ",".join(categories) if categories else "all"
                    logger.info(f"arXiv fetch by range: {start_date} to {end_date}, categories={cats_label}, fetched={len(raw)}")
                except Exception as e:
                    logger.error(f"Error in date range parsing, falling back to window: {e}")
                    raw = await asyncio.to_thread(search_papers_by_window, categories, days, max_results)
                    cats_label = ",".join(categories) if categories else "all"
                    logger.info(f"arXiv fetch by window (fallback): days={days}, categories={cats_label}, fetched={len(raw)}")
            else:
                raw = await asyncio.to_thread(search_papers_by_window, categories, days, max_results)
                cats_label = ",".join(categories) if categories else "all"
                logger.info(f"arXiv fetch by window: days={days}, categories={cats_label}, fetched={len(raw)}")
            
            return {
                "processing_status": "fetched",
                "raw_papers": raw,
                "fetched": len(raw),
                "papers": [],
                "categories": categories,
                "session_id": session_id,
                "resume_mode": resume_mode,
                "processed_paper_ids": [],
                "failed_paper_ids": [],
                "api_exhausted": False,
                "current_batch_index": 0,
                "total_papers": len(raw),
                "all_paper_ids": [p.get("id") for p in raw if p.get("id")]
            }
    except Exception as e:
        return {"processing_status": "error", "error_message": str(e)}

async def process_single_paper(state: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single paper: fetch first page text and map author->affiliations via LLM.

    Input state must contain key `paper`. Returns {"papers": [enriched_paper]}.
    """
    paper = state.get("paper", {})
    paper_id = paper.get("id", "unknown")
    title = (paper.get("title") or "(untitled)").strip()
    pub_label = iso_to_date(paper.get("published_at")) or "unknown"
    session_id = state.get("session_id")
    
    start_time = datetime.now(timezone.utc)
    logger.info(f"Processing paper: '{title}' (published: {pub_label})")

    authors = paper.get("authors", [])
    pdf_url = paper.get("pdf_url")
    
    # 更新论文状态为处理中
    if session_id:
        resume_manager.update_paper_status(session_id, paper_id, ProcessingStatus.IN_PROGRESS)
    
    if not authors or not pdf_url:
        if session_id:
            resume_manager.update_paper_status(session_id, paper_id, ProcessingStatus.COMPLETED)
        return {"papers": [{**paper, "author_affiliations": []}]}

    try:
        async with _AFF_SEM:
            first_page_text = await asyncio.to_thread(download_first_page_text_with_retries, pdf_url)
            if not first_page_text:
                if session_id:
                    resume_manager.update_paper_status(
                        session_id, paper_id, ProcessingStatus.FAILED, 
                        error_message="Failed to download PDF first page"
                    )
                return {"papers": [{**paper, "author_affiliations": []}]}

            llm = create_llm()
            user_prompt = build_affiliation_user_prompt(authors, first_page_text)
            try:
                resp = await llm.ainvoke([
                    SystemMessage(content=AFFILIATION_SYSTEM_PROMPT),
                    HumanMessage(content=user_prompt),
                ])
                content = resp.content.strip().strip("`")
                content = re.sub(r"^json\n", "", content, flags=re.IGNORECASE).strip()
                data = json.loads(content)
                mapped = []
                author_data_by_name = { (a.get("name") or "").strip(): a for a in data.get("authors", []) }
                for name in authors:
                    author_info = author_data_by_name.get(name, {})
                    aff = author_info.get("affiliations") or []
                    aff = [s.strip() for s in aff if s and s.strip()]
                    email = author_info.get("email")
                    if email and isinstance(email, str):
                        email = email.strip()
                        if not email:
                            email = None
                    else:
                        email = None
                    # 获取OpenAlex学术指标
                    academic_metrics = None
                    try:
                        # 直接使用作者姓名获取学术指标
                        academic_metrics = await asyncio.to_thread(
                            get_author_academic_metrics,
                            name
                        )
                        if academic_metrics:
                            logger.info(f"Retrieved academic metrics for {name}: {academic_metrics}")
                    except Exception as e:
                        logger.warning(f"Failed to get academic metrics for {name}: {e}")
                    
                    author_entry = {"name": name, "affiliations": aff, "email": email}
                    if academic_metrics:
                        author_entry["academic_metrics"] = academic_metrics
                    
                    mapped.append(author_entry)
                
                # 计算处理时间并更新状态
                processing_time = (datetime.now(timezone.utc) - start_time).total_seconds()
                if session_id:
                    resume_manager.update_paper_status(
                        session_id, paper_id, ProcessingStatus.COMPLETED,
                        processing_time=processing_time
                    )
                
                return {"papers": [{**paper, "author_affiliations": mapped}]}
            except Exception as e:
                error_msg = f"LLM processing failed: {str(e)}"
                logger.error(f"Error processing paper {paper_id}: {error_msg}")
                if session_id:
                    resume_manager.update_paper_status(
                        session_id, paper_id, ProcessingStatus.FAILED,
                        error_message=error_msg
                    )
                return {"papers": [{**paper, "author_affiliations": []}]}
    except Exception as e:
        error_msg = f"General processing error: {str(e)}"
        logger.error(f"Error processing paper {paper_id}: {error_msg}")
        if session_id:
            resume_manager.update_paper_status(
                session_id, paper_id, ProcessingStatus.FAILED,
                error_message=error_msg
            )
        return {"papers": [{**paper, "author_affiliations": []}]}

async def process_orcid_for_paper(state: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich a single paper using ORCID: per author, if ORCID record strictly matches name and
    the institution matches the paper-extracted affiliation, capture orcid.

    Output merges via accumulator: {"papers": [enriched_paper]} where enriched_paper carries:
      - orcid_by_author: {author_name -> orcid_id}
    """
    paper = state.get("paper", {})
    paper_id = paper.get("id", "unknown")
    paper_title = paper.get("title", "Unknown")
    session_id = state.get("session_id")
    logger.info(f"Processing ORCID for paper: '{paper_title[:50]}...'")
    
    authors = paper.get("authors", []) or []
    aff_map = paper.get("author_affiliations", []) or []
    logger.info(f"Authors count: {len(authors)}, Author affiliations count: {len(aff_map)}")
    
    if not authors or not aff_map:
        logger.info("No authors or affiliations found, skipping ORCID processing")
        return {"papers": [{**paper}]}
    orcid_by_author: Dict[str, str] = {}
    api_exhausted = False

    # Read-only pre-check: if author already has orcid and all current affiliations already
    # have role/start/end (any of them) recorded, skip ORCID lookup for that author.
    author_names = [(item.get("name") or "").strip() for item in aff_map if (item.get("name") or "").strip()]
    name_to_author_row: Dict[str, Dict[str, Any]] = {}
    name_to_aff_covered: Dict[str, Dict[str, bool]] = {}
    author_id_to_db_affs: Dict[int, List[str]] = {}
    try:
        db_uri = os.getenv("DATABASE_URL")
        if db_uri and author_names:
            await DatabaseManager.initialize(db_uri)
        pool = await DatabaseManager.get_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                for nm in author_names:
                        # author basic
                        await cur.execute("SELECT id, orcid FROM authors WHERE author_name_en = %s LIMIT 1", (nm,))
                        row = await cur.fetchone()
                        if row:
                            name_to_author_row[nm] = {"id": row[0], "orcid": row[1]}
                            # known DB affiliations for this author
                            await cur.execute(
                                """
                                SELECT f.aff_name
                                FROM author_affiliation aa
                                JOIN affiliations f ON f.id = aa.affiliation_id
                                WHERE aa.author_id = %s
                                """,
                                (row[0],),
                            )
                            aff_rows = await cur.fetchall()
                            author_id_to_db_affs[row[0]] = [r[0] for r in (aff_rows or []) if r and r[0]]
                        # affiliation coverage map
                        for item in [x for x in aff_map if (x.get("name") or "").strip() == nm]:
                            for aff in (item.get("affiliations") or []):
                                norm_key = (" ".join((aff or "").split()).replace(" ", "").lower())
                                covered = False
                                if row:
                                    await cur.execute(
                                        """
                                        SELECT aa.role, aa.start_date, aa.end_date
                                        FROM author_affiliation aa
                                        JOIN affiliations f ON f.id = aa.affiliation_id
                                        WHERE aa.author_id = %s AND REPLACE(LOWER(f.aff_name), ' ', '') = %s
                                        LIMIT 1
                                        """,
                                        (row[0], norm_key),
                                    )
                                    meta = await cur.fetchone()
                                    if meta and (meta[0] is not None or meta[1] is not None or meta[2] is not None):
                                        covered = True
                                name_to_aff_covered.setdefault(nm, {})[norm_key] = covered
    except Exception:
        # best-effort; if pre-check fails, proceed with ORCID lookups
        pass

    async def _lookup_author(name: str, affs: List[str]):
        # Try affiliations in order; each lookup guarded by semaphore
        # Skip if pre-check shows author has orcid and all current affs covered
        pre = name_to_author_row.get(name)
        if pre and (pre.get("orcid") or None):
            all_cov = True
            for aff in affs:
                nk = (" ".join((aff or "").split()).replace(" ", "").lower())
                if not name_to_aff_covered.get(name, {}).get(nk, False):
                    all_cov = False
                    break
            if all_cov:
                return None, None
        # Build candidate affiliation pool: DB-known (by author_id) + current paper-extracted
        author_id = (pre or {}).get("id")
        db_affs = author_id_to_db_affs.get(author_id or -1, [])
        pool_affs = []
        seen = set()
        for s in (db_affs + affs):
            if not s:
                continue
            ss = " ".join(s.split())
            if ss not in seen:
                seen.add(ss); pool_affs.append(ss)
        # Fetch strict-name candidates once, then try to match any candidate to any affiliation
        async with _ORCID_SEM:
            cands = await asyncio.to_thread(orcid_candidates_by_name, name, 5)
        
        # Try to find ORCID match with institution
        for cand in cands or []:
            for aff in pool_affs:
                best = best_aff_match_for_institution(aff, cand)
                if best:
                    return aff, {**cand, "_best": best}
        
        # If no ORCID match found but we have candidates, return the first candidate
        # This allows Tavily fallback to work even when ORCID has no institution data
        if cands and pool_affs:
            return pool_affs[0], {**cands[0], "_best": None}
        
        return None, None

    tasks = []
    for item in aff_map:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        affs = [a for a in (item.get("affiliations") or []) if a]
        if not affs:
            continue
        tasks.append(_lookup_author(name, affs))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    i = 0
    for item in aff_map:
        name = (item.get("name") or "").strip()
        affs = [a for a in (item.get("affiliations") or []) if a]
        if not name or not affs:
            continue
        r = results[i]; i += 1
        
        # Initialize role and department variables
        role = None
        department = None
        sd = None
        ed = None
        aff_used = None
        orcid_found = False
        
        # Process ORCID results if available
        if not isinstance(r, Exception) and r:
            aff_used, info = r
            if info:
                orcid_found = True
                orcid_id = info.get("orcid_id")
                if orcid_id:
                    orcid_by_author[name] = orcid_id
                best_aff = info.get("_best") or best_aff_match_for_institution(aff_used, info)
                
                if best_aff:
                    # Keep role and department separate for proper database storage
                    role = (best_aff.get("role") or "").strip() or None
                    department = (best_aff.get("department") or "").strip() or None
                        
                    sd = parse_orcid_date(best_aff.get("start_date") or "")
                    ed = parse_orcid_date(best_aff.get("end_date") or "")
        
        # If no role found (either ORCID not found or ORCID found but no role), try Tavily API
        if not role:
            # Use aff_used if available from ORCID, otherwise use the first affiliation from the paper
            search_aff = aff_used or (affs[0] if affs else None)
            if search_aff:
                logger.info(f"Trying Tavily API for {name} at {search_aff} (ORCID found: {orcid_found})")
                try:
                    # Add throttling delay between Tavily API calls in batch processing
                    if i > 0:  # Skip delay for first author in batch
                        await asyncio.sleep(_TAVILY_BATCH_DELAY)
                    
                    tavily_result = await search_person_role_with_tavily(name, search_aff)
                    if tavily_result and tavily_result.get("search_successful"):
                        extracted_role = tavily_result.get("extracted_role")
                        if extracted_role:
                            role = extracted_role.strip()
                            logger.info(f"Tavily found role for {name}: {role}")
                            # If we didn't have aff_used from ORCID, use the search affiliation
                            if not aff_used:
                                aff_used = search_aff
                        else:
                            logger.info(f"Tavily search successful but no role extracted for {name}")
                    else:
                        logger.info(f"Tavily search failed for {name}")
                except Exception as e:
                    error_msg = str(e).lower()
                    # 检测Tavily API额度耗尽
                    if "quota" in error_msg or "limit" in error_msg or "exceeded" in error_msg:
                        logger.error(f"Tavily API quota exhausted while processing {name}: {e}")
                        api_exhausted = True
                        
                        # 更新会话状态
                        if session_id:
                            resume_manager.update_paper_status(
                                session_id, paper_id, ProcessingStatus.FAILED,
                                error_message=f"Tavily API quota exhausted: {str(e)}"
                            )
                        
                        # 返回当前状态，标记API已耗尽
                        return {
                            "papers": [paper],
                            "api_exhausted": True,
                            "processing_status": "api_quota_exhausted",
                            "error_message": f"Tavily API quota exhausted while processing author {name}"
                        }
                    else:
                        logger.error(f"Tavily API error for {name}: {e}")
            else:
                logger.info(f"No affiliation available for Tavily search for {name}")
        
        # 如果API已耗尽，停止处理
        if api_exhausted:
            break
        
        # Note: role, department, start_date, end_date information is no longer stored
        # as orcid_aff_meta field has been removed from the database schema
    enriched = {**paper}
    if orcid_by_author:
        enriched["orcid_by_author"] = orcid_by_author
    return {"papers": [enriched], "api_exhausted": api_exhausted}

def merge_paper_results(state: DataProcessingState) -> DataProcessingState:
    """Merge results from process_single_paper and process_orcid_for_paper.
    
    This function combines the enriched paper data from both processing nodes
    to avoid duplicate processing in upsert_papers.
    """
    logger.info(f"merge_paper_results called with {len(state.get('papers', []))} papers")
    papers = state.get("papers", []) or []
    api_exhausted = state.get("api_exhausted", False)
    
    # 检查是否有任何论文处理过程中API耗尽
    for paper_result in papers:
        if isinstance(paper_result, dict) and paper_result.get("api_exhausted"):
            api_exhausted = True
            break
    
    if not papers:
        logger.info("No papers to merge, returning state as-is")
        result = state.copy()
        if api_exhausted:
            result["api_exhausted"] = True
            result["processing_status"] = "api_quota_exhausted"
        return result
    
    # Group papers by arxiv_entry to merge duplicates
    paper_map = {}
    for paper in papers:
        arxiv_entry = paper.get("id")
        if not arxiv_entry:
            continue
            
        if arxiv_entry in paper_map:
            logger.info(f"Merging duplicate paper: {arxiv_entry}")
            # Merge the paper data
            existing = paper_map[arxiv_entry]
            # Merge author_affiliations (from process_single_paper)
            if "author_affiliations" in paper and "author_affiliations" not in existing:
                existing["author_affiliations"] = paper["author_affiliations"]
            # Merge orcid data (from process_orcid_for_paper)
            if "orcid_by_author" in paper:
                existing["orcid_by_author"] = paper["orcid_by_author"]
        else:
            paper_map[arxiv_entry] = paper.copy()
    
    # Return merged papers
    merged_papers = list(paper_map.values())
    logger.info(f"Merged {len(papers)} papers into {len(merged_papers)} unique papers, API exhausted: {api_exhausted}")
    
    result = {**state, "papers": merged_papers}
    if api_exhausted:
        result["api_exhausted"] = True
        result["processing_status"] = "api_quota_exhausted"
    
    return result

def dispatch_affiliations(state: DataProcessingState):
    """Dispatch parallel jobs using Send for each paper in `raw_papers`."""
    raw = state.get("raw_papers", []) or []
    if not raw:
        # If no papers to process, go directly to merge_paper_results
        return [Send("merge_paper_results", state)]
    jobs = []
    for p in raw:
        jobs.append(Send("process_single_paper", {"paper": p}))
    return jobs

def dispatch_orcid_processing(state: DataProcessingState):
    """Dispatch ORCID processing jobs for papers that have author_affiliations."""
    papers = state.get("papers", []) or []
    if not papers:
        return [Send("upsert_papers", state)]
    
    jobs = []
    for paper in papers:
        # Only process papers that have author_affiliations
        if paper.get("author_affiliations"):
            jobs.append(Send("process_orcid_for_paper", {"paper": paper}))
    
    if not jobs:
        # No papers need ORCID processing, go directly to upsert
        return [Send("upsert_papers", state)]
    
    return jobs

async def upsert_papers(state: DataProcessingState, config: RunnableConfig) -> DataProcessingState:
    """Create normalized schema and insert papers/authors/categories/affiliations.
    
    Modified for streaming processing: processes current batch and prepares for next batch.
    """
    try:
        # Allow upsert if we have papers to process, regardless of current status
        papers: List[Dict[str, Any]] = state.get("papers", []) or []
        raw_papers: List[Dict[str, Any]] = state.get("raw_papers", []) or []
        session_id = state.get("session_id")
        api_exhausted = state.get("api_exhausted", False)
        current_batch_index = state.get("current_batch_index", 0)
        total_papers = state.get("total_papers", 0)
        all_paper_ids = state.get("all_paper_ids", [])
        processed_paper_ids = state.get("processed_paper_ids", [])
        failed_paper_ids = state.get("failed_paper_ids", [])
        
        # Use papers if available, otherwise use raw_papers
        papers_to_process = papers if papers else raw_papers
        
        if not papers_to_process:
            # 检查是否还有更多批次需要处理
            batch_size = int(os.getenv("BATCH_SIZE", "10"))
            next_batch_index = current_batch_index + 1
            
            if next_batch_index * batch_size >= total_papers:
                # 所有批次都已完成
                result = {
                    "processing_status": "completed",
                    "inserted": len(processed_paper_ids),
                    "skipped": 0,
                    "fetched": state.get("fetched", 0),
                    "current_batch_index": next_batch_index,
                    "total_papers": total_papers,
                    "all_paper_ids": all_paper_ids,
                    "processed_paper_ids": processed_paper_ids,
                    "failed_paper_ids": failed_paper_ids
                }
                if api_exhausted:
                    result["processing_status"] = "api_quota_exhausted"
                return result
            else:
                # 还有更多批次，返回batch_completed状态
                return {
                    "processing_status": "batch_completed",
                    "inserted": 0,
                    "skipped": 0,
                    "fetched": state.get("fetched", 0),
                    "current_batch_index": next_batch_index,
                    "total_papers": total_papers,
                    "all_paper_ids": all_paper_ids,
                    "processed_paper_ids": processed_paper_ids,
                    "failed_paper_ids": failed_paper_ids
                }
        
        db_uri = os.getenv("DATABASE_URL")
        if not db_uri:
            return {"processing_status": "error", "error_message": "DATABASE_URL not set"}
        
        await DatabaseManager.initialize(db_uri)
        pool = await DatabaseManager.get_pool()

        # 处理当前批次的论文
        logger.info(f"Processing current batch {current_batch_index + 1}: {len(papers_to_process)} papers")
        
        try:
            # 使用信号量限制并发批次数量，避免过多数据库连接
            async with _BATCH_SEM:
                batch_inserted, batch_skipped = await _process_paper_batch(
                    papers_to_process, pool, session_id
                )
            
            # 更新已处理的论文ID
            for paper in papers_to_process:
                paper_id = paper.get("id")
                if paper_id and paper_id not in processed_paper_ids:
                    processed_paper_ids.append(paper_id)
            
            logger.info(f"Batch {current_batch_index + 1} completed: {batch_inserted} inserted, {batch_skipped} skipped")
            
            # 更新会话进度
            if session_id:
                resume_manager.update_session_progress(
                    session_id,
                    processed_count=len(processed_paper_ids),
                    failed_count=len(failed_paper_ids)
                )
                    
        except Exception as e:
            logger.error(f"Error processing batch {current_batch_index + 1}: {str(e)}")
            
            # 将当前批次的论文标记为失败
            for paper in papers_to_process:
                paper_id = paper.get("id")
                if paper_id and paper_id not in failed_paper_ids:
                    failed_paper_ids.append(paper_id)
            
            # 更新会话进度
            if session_id:
                resume_manager.update_session_progress(
                    session_id,
                    processed_count=len(processed_paper_ids),
                    failed_count=len(failed_paper_ids),
                    error_message=f"Batch {current_batch_index + 1} failed: {str(e)}"
                )
            
            batch_inserted = 0
            batch_skipped = 0
        
        # 准备下一批次
        batch_size = int(os.getenv("BATCH_SIZE", "10"))
        next_batch_index = current_batch_index + 1
        
        # 检查是否还有更多批次需要处理
        if next_batch_index * batch_size >= total_papers:
            # 所有批次都已完成，更新最终会话状态
            if session_id:
                final_status = "completed" if len(failed_paper_ids) == 0 else "failed"
                resume_manager.update_session_progress(
                    session_id,
                    processed_count=len(processed_paper_ids),
                    failed_count=len(failed_paper_ids),
                    status=final_status
                )
            
            processing_status = "api_quota_exhausted" if api_exhausted else "completed"
            logger.info(f"All batches completed: {len(processed_paper_ids)} papers processed, {len(failed_paper_ids)} failed")
            
            return {
                "processing_status": processing_status,
                "inserted": len(processed_paper_ids),
                "skipped": 0,
                "api_exhausted": api_exhausted,
                "current_batch_index": next_batch_index,
                "total_papers": total_papers,
                "all_paper_ids": all_paper_ids,
                "processed_paper_ids": processed_paper_ids,
                "failed_paper_ids": failed_paper_ids
            }
        else:
            # 还有更多批次需要处理
            logger.info(f"Batch {current_batch_index + 1} completed, preparing for next batch {next_batch_index + 1}")
            
            return {
                "processing_status": "batch_completed",
                "inserted": batch_inserted,
                "skipped": batch_skipped,
                "api_exhausted": api_exhausted,
                "current_batch_index": next_batch_index,
                "total_papers": total_papers,
                "all_paper_ids": all_paper_ids,
                "processed_paper_ids": processed_paper_ids,
                "failed_paper_ids": failed_paper_ids
            }
        
    except Exception as e:
        # 保存错误状态到会话
        session_id = state.get("session_id")
        if session_id:
            resume_manager.update_session_progress(
                session_id,
                processed_count=len(state.get("processed_paper_ids", [])),
                failed_count=len(state.get("failed_paper_ids", [])),
                error_message=str(e)
            )
        
        return {
            "processing_status": "error",
            "error_message": str(e),
            "api_exhausted": state.get("api_exhausted", False),
            "current_batch_index": state.get("current_batch_index", 0),
            "total_papers": state.get("total_papers", 0),
            "all_paper_ids": state.get("all_paper_ids", []),
            "processed_paper_ids": state.get("processed_paper_ids", []),
            "failed_paper_ids": state.get("failed_paper_ids", [])
        }

async def _process_paper_batch(
    papers_batch: List[Dict[str, Any]], 
    pool, 
    session_id: Optional[str] = None
) -> tuple[int, int]:
    """处理单个论文批次的核心逻辑"""
    inserted = 0
    skipped = 0
    
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await create_schema_if_not_exists(cur)
            # Prepare QS mapping and ranking systems once per transaction
            qs_map = get_qs_map()
            qs_names = get_qs_names()
            qs_sys_ids = await ensure_qs_ranking_systems(cur)
            
            # Global author cache to avoid duplicates across papers in this batch
            author_name_to_id: Dict[str, int] = {}

            for i, p in enumerate(papers_batch):
                    paper_title = p.get("title")
                    if not paper_title:
                        continue
                    published_date = iso_to_date(p.get("published_at"))
                    updated_date = iso_to_date(p.get("updated_at"))
                    abstract = p.get("summary")
                    doi = None
                    pdf_source = p.get("pdf_url")
                    arxiv_entry = p.get("id")

                    # Insert paper
                    paper_id = None
                    
                    try:
                        await cur.execute(
                            """
                            INSERT INTO papers (
                                paper_title, published, updated, abstract, doi, pdf_source, arxiv_entry
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (arxiv_entry) DO NOTHING
                            RETURNING id
                            """,
                            (paper_title, published_date, updated_date, abstract, doi, pdf_source, arxiv_entry),
                        )
                        row = await cur.fetchone()
                        if row and row[0]:
                            paper_id = row[0]
                            inserted += 1
                        else:
                            await cur.execute("SELECT id FROM papers WHERE arxiv_entry = %s LIMIT 1", (arxiv_entry,))
                            row2 = await cur.fetchone()
                            if row2:
                                paper_id = row2[0]
                                skipped += 1
                            else:
                                await cur.execute(
                                    "SELECT id FROM papers WHERE paper_title = %s AND published = %s LIMIT 1",
                                    (paper_title, published_date),
                                )
                                row3 = await cur.fetchone()
                                if row3:
                                    paper_id = row3[0]
                                    skipped += 1
                                else:
                                    continue
                    except Exception as e:
                        logger.error(f"Error inserting paper {arxiv_entry}: {str(e)}")
                        await cur.execute("SELECT id FROM papers WHERE arxiv_entry = %s LIMIT 1", (arxiv_entry,))
                        rowe = await cur.fetchone()
                        if rowe:
                            paper_id = rowe[0]
                            skipped += 1
                        else:
                            continue

                    if paper_id is None:
                        continue

                    # Authors and author_paper
                    # Build email and academic metrics mapping from author_affiliations
                    author_email_map = {}
                    author_metrics_map = {}
                    for item in p.get("author_affiliations", []) or []:
                        name = (item.get("name") or "").strip()
                        email = item.get("email")
                        academic_metrics = item.get("academic_metrics")
                        if name and email:
                            author_email_map[name] = email
                        if name and academic_metrics:
                            author_metrics_map[name] = academic_metrics
                    
                    for idx, name_en in enumerate(p.get("authors", []), start=1):
                        # First check if we already processed this author in current transaction
                        author_id = author_name_to_id.get(name_en)
                        if author_id:
                            # Author already processed, just create the relationship
                            await cur.execute(
                                """
                                INSERT INTO author_paper (author_id, paper_id, author_order, is_corresponding)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (author_id, paper_id) DO NOTHING
                                """,
                                (author_id, paper_id, idx, False),
                            )
                            continue
                            
                        email = author_email_map.get(name_en)
                        orcid = (p.get("orcid_by_author") or {}).get(name_en)
                        
                        # If not in cache, try to find existing author by email or orcid
                        if email:
                            await cur.execute("SELECT id FROM authors WHERE email = %s LIMIT 1", (email,))
                            rowa = await cur.fetchone()
                            if rowa:
                                author_id = rowa[0]
                                # Update name and orcid if we have them
                                try:
                                    await cur.execute(
                                        "UPDATE authors SET author_name_en = COALESCE(author_name_en, %s), orcid = COALESCE(orcid, %s) WHERE id = %s",
                                        (name_en, orcid, author_id),
                                    )
                                except Exception:
                                    pass
                        
                        if not author_id and orcid:
                            await cur.execute("SELECT id FROM authors WHERE orcid = %s LIMIT 1", (orcid,))
                            rowa = await cur.fetchone()
                            if rowa:
                                author_id = rowa[0]
                                # Update name and email if we have them
                                try:
                                    await cur.execute(
                                        "UPDATE authors SET author_name_en = COALESCE(author_name_en, %s), email = COALESCE(email, %s) WHERE id = %s",
                                        (name_en, email, author_id),
                                    )
                                except Exception:
                                    pass
                        
                        # Extract academic metrics if available
                        citations = h_index = i10_index = None
                        academic_metrics = author_metrics_map.get(name_en)
                        if academic_metrics:
                            citations = academic_metrics.get("citations")
                            h_index = academic_metrics.get("h_index")
                            i10_index = academic_metrics.get("i10_index")
                        
                        # If no existing author found by email or orcid, create new one
                        if not author_id:
                            # Create new author with available information (email and orcid can be NULL)
                            try:
                                await cur.execute(
                                    "INSERT INTO authors (author_name_en, email, orcid, citations, h_index, i10_index) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", 
                                    (name_en, email, orcid, citations, h_index, i10_index)
                                )
                                rowa2 = await cur.fetchone()
                                if rowa2:
                                    author_id = rowa2[0]
                            except Exception as e:
                                # Handle unique constraint violations gracefully
                                logger.warning(f"Failed to insert author {name_en}: {e}")
                                continue
                        else:
                            # Update existing author with academic metrics if available
                            if academic_metrics:
                                try:
                                    await cur.execute(
                                        "UPDATE authors SET citations = COALESCE(%s, citations), h_index = COALESCE(%s, h_index), i10_index = COALESCE(%s, i10_index) WHERE id = %s",
                                        (citations, h_index, i10_index, author_id)
                                    )
                                except Exception as e:
                                    logger.warning(f"Failed to update academic metrics for author {name_en}: {e}")
                        
                        if not author_id:
                            continue
                        author_name_to_id[name_en] = author_id
                        await cur.execute(
                            """
                            INSERT INTO author_paper (author_id, paper_id, author_order, is_corresponding)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (author_id, paper_id) DO NOTHING
                            """,
                            (author_id, paper_id, idx, False),
                        )

                    # Categories and paper_category
                    for cat in p.get("categories", []):
                        category_id = None
                        await cur.execute("SELECT id FROM categories WHERE category = %s LIMIT 1", (cat,))
                        rowc = await cur.fetchone()
                        if rowc:
                            category_id = rowc[0]
                        else:
                            await cur.execute(
                                "INSERT INTO categories (category) VALUES (%s) ON CONFLICT (category) DO NOTHING RETURNING id",
                                (cat,),
                            )
                            rowc2 = await cur.fetchone()
                            if rowc2:
                                category_id = rowc2[0]
                            else:
                                await cur.execute("SELECT id FROM categories WHERE category = %s LIMIT 1", (cat,))
                                rowc3 = await cur.fetchone()
                                if rowc3:
                                    category_id = rowc3[0]
                        if category_id is not None:
                            await cur.execute(
                                """
                                INSERT INTO paper_category (paper_id, category_id)
                                VALUES (%s, %s)
                                ON CONFLICT (paper_id, category_id) DO NOTHING
                                """,
                                (paper_id, category_id),
                            )

                    # Affiliations and author_affiliation
                    for item in p.get("author_affiliations", []) or []:
                        name = (item.get("name") or "").strip()
                        if not name:
                            continue
                        author_id = author_name_to_id.get(name)
                        if not author_id:
                            continue
                        for aff_name in item.get("affiliations") or []:
                            if not aff_name:
                                continue
                            # normalize: trim, collapse spaces, proper spacing and lower for key
                            cleaned = " ".join((aff_name or "").split())
                            norm_key = cleaned.replace(" ", "").lower()
                            # try find by normalized key via case/space-insensitive matching
                            await cur.execute(
                                "SELECT id, aff_name FROM affiliations WHERE REPLACE(LOWER(aff_name), ' ', '') = %s LIMIT 1",
                                (norm_key,),
                            )
                            rowaf = await cur.fetchone()
                            if rowaf and rowaf[0]:
                                aff_id = rowaf[0]
                            else:
                                # insert with cleaned display name, then reselect by normalized key to avoid race
                                await cur.execute(
                                    "INSERT INTO affiliations (aff_name) VALUES (%s) ON CONFLICT (aff_name) DO NOTHING RETURNING id",
                                    (cleaned,),
                                )
                                rowaf2 = await cur.fetchone()
                                if rowaf2 and rowaf2[0]:
                                    aff_id = rowaf2[0]
                                else:
                                    await cur.execute(
                                        "SELECT id FROM affiliations WHERE REPLACE(LOWER(aff_name), ' ', '') = %s LIMIT 1",
                                        (norm_key,),
                                    )
                                    rowaf3 = await cur.fetchone()
                                    if not rowaf3:
                                        continue
                                    aff_id = rowaf3[0]

                            # Enrich with QS rankings and country if available
                            await enrich_affiliation_from_qs(cur, aff_id, cleaned, qs_map, qs_names, qs_sys_ids)
                            # Upsert author_affiliation: only maintain latest_time; leave role/start_date/end_date as NULL for now
                            pub_dt = published_date
                            await cur.execute(
                                """
                                INSERT INTO author_affiliation (author_id, affiliation_id, latest_time)
                                VALUES (%s, %s, %s)
                                ON CONFLICT (author_id, affiliation_id) DO UPDATE SET
                                  latest_time = GREATEST(COALESCE(author_affiliation.latest_time, EXCLUDED.latest_time), EXCLUDED.latest_time)
                                """,
                                (author_id, aff_id, pub_dt),
                            )
                            # Note: ORCID metadata (role, department, start_date, end_date) is no longer processed
                            # as orcid_aff_meta field has been removed from the database schema

            # Commit the transaction for this batch
            await conn.commit()
    
    return inserted, skipped

# ---------------------- Graph Construction ----------------------

def _route(state: DataProcessingState) -> str:
    """Route function for conditional edges."""
    status = state.get("processing_status")
    if status == "fetched":
        return "fetch_arxiv_today"  # continue from sender node after map
    if status in {"completed", "error"}:
        return "__end__"

def collect_single_paper_results(state: DataProcessingState) -> DataProcessingState:
    """Collect results from process_single_paper and prepare for ORCID processing."""
    papers = state.get("papers", []) or []
    logger.info(f"Collected {len(papers)} papers from process_single_paper")
    return state

def should_continue_processing(state: DataProcessingState):
    """Determine if processing should continue to next batch or end."""
    processing_status = state.get("processing_status")
    
    if processing_status == "batch_completed":
        # Continue to next batch
        return "fetch_arxiv_today"
    else:
        # End processing (completed, error, or api_quota_exhausted)
        return END

# Build the state graph
builder = StateGraph(DataProcessingState)

builder.add_node("fetch_arxiv_today", fetch_arxiv_today)
builder.add_node("process_single_paper", process_single_paper)
builder.add_node("collect_single_paper_results", collect_single_paper_results)
builder.add_node("process_orcid_for_paper", process_orcid_for_paper)
builder.add_node("merge_paper_results", merge_paper_results)
builder.add_node("upsert_papers", upsert_papers)

builder.add_edge(START, "fetch_arxiv_today")
# Use conditional edges with Send for parallel map from fetch node
builder.add_conditional_edges(
    "fetch_arxiv_today",
    dispatch_affiliations,
)
# Connect process_single_paper to collector, then dispatch ORCID processing
builder.add_edge("process_single_paper", "collect_single_paper_results")
builder.add_conditional_edges(
    "collect_single_paper_results",
    dispatch_orcid_processing,
)
# Connect ORCID processing to merge, then to upsert
builder.add_edge("process_orcid_for_paper", "merge_paper_results")
builder.add_edge("merge_paper_results", "upsert_papers")

# Add conditional edge from upsert_papers to either continue or end
builder.add_conditional_edges(
    "upsert_papers",
    should_continue_processing,
)

data_processing_graph = builder.compile()

async def build_data_processing_graph(checkpointer=None):
    """Build data processing graph with optional checkpointer."""
    if checkpointer:
        return builder.compile(checkpointer=checkpointer)
    return data_processing_graph
