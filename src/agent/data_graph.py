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
    # ORCID utilities (keeping for compatibility)
    orcid_candidates_by_name, best_aff_match_for_institution, parse_orcid_date,
    normalize_aff_variants, norm_string,
    # QS utilities
    get_qs_map, get_qs_names, ensure_qs_ranking_systems, enrich_affiliation_from_qs,
    # Database utilities
    create_schema_if_not_exists,
    # Tavily utilities
    search_person_role_with_tavily, search_person_homepage_with_tavily,
    crawl_homepage, extract_email_and_dates_with_llm
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

# Tavily API configuration
_TAVILY_ENABLED = os.getenv("TAVILY_ENABLED", "false").lower() in ("true", "1", "yes", "on")
_TAVILY_BATCH_DELAY = float(os.getenv("TAVILY_BATCH_DELAY", "2.0"))

# Database batch processing concurrency control
_BATCH_MAX_CONCURRENCY = int(os.getenv("BATCH_MAX_CONCURRENCY", "3"))  # Limit concurrent batches for Supabase
_BATCH_SEM = asyncio.Semaphore(_BATCH_MAX_CONCURRENCY)

# ---------------------- Node Functions ----------------------

async def fetch_arxiv_today(state: DataProcessingState, config: RunnableConfig) -> DataProcessingState:
    """Fetch latest papers from arXiv by date window, explicit date range or id_list."""
    try:
        cfg = config.get("configurable", {}) if isinstance(config, dict) else {}
        
        # 检查是否为恢复模式
        session_id = cfg.get("session_id")
        resume_mode = cfg.get("resume_mode", False)
        
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
                    "api_exhausted": False
                }
        
        # 如果是新的批量处理且有id_list，创建会话
        if id_list and not session_id:
            session_id = resume_manager.create_session(
                source_file=cfg.get("source_file", "unknown"),
                paper_ids=id_list
            )
            logger.info(f"Created new processing session: {session_id}")

        # ID列表模式：分批获取论文以优化内存使用和错误处理
        if id_list:
            batch_size = int(os.getenv("BATCH_SIZE", "10"))
            total_papers = len(id_list)
            total_batches = (total_papers + batch_size - 1) // batch_size
            
            logger.info(f"Processing {total_papers} papers in {total_batches} batches (batch_size={batch_size})")
            
            all_raw_papers = []
            successful_batches = 0
            
            for batch_index in range(total_batches):
                batch_start = batch_index * batch_size
                batch_end = min(batch_start + batch_size, total_papers)
                current_batch_ids = id_list[batch_start:batch_end]
                
                logger.info(f"[BATCH {batch_index + 1}/{total_batches}] Processing papers {batch_start + 1}-{batch_end} ({len(current_batch_ids)} papers)")
                
                try:
                    # 分批调用ArXiv API
                    batch_raw = await asyncio.to_thread(search_papers_by_ids, current_batch_ids)
                    all_raw_papers.extend(batch_raw)
                    successful_batches += 1
                    
                    logger.info(f"[BATCH {batch_index + 1}/{total_batches}] ✅ Fetched {len(batch_raw)} papers from ArXiv")
                    
                    # 可选：添加批次间延迟以避免API限制
                    if batch_index < total_batches - 1:  # 不是最后一批
                        await asyncio.sleep(0.5)  # 500ms延迟
                        
                except Exception as e:
                    logger.error(f"[BATCH {batch_index + 1}/{total_batches}] ❌ Failed to fetch papers: {str(e)}")
                    # 继续处理下一批，不中断整个流程
                    continue
            
            logger.info(f"ArXiv fetch completed: {len(all_raw_papers)} papers fetched from {successful_batches}/{total_batches} successful batches")
            
            return {
                "processing_status": "fetched",
                "raw_papers": all_raw_papers,
                "fetched": len(all_raw_papers),
                "papers": [],
                "categories": categories,
                "session_id": session_id,
                "resume_mode": resume_mode,
                "processed_paper_ids": state.get("processed_paper_ids", []),
                "failed_paper_ids": state.get("failed_paper_ids", []),
                "api_exhausted": False,
                "total_requested": total_papers,
                "total_papers": len(all_raw_papers),
                "successful_batches": successful_batches,
                "total_batches": total_batches
            }
        else:
            # 非ID列表模式：按日期范围或窗口获取
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
                "api_exhausted": False
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
                
                # 提取关键词
                keywords = data.get("keywords", [])
                keywords = [k.strip().lower() for k in keywords if k and k.strip()]
                
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
                        # 尝试获取作者的机构名称
                        institution_name = None
                        if aff:
                            # aff是字符串列表，取第一个机构名称
                            institution_name = aff[0] if isinstance(aff[0], str) else None

                        academic_metrics = await asyncio.to_thread(
                            get_author_academic_metrics,
                            name,
                            institution_name
                        )
                        if academic_metrics:
                            logger.info(f"[OPENALEX] ✓ Retrieved metrics for {name}: citations={academic_metrics.get('citations', 'N/A')}, h-index={academic_metrics.get('h_index', 'N/A')}")
                    except Exception as e:
                        logger.warning(f"[OPENALEX] ✗ Failed to get metrics for {name}: {e}")
                    
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
                
                return {"papers": [{**paper, "author_affiliations": mapped, "keywords": keywords}]}
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

async def process_tavily_homepage_for_paper(state: Dict[str, Any]) -> Dict[str, Any]:
    """使用Tavily API获取作者的homepage链接"""
    paper = state.get("paper", {})
    paper_id = paper.get("id", "unknown")
    session_id = state.get("session_id")
    
    aff_map = paper.get("author_affiliations", []) or []
    if not aff_map:
        return {"papers": [{**paper}]}
    
    # 为每个作者获取homepage
    for item in aff_map:
        name = (item.get("name") or "").strip()
        affiliations = item.get("affiliations", [])
        
        if not name or not affiliations:
            continue
            
        # 使用第一个机构进行搜索
        affiliation = affiliations[0] if affiliations else ""
        
        try:
            if _TAVILY_ENABLED:
                homepage_result = await search_person_homepage_with_tavily(name, affiliation)
                if homepage_result and homepage_result.get("search_successful"):
                    # 使用LLM从Tavily响应中提取homepage链接
                    tavily_answer = homepage_result.get('answer', '')
                    tavily_results = homepage_result.get('results', [])
                    
                    if tavily_answer or tavily_results:
                        # 导入LLM提取函数
                        from src.agent.utils import _extract_homepage_link_with_llm
                        
                        extracted_link = _extract_homepage_link_with_llm(
                            name, affiliation, tavily_answer, tavily_results
                        )
                        
                        if extracted_link:
                            item["homepage"] = extracted_link
                            logger.info(f"[TAVILY] ✓ Extracted homepage for {name}: {extracted_link}")
                            
                            # 立即提取role信息
                            try:
                                from src.agent.utils import search_person_role_with_tavily
                                role_result = await search_person_role_with_tavily(name, affiliation)
                                if role_result and role_result.get("search_successful"):
                                    extracted_role = role_result.get("extracted_role")
                                    if extracted_role:
                                        item["role"] = extracted_role.strip()
                                        logger.info(f"[TAVILY] ✓ Extracted role for {name}: {extracted_role}")
                                    else:
                                        logger.info(f"[TAVILY] ✗ No role extracted for {name}")
                                else:
                                    logger.info(f"[TAVILY] ✗ Role search failed for {name}")
                            except Exception as role_e:
                                logger.warning(f"[TAVILY] Error getting role for {name}: {role_e}")
                        else:
                            logger.info(f"[TAVILY] ✗ LLM could not extract valid homepage link for {name}")
                    else:
                        logger.info(f"[TAVILY] ✗ No answer or results from Tavily for {name}")
                else:
                    logger.info(f"[TAVILY] ✗ Tavily search failed for {name}")
            else:
                logger.info(f"[TAVILY] Disabled, skipping homepage search for {name}")
        except Exception as e:
            logger.warning(f"[TAVILY] Error getting homepage for {name}: {e}")
    
    return {"papers": [{**paper, "author_affiliations": aff_map}]}

async def process_homepage_extraction_for_paper(state: Dict[str, Any]) -> Dict[str, Any]:
    """从homepage链接中提取email、role、start_date、end_date信息"""
    paper = state.get("paper", {})
    paper_id = paper.get("id", "unknown")
    session_id = state.get("session_id")
    
    aff_map = paper.get("author_affiliations", []) or []
    if not aff_map:
        return {"papers": [{**paper}]}
    
    # 处理每个有homepage的作者
    for item in aff_map:
        name = (item.get("name") or "").strip()
        homepage = item.get("homepage")
        affiliations = item.get("affiliations", [])
        
        if not name:
            continue
            
        # First, extract affiliation details using Tavily API for each affiliation
        for aff_name in affiliations:
            if not aff_name:
                continue
                
            try:
                # Import the new functions
                from src.agent.utils import search_person_affiliation_details_with_tavily, _extract_affiliation_details_with_llm
                
                # Search for affiliation details with homepage reference if available
                details_result = await search_person_affiliation_details_with_tavily(name, aff_name, homepage)
                
                if details_result and details_result.get("search_successful"):
                    tavily_answer = details_result.get('answer', '')
                    tavily_results = details_result.get('results', [])
                    
                    if tavily_answer or tavily_results:
                        # Extract role, start_date, end_date using LLM
                        extracted_details = _extract_affiliation_details_with_llm(
                            name, aff_name, tavily_answer, tavily_results
                        )
                        
                        # Store the extracted details in the item
                        if extracted_details.get('role'):
                            item["role"] = extracted_details['role']
                            logger.info(f"[TAVILY] ✓ Extracted role for {name} at {aff_name}: {extracted_details['role']}")
                        
                        if extracted_details.get('start_date'):
                            item["start_date"] = extracted_details['start_date']
                            logger.info(f"[TAVILY] ✓ Extracted start_date for {name} at {aff_name}: {extracted_details['start_date']}")
                        
                        if extracted_details.get('end_date'):
                            item["end_date"] = extracted_details['end_date']
                            logger.info(f"[TAVILY] ✓ Extracted end_date for {name} at {aff_name}: {extracted_details['end_date']}")
                        
                        if not any(extracted_details.values()):
                            logger.info(f"[TAVILY] ✗ No valid affiliation details extracted for {name} at {aff_name}")
                    else:
                        logger.info(f"[TAVILY] ✗ No answer or results for affiliation details of {name} at {aff_name}")
                else:
                    logger.info(f"[TAVILY] ✗ Affiliation details search failed for {name} at {aff_name}")
                    
            except Exception as aff_e:
                logger.warning(f"[TAVILY] Error getting affiliation details for {name} at {aff_name}: {aff_e}")
        
        # Then, if homepage exists, crawl it for additional information
        if homepage:
            try:
                # 爬取homepage内容并提取信息
                homepage_content = await crawl_homepage(homepage)
                if homepage_content:
                    # 使用LLM提取email和职位信息
                    extracted_info = await extract_email_and_dates_with_llm(
                        name, homepage_content, affiliations[0] if affiliations else ""
                    )
                    
                    if extracted_info:
                        if extracted_info.get("email"):
                            item["email"] = extracted_info["email"]
                        if extracted_info.get("role"):
                            item["role"] = extracted_info["role"]
                        if extracted_info.get("start_date"):
                            item["start_date"] = extracted_info["start_date"]
                        if extracted_info.get("end_date"):
                            item["end_date"] = extracted_info["end_date"]
                        
                        logger.info(f"[HOMEPAGE] ✓ Extracted info for {name}: {extracted_info}")
                    else:
                        logger.info(f"[HOMEPAGE] ✗ No info extracted from homepage for {name}")
                else:
                    logger.warning(f"[HOMEPAGE] Failed to crawl homepage for {name}: {homepage}")
                    
            except Exception as e:
                logger.warning(f"[HOMEPAGE] Error processing homepage for {name}: {e}")
            
        # 如果从homepage没有获取到role信息，尝试使用Tavily API
        if not item.get("role") and _TAVILY_ENABLED and affiliations:
            try:
                tavily_result = await search_person_role_with_tavily(name, affiliations[0])
                if tavily_result and tavily_result.get("search_successful"):
                    extracted_role = tavily_result.get("extracted_role")
                    if extracted_role:
                        item["role"] = extracted_role.strip()
                        logger.info(f"[TAVILY] ✓ Found role for {name}: {extracted_role}")
            except Exception as e:
                logger.warning(f"[TAVILY] Error getting role for {name}: {e}")
    
    return {"papers": [{**paper, "author_affiliations": aff_map}]}

async def process_openalex_for_paper(state: Dict[str, Any]) -> Dict[str, Any]:
    """使用OpenAlex API获取作者的学术指标信息（citations, h_index, i10_index, orcid）"""
    paper = state.get("paper", {})
    paper_id = paper.get("id", "unknown")
    paper_title = paper.get("title", "Unknown")
    session_id = state.get("session_id")
    # Reduce verbose per-paper ORCID logs; keep processing minimal
    
    aff_map = paper.get("author_affiliations", []) or []
    
    if not aff_map:
        logger.info("No author affiliations found, skipping OpenAlex processing")
        return {"papers": [{**paper}]}
    
    # 为每个作者获取OpenAlex学术指标
    for item in aff_map:
        name = (item.get("name") or "").strip()
        affiliations = item.get("affiliations", [])
        
        if not name:
            continue
            
        # 使用第一个机构进行验证
        institution_name = affiliations[0] if affiliations else None
        
        try:
            academic_metrics = await asyncio.to_thread(
                get_author_academic_metrics,
                name,
                institution_name
            )
            
            if academic_metrics:
                # 更新作者的学术指标信息
                item["academic_metrics"] = academic_metrics
                logger.info(f"[OPENALEX] ✓ Retrieved metrics for {name}: citations={academic_metrics.get('citations', 'N/A')}, h-index={academic_metrics.get('h_index', 'N/A')}")
            else:
                logger.info(f"[OPENALEX] ✗ No metrics found for {name}")
                
        except Exception as e:
            logger.warning(f"[OPENALEX] Error getting metrics for {name}: {e}")
    
    return {"papers": [{**paper, "author_affiliations": aff_map}]}

def merge_paper_results(state: DataProcessingState) -> DataProcessingState:
    """Merge and deduplicate results from parallel ORCID processing.
    
    This function acts as a reducer that collects all parallel Send results
    from process_orcid_for_paper nodes and handles deduplication.
    """
    papers = state.get("papers", []) or []
    api_exhausted = state.get("api_exhausted", False)
    
    # Keep merge log minimal
    
    # 检查API耗尽状态
    for paper_result in papers:
        if isinstance(paper_result, dict) and paper_result.get("api_exhausted"):
            api_exhausted = True
            logger.warning(f"[MERGE] API quota exhausted detected in paper processing")
            break
    
    # 去重处理：基于arxiv_entry或id合并重复论文
    paper_map = {}
    duplicates_merged = 0
    skipped_invalid = 0
    
    for paper in papers:
        # 尝试多种ID字段作为去重键
        paper_key = paper.get("arxiv_entry") or paper.get("id") or paper.get("arxiv_id")
        
        if not paper_key:
            skipped_invalid += 1
            logger.debug(f"[MERGE] Paper missing identification fields, skipping: {paper.get('title', 'Unknown')[:50]}...")
            continue
        
        if paper_key in paper_map:
            duplicates_merged += 1
            logger.debug(f"[MERGE] Merging duplicate paper: {paper_key}")
            existing = paper_map[paper_key]
            # Merge ORCID data from parallel processing
            if "orcid_by_author" in paper:
                if "orcid_by_author" not in existing:
                    existing["orcid_by_author"] = {}
                existing["orcid_by_author"].update(paper["orcid_by_author"])
            # Merge other enriched data
            if "academic_metrics" in paper and "academic_metrics" not in existing:
                existing["academic_metrics"] = paper["academic_metrics"]
        else:
            paper_map[paper_key] = paper
    
    merged_papers = list(paper_map.values())
    
    # 简化日志输出，只在有重要信息时输出
    if duplicates_merged > 0:
        logger.info(f"[MERGE] Merged duplicates: {duplicates_merged}, invalid skipped: {skipped_invalid}")
    elif skipped_invalid > 0:
        logger.debug(f"[MERGE] Skipped {skipped_invalid} papers with missing ID fields")
    
    logger.info(f"[MERGE] {len(merged_papers)} unique papers ready for DB insertion")
    
    return {
        "papers": merged_papers,
        "api_exhausted": api_exhausted
    }

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

def dispatch_enrichment_processing(state: DataProcessingState):
    """Dispatch parallel enrichment jobs (OpenAlex + Tavily) for papers that have author_affiliations."""
    papers = state.get("papers", []) or []
    if not papers:
        return [Send("upsert_papers", state)]
    
    jobs = []
    for paper in papers:
        # Only process papers that have author_affiliations
        if paper.get("author_affiliations"):
            # 并行处理OpenAlex和Tavily
            jobs.append(Send("process_openalex_for_paper", {"paper": paper}))
            jobs.append(Send("process_tavily_homepage_for_paper", {"paper": paper}))
    
    if not jobs:
        # No papers need enrichment processing, go directly to upsert
        return [Send("upsert_papers", state)]
    
    return jobs

async def upsert_papers(state: DataProcessingState, config: RunnableConfig) -> DataProcessingState:
    """Create normalized schema and insert papers/authors/categories/affiliations."""
    try:
        papers: List[Dict[str, Any]] = state.get("papers", []) or []
        raw_papers: List[Dict[str, Any]] = state.get("raw_papers", []) or []
        
        # Use papers if available, otherwise use raw_papers
        papers_to_process = papers if papers else raw_papers
        
        if not papers_to_process:
            return {
                "processing_status": "completed",
                "inserted": 0,
                "skipped": 0,
                "fetched": state.get("fetched", 0)
            }
        
        db_uri = os.getenv("DATABASE_URL")
        if not db_uri:
            return {"processing_status": "error", "error_message": "DATABASE_URL not set"}
        
        await DatabaseManager.initialize(db_uri)

        logger.info(f"[UPSERT] Processing {len(papers_to_process)} papers for database insertion")
        
        try:
            # 使用信号量限制并发批次数量，避免过多数据库连接
            async with _BATCH_SEM:
                inserted, skipped = await _process_paper_batch_with_context(
                    papers_to_process
                )
            
            logger.info(f"Processing completed: {inserted} inserted, {skipped} skipped")
            
            return {
                "inserted": inserted,
                "skipped": skipped,
                "fetched": state.get("fetched", 0)
            }
                    
        except Exception as e:
            logger.error(f"Error processing papers: {str(e)}")
            return {
                "error_message": str(e),
                "inserted": 0,
                "skipped": 0
            }
        
    except Exception as e:
        return {
            "error_message": str(e)
        }

async def _process_paper_batch_with_context(
    papers_batch: List[Dict[str, Any]]
) -> tuple[int, int]:
    """处理单个论文批次的核心逻辑 - 使用连接上下文管理器"""
    inserted = 0
    skipped = 0
    
    async with DatabaseManager.get_connection() as conn:
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
                    # Build email, academic metrics, homepage, role, and date mapping from author_affiliations
                    author_email_map = {}
                    author_metrics_map = {}
                    author_homepage_map = {}
                    author_role_map = {}
                    author_start_date_map = {}
                    author_end_date_map = {}
                    for item in p.get("author_affiliations", []) or []:
                        name = (item.get("name") or "").strip()
                        email = item.get("email")
                        academic_metrics = item.get("academic_metrics")
                        homepage = item.get("homepage")
                        role = item.get("role")
                        start_date = item.get("start_date")
                        end_date = item.get("end_date")
                        if name and email:
                            author_email_map[name] = email
                        if name and academic_metrics:
                            author_metrics_map[name] = academic_metrics
                        if name and homepage:
                            author_homepage_map[name] = homepage
                        if name and role:
                            author_role_map[name] = role
                        if name and start_date:
                            author_start_date_map[name] = start_date
                        if name and end_date:
                            author_end_date_map[name] = end_date
                    
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
                        homepage = author_homepage_map.get(name_en)
                        
                        # If not in cache, try to find existing author by email or orcid
                        if email:
                            await cur.execute("SELECT id FROM authors WHERE email = %s LIMIT 1", (email,))
                            rowa = await cur.fetchone()
                            if rowa:
                                author_id = rowa[0]
                                # Update name, orcid, and homepage if we have them
                                try:
                                    await cur.execute(
                                        "UPDATE authors SET author_name_en = COALESCE(author_name_en, %s), orcid = COALESCE(orcid, %s), homepage = COALESCE(homepage, %s) WHERE id = %s",
                                        (name_en, orcid, homepage, author_id),
                                    )
                                except Exception:
                                    pass
                        
                        if not author_id and orcid:
                            await cur.execute("SELECT id FROM authors WHERE orcid = %s LIMIT 1", (orcid,))
                            rowa = await cur.fetchone()
                            if rowa:
                                author_id = rowa[0]
                                # Update name, email, and homepage if we have them
                                try:
                                    await cur.execute(
                                        "UPDATE authors SET author_name_en = COALESCE(author_name_en, %s), email = COALESCE(email, %s), homepage = COALESCE(homepage, %s) WHERE id = %s",
                                        (name_en, email, homepage, author_id),
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
                            # 从 OpenAlex 获取 ORCID
                            openalex_orcid = academic_metrics.get("orcid")
                            # 如果 OpenAlex 提供了 ORCID 且当前 ORCID 为空，则更新
                            if openalex_orcid and not orcid:
                                orcid = openalex_orcid
                        
                        # If no existing author found by email or orcid, create new one
                        if not author_id:
                            # Create new author with available information (email, orcid, and homepage can be NULL)
                            try:
                                await cur.execute(
                                    "INSERT INTO authors (author_name_en, email, orcid, citations, h_index, i10_index, homepage) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id", 
                                    (name_en, email, orcid, citations, h_index, i10_index, homepage)
                                )
                                rowa2 = await cur.fetchone()
                                if rowa2:
                                    author_id = rowa2[0]
                            except Exception as e:
                                # Handle unique constraint violations gracefully
                                logger.warning(f"Failed to insert author {name_en}: {e}")
                                continue
                        else:
                            # Update existing author with academic metrics, ORCID, and homepage if available
                            update_fields = []
                            update_values = []
                            if academic_metrics:
                                if citations is not None: update_fields.append("citations = COALESCE(%s, citations)"); update_values.append(citations)
                                if h_index is not None: update_fields.append("h_index = COALESCE(%s, h_index)"); update_values.append(h_index)
                                if i10_index is not None: update_fields.append("i10_index = COALESCE(%s, i10_index)"); update_values.append(i10_index)
                                # 仅当 OpenAlex 提供了 ORCID 且数据库中 ORCID 为空时才更新
                                if openalex_orcid and not orcid:
                                    update_fields.append("orcid = COALESCE(%s, orcid)"); update_values.append(openalex_orcid)
                            
                            # Update homepage if available
                            if homepage:
                                update_fields.append("homepage = COALESCE(%s, homepage)"); update_values.append(homepage)

                            if update_fields:
                                try:
                                    update_query = f"UPDATE authors SET {', '.join(update_fields)} WHERE id = %s"
                                    await cur.execute(update_query, (*update_values, author_id))
                                except Exception as e:
                                    logger.warning(f"Failed to update academic metrics or ORCID for author {name_en}: {e}")
                        
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

                    # Keywords and paper_keyword
                    for keyword in p.get("keywords", []):
                        if not keyword or not keyword.strip():
                            continue
                        keyword = keyword.strip().lower()  # 标准化关键词
                        keyword_id = None
                        await cur.execute("SELECT id FROM keywords WHERE keyword = %s LIMIT 1", (keyword,))
                        rowk = await cur.fetchone()
                        if rowk:
                            keyword_id = rowk[0]
                        else:
                            await cur.execute(
                                "INSERT INTO keywords (keyword) VALUES (%s) ON CONFLICT (keyword) DO NOTHING RETURNING id",
                                (keyword,),
                            )
                            rowk2 = await cur.fetchone()
                            if rowk2:
                                keyword_id = rowk2[0]
                            else:
                                await cur.execute("SELECT id FROM keywords WHERE keyword = %s LIMIT 1", (keyword,))
                                rowk3 = await cur.fetchone()
                                if rowk3:
                                    keyword_id = rowk3[0]
                        if keyword_id is not None:
                            await cur.execute(
                                """
                                INSERT INTO paper_keyword (paper_id, keyword_id)
                                VALUES (%s, %s)
                                ON CONFLICT (paper_id, keyword_id) DO NOTHING
                                """,
                                (paper_id, keyword_id),
                            )

                    # Affiliations and author_affiliation
                    for item in p.get("author_affiliations", []) or []:
                        name = (item.get("name") or "").strip()
                        if not name:
                            continue
                        author_id = author_name_to_id.get(name)
                        if not author_id:
                            continue
                        
                        # Get role and date information for this author
                        author_role = author_role_map.get(name)
                        author_start_date = author_start_date_map.get(name)
                        author_end_date = author_end_date_map.get(name)
                        
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
                            
                            # Upsert author_affiliation: include role information from Tavily/ORCID search
                            pub_dt = published_date
                            if author_role:
                                await cur.execute(
                                    """
                                    INSERT INTO author_affiliation (author_id, affiliation_id, latest_time, role)
                                    VALUES (%s, %s, %s, %s)
                                    ON CONFLICT (author_id, affiliation_id) DO UPDATE SET
                                      latest_time = GREATEST(COALESCE(author_affiliation.latest_time, EXCLUDED.latest_time), EXCLUDED.latest_time),
                                      role = COALESCE(EXCLUDED.role, author_affiliation.role)
                                    """,
                                    (author_id, aff_id, pub_dt, author_role),
                                )
                            else:
                                await cur.execute(
                                    """
                                    INSERT INTO author_affiliation (author_id, affiliation_id, latest_time)
                                    VALUES (%s, %s, %s)
                                    ON CONFLICT (author_id, affiliation_id) DO UPDATE SET
                                      latest_time = GREATEST(COALESCE(author_affiliation.latest_time, EXCLUDED.latest_time), EXCLUDED.latest_time)
                                    """,
                                    (author_id, aff_id, pub_dt),
                                )

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
    """Collect results from process_single_paper and prepare for ORCID processing.
    
    This function acts as a reducer node that automatically collects all parallel
    Send results from process_single_paper nodes via the papers field reducer.
    """
    papers = state.get("papers", []) or []
    logger.info(f"[COLLECT] Collected {len(papers)} papers with author_affiliations for ORCID processing")
    return state



# Build the state graph
builder = StateGraph(DataProcessingState)

builder.add_node("fetch_arxiv_today", fetch_arxiv_today)
builder.add_node("process_single_paper", process_single_paper)
builder.add_node("collect_single_paper_results", collect_single_paper_results)
builder.add_node("process_openalex_for_paper", process_openalex_for_paper)
builder.add_node("process_tavily_homepage_for_paper", process_tavily_homepage_for_paper)
builder.add_node("merge_paper_results", merge_paper_results)
builder.add_node("upsert_papers", upsert_papers)

builder.add_edge(START, "fetch_arxiv_today")
# Use conditional edges with Send for parallel map from fetch node
builder.add_conditional_edges(
    "fetch_arxiv_today",
    dispatch_affiliations,
)
# Connect process_single_paper to collector, then dispatch enrichment processing
builder.add_edge("process_single_paper", "collect_single_paper_results")
builder.add_conditional_edges(
    "collect_single_paper_results",
    dispatch_enrichment_processing,
)
# Connect enrichment processing nodes: OpenAlex and Tavily run in parallel
builder.add_edge("process_openalex_for_paper", "merge_paper_results")
builder.add_edge("process_tavily_homepage_for_paper", "merge_paper_results")
builder.add_edge("merge_paper_results", "upsert_papers")

# Connect upsert_papers to end
builder.add_edge("upsert_papers", END)

data_processing_graph = builder.compile()

async def build_data_processing_graph(checkpointer=None):
    """Build data processing graph with optional checkpointer."""
    if checkpointer:
        return builder.compile(checkpointer=checkpointer)
    return data_processing_graph
