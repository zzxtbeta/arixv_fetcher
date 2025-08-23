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
from datetime import datetime, timezone, timedelta, time
from typing import Dict, Any, List, Optional

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
    create_schema_if_not_exists
)

logger = logging.getLogger(__name__)

# Bounded concurrency for Send tasks to avoid PDF/LLM rate limits
_AFF_MAX = int(os.getenv("AFFILIATION_MAX_CONCURRENCY", "5"))
_AFF_SEM = asyncio.Semaphore(_AFF_MAX)
# Bounded concurrency for ORCID lookups
_ORCID_MAX = int(os.getenv("ORCID_MAX_CONCURRENCY", "5"))
_ORCID_SEM = asyncio.Semaphore(_ORCID_MAX)

# ---------------------- Node Functions ----------------------

async def fetch_arxiv_today(state: DataProcessingState, config: RunnableConfig) -> DataProcessingState:
    """Fetch latest papers from arXiv by date window, explicit date range or id_list."""
    try:
        cfg = config.get("configurable", {}) if isinstance(config, dict) else {}
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

        if id_list:
            raw = await asyncio.to_thread(search_papers_by_ids, id_list)
            logger.info(f"arXiv fetch by id_list: count={len(raw)}")
        else:
            # Prefer explicit date range if both provided
            if start_date and end_date:
                try:
                    sd = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    ed = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    start_dt = datetime.combine(sd.date(), time(0, 0, tzinfo=timezone.utc))
                    end_dt = datetime.combine(ed.date(), time(23, 59, tzinfo=timezone.utc))
                    raw = await asyncio.to_thread(search_papers_by_range, categories, start_dt, end_dt, max_results)
                    cats_label = ",".join(categories) if categories else "all"
                    # logger.info(f"arXiv fetch by range: {start_date} to {end_date}, categories={cats_label}, fetched={len(raw)}")
                except Exception:
                    raw = await asyncio.to_thread(search_papers_by_window, categories, days, max_results)
                    cats_label = ",".join(categories) if categories else "all"
                    # logger.info(f"arXiv fetch by window (fallback): days={days}, categories={cats_label}, fetched={len(raw)}")
            else:
                raw = await asyncio.to_thread(search_papers_by_window, categories, days, max_results)
                cats_label = ",".join(categories) if categories else "all"
                logger.info(f"arXiv fetch by window: days={days}, categories={cats_label}, fetched={len(raw)}")
        return {
            "processing_status": "fetched",
            "raw_papers": raw,
            "fetched": len(raw),
            # initialize accumulator for parallel map
            "papers": [],
            "categories": categories,
        }
    except Exception as e:
        return {"processing_status": "error", "error_message": str(e)}

async def process_single_paper(state: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single paper: fetch first page text and map author->affiliations via LLM.

    Input state must contain key `paper`. Returns {"papers": [enriched_paper]}.
    """
    paper = state.get("paper", {})
    title = (paper.get("title") or "(untitled)").strip()
    pub_label = iso_to_date(paper.get("published_at")) or "unknown"
    logger.info(f"Processing paper: '{title}' (published: {pub_label})")

    authors = paper.get("authors", [])
    pdf_url = paper.get("pdf_url")
    if not authors or not pdf_url:
        return {"papers": [{**paper, "author_affiliations": []}]}

    async with _AFF_SEM:
        first_page_text = await asyncio.to_thread(download_first_page_text_with_retries, pdf_url)
        if not first_page_text:
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
                mapped.append({"name": name, "affiliations": aff, "email": email})
            return {"papers": [{**paper, "author_affiliations": mapped}]}
        except Exception:
            return {"papers": [{**paper, "author_affiliations": []}]}

async def process_orcid_for_paper(state: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich a single paper using ORCID: per author, if ORCID record strictly matches name and
    the institution matches the paper-extracted affiliation, capture orcid and role/start/end.

    Output merges via accumulator: {"papers": [enriched_paper]} where enriched_paper carries:
      - orcid_by_author: {author_name -> orcid_id}
      - orcid_aff_meta: {author_name -> { norm_aff_key -> {role,start_date,end_date} }}
    """
    paper = state.get("paper", {})
    authors = paper.get("authors", []) or []
    aff_map = paper.get("author_affiliations", []) or []
    if not authors or not aff_map:
        return {"papers": [{**paper}]}
    orcid_by_author: Dict[str, str] = {}
    orcid_aff_meta: Dict[str, Dict[str, Dict[str, Optional[str]]]] = {}

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
        for cand in cands or []:
            for aff in pool_affs:
                best = best_aff_match_for_institution(aff, cand)
                if best:
                    return aff, {**cand, "_best": best}
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
        if isinstance(r, Exception) or not r:
            continue
        aff_used, info = r
        if not info:
            continue
        orcid_id = info.get("orcid_id")
        if orcid_id:
            orcid_by_author[name] = orcid_id
        best_aff = info.get("_best") or best_aff_match_for_institution(aff_used, info)
        if best_aff:
            # Combine role and department for complete role information
            role_title = (best_aff.get("role") or "").strip()
            department = (best_aff.get("department") or "").strip()
            
            if role_title and department:
                role = f"{role_title} ({department})"
            elif role_title:
                role = role_title
            elif department:
                role = department
            else:
                role = None
                
            sd = parse_orcid_date(best_aff.get("start_date") or "")
            ed = parse_orcid_date(best_aff.get("end_date") or "")
            norm_key = (" ".join((aff_used or "").split()).replace(" ", "").lower())
            orcid_aff_meta.setdefault(name, {})[norm_key] = {"role": role, "department": department, "start_date": sd, "end_date": ed}
    enriched = {**paper}
    if orcid_by_author:
        enriched["orcid_by_author"] = orcid_by_author
    if orcid_aff_meta:
        enriched["orcid_aff_meta"] = orcid_aff_meta
    return {"papers": [enriched]}

def dispatch_affiliations(state: DataProcessingState):
    """Dispatch parallel jobs using Send for each paper in `raw_papers`."""
    raw = state.get("raw_papers", []) or []
    if not raw:
        return []
    jobs = []
    for p in raw:
        jobs.append(Send("process_single_paper", {"paper": p}))
        jobs.append(Send("process_orcid_for_paper", {"paper": p}))
    return jobs

async def upsert_papers(state: DataProcessingState, config: RunnableConfig) -> DataProcessingState:
    """Create normalized schema and insert papers/authors/categories/affiliations.
    DB writes remain in a single node to avoid deadlocks.
    """
    try:
        # Allow upsert if we have papers to process, regardless of current status
        papers: List[Dict[str, Any]] = state.get("papers", []) or []
        raw_papers: List[Dict[str, Any]] = state.get("raw_papers", []) or []
        
        # Use papers if available, otherwise use raw_papers
        papers_to_process = papers if papers else raw_papers
        

        
        if not papers_to_process:
            return {"processing_status": "error", "error_message": "Nothing to upsert"}
        
        db_uri = os.getenv("DATABASE_URL")
        if not db_uri:
            return {"processing_status": "error", "error_message": "DATABASE_URL not set"}
        
        await DatabaseManager.initialize(db_uri)
        pool = await DatabaseManager.get_pool()

        inserted = 0; skipped = 0
        # papers variable already defined above
        
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await create_schema_if_not_exists(cur)
                # Prepare QS mapping and ranking systems once per transaction
                qs_map = get_qs_map()
                qs_names = get_qs_names()
                qs_sys_ids = await ensure_qs_ranking_systems(cur)

                for i, p in enumerate(papers_to_process):
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
                    author_name_to_id: Dict[str, int] = {}
                    # Build email mapping from author_affiliations
                    author_email_map = {}
                    for item in p.get("author_affiliations", []) or []:
                        name = (item.get("name") or "").strip()
                        email = item.get("email")
                        if name and email:
                            author_email_map[name] = email
                    
                    for idx, name_en in enumerate(p.get("authors", []), start=1):
                        author_id = None
                        email = author_email_map.get(name_en)
                        await cur.execute("SELECT id FROM authors WHERE author_name_en = %s LIMIT 1", (name_en,))
                        rowa = await cur.fetchone()
                        if rowa:
                            author_id = rowa[0]
                            # Update email if we have one and it's not already set
                            if email:
                                try:
                                    await cur.execute(
                                        "UPDATE authors SET email = COALESCE(email, %s) WHERE id = %s",
                                        (email, author_id),
                                    )
                                except Exception:
                                    pass
                        else:
                            if email:
                                await cur.execute("INSERT INTO authors (author_name_en, email) VALUES (%s, %s) RETURNING id", (name_en, email))
                            else:
                                await cur.execute("INSERT INTO authors (author_name_en) VALUES (%s) RETURNING id", (name_en,))
                            rowa2 = await cur.fetchone()
                            if rowa2:
                                author_id = rowa2[0]
                        if not author_id:
                            continue
                        author_name_to_id[name_en] = author_id
                        # Optional: update authors.orcid if provided by ORCID enrichment
                        ob = (p.get("orcid_by_author") or {}).get(name_en)
                        if ob:
                            try:
                                await cur.execute(
                                    "UPDATE authors SET orcid = COALESCE(orcid, %s) WHERE id = %s",
                                    (ob, author_id),
                                )
                            except Exception:
                                pass
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
                            # If ORCID meta present for this author-affiliation, update role/start/end conservatively
                            meta = ((p.get("orcid_aff_meta") or {}).get(name) or {}).get(norm_key)
                            if meta:
                                role = meta.get("role")
                                department = meta.get("department")
                                sd = meta.get("start_date"); ed = meta.get("end_date")
                                if role:
                                    try:
                                        await cur.execute(
                                            "UPDATE author_affiliation SET role = COALESCE(role, %s) WHERE author_id = %s AND affiliation_id = %s",
                                            (role, author_id, aff_id),
                                        )
                                    except Exception:
                                        pass
                                if department:
                                    try:
                                        await cur.execute(
                                            "UPDATE author_affiliation SET department = COALESCE(department, %s) WHERE author_id = %s AND affiliation_id = %s",
                                            (department, author_id, aff_id),
                                        )
                                    except Exception:
                                        pass
                                if sd:
                                    try:
                                        await cur.execute(
                                            "UPDATE author_affiliation SET start_date = LEAST(COALESCE(start_date, %s), %s) WHERE author_id = %s AND affiliation_id = %s",
                                            (sd, sd, author_id, aff_id),
                                        )
                                    except Exception:
                                        pass
                                if ed:
                                    try:
                                        await cur.execute(
                                            "UPDATE author_affiliation SET end_date = GREATEST(COALESCE(end_date, %s), %s) WHERE author_id = %s AND affiliation_id = %s",
                                            (ed, ed, author_id, aff_id),
                                        )
                                    except Exception:
                                        pass

                # Commit the transaction
                await conn.commit()

        return {"processing_status": "completed", "inserted": inserted, "skipped": skipped}
    except Exception as e:
        return {"processing_status": "error", "error_message": str(e)}

# ---------------------- Graph Construction ----------------------

def _route(state: DataProcessingState) -> str:
    """Route function for conditional edges."""
    status = state.get("processing_status")
    if status == "fetched":
        return "fetch_arxiv_today"  # continue from sender node after map
    if status in {"completed", "error"}:
        return "__end__"

# Build the state graph
builder = StateGraph(DataProcessingState)

builder.add_node("fetch_arxiv_today", fetch_arxiv_today)
builder.add_node("process_single_paper", process_single_paper)
builder.add_node("upsert_papers", upsert_papers)
builder.add_node("process_orcid_for_paper", process_orcid_for_paper)

builder.add_edge(START, "fetch_arxiv_today")
# Use conditional edges with Send for parallel map from fetch node
builder.add_conditional_edges(
    "fetch_arxiv_today",
    dispatch_affiliations,
)
# After all Send tasks complete, continue to upsert
builder.add_edge("fetch_arxiv_today", "upsert_papers")
# Also connect the Send target to the join so execution waits for all workers
builder.add_edge("process_single_paper", "upsert_papers")
builder.add_edge("process_orcid_for_paper", "upsert_papers")

builder.add_edge("upsert_papers", END)

data_processing_graph = builder.compile()

async def build_data_processing_graph(checkpointer=None):
    """Build data processing graph with optional checkpointer."""
    if checkpointer:
        return builder.compile(checkpointer=checkpointer)
    return data_processing_graph
