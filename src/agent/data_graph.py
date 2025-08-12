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
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

import requests
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from src.agent.state import DataProcessingState
from src.db.database import DatabaseManager
from src.agent.prompts import AFFILIATION_SYSTEM_PROMPT, build_affiliation_user_prompt

logger = logging.getLogger(__name__)

ARXIV_QUERY_API = "https://export.arxiv.org/api/query"
HTTP_HEADERS = {"User-Agent": "arxiv-scraper/0.1 (+https://example.com)"}

# Bounded concurrency for Send tasks to avoid PDF/LLM rate limits
_AFF_MAX = int(os.getenv("AFFILIATION_MAX_CONCURRENCY", "4"))
_AFF_SEM = asyncio.Semaphore(_AFF_MAX)


# ---------------------- Fetch and parse arXiv ----------------------

def _parse_arxiv_atom(xml_text: str) -> List[Dict[str, Any]]:
    import xml.etree.ElementTree as ET

    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(xml_text)
    papers: List[Dict[str, Any]] = []

    for entry in root.findall("atom:entry", ns):
        full_id = (entry.findtext("atom:id", default="", namespaces=ns) or "").strip()
        base_id = full_id.rsplit("/", 1)[-1].split("v")[0]

        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()

        authors: List[str] = []
        for author in entry.findall("atom:author", ns):
            name = author.findtext("atom:name", default="", namespaces=ns)
            if name:
                authors.append(name.strip())

        categories: List[str] = []
        primary = entry.find("arxiv:primary_category", ns)
        if primary is not None and primary.get("term"):
            categories.append(primary.get("term"))
        for cat in entry.findall("atom:category", ns):
            term = cat.get("term")
            if term and term not in categories:
                categories.append(term)

        comment = None
        comment_el = entry.find("arxiv:comment", ns)
        if comment_el is not None and comment_el.text:
            comment = comment_el.text.strip()

        pdf_url = None
        for link in entry.findall("atom:link", ns):
            rel = link.get("rel"); href = link.get("href"); typ = link.get("type")
            if typ == "application/pdf":
                pdf_url = href
        if not pdf_url:
            pdf_url = f"https://arxiv.org/pdf/{base_id}"

        published_at = None
        published_text = entry.findtext("atom:published", default="", namespaces=ns)
        if published_text:
            try:
                published_at = datetime.fromisoformat(published_text.replace("Z", "+00:00"))
            except Exception:
                published_at = None

        updated_at = None
        updated_text = entry.findtext("atom:updated", default="", namespaces=ns)
        if updated_text:
            try:
                updated_at = datetime.fromisoformat(updated_text.replace("Z", "+00:00"))
            except Exception:
                updated_at = None

        papers.append({
            "id": base_id,
            "title": title,
            "summary": summary,
            "comment": comment,
            "authors": authors,
            "categories": categories,
            "pdf_url": pdf_url,
            "published_at": published_at.isoformat() if published_at else None,
            "updated_at": updated_at.isoformat() if updated_at else None,
        })

    return papers


def _build_search_query(categories: List[str], start_dt: datetime, end_dt: datetime) -> str:
    start_str = start_dt.strftime("%Y%m%d%H%M"); end_str = end_dt.strftime("%Y%m%d%H%M")
    date_window = f"(submittedDate:[{start_str} TO {end_str}] OR lastUpdatedDate:[{start_str} TO {end_str}])"
    cat_q = " OR ".join(f"cat:{c}" for c in categories) if categories else ""
    return f"{date_window} AND ({cat_q})" if cat_q else date_window


def _search_papers_by_window(categories: List[str], days: int, max_results: int = 200) -> List[Dict[str, Any]]:
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=max(1, days))
    search_query = _build_search_query(categories, start_dt, end_dt)

    results: List[Dict[str, Any]] = []
    page_size = min(100, max_results)
    start = 0

    while start < max_results:
        params = {
            "search_query": search_query,
            "start": start,
            "max_results": min(page_size, max_results - start),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        resp = requests.get(ARXIV_QUERY_API, params=params, headers=HTTP_HEADERS, timeout=30)
        resp.raise_for_status()
        papers = _parse_arxiv_atom(resp.text)
        if not papers:
            break
        results.extend(papers)
        if len(papers) < params["max_results"]:
            break
        start += params["max_results"]

    return results[:max_results]


def _iso_to_date(iso_str: Optional[str]) -> Optional[str]:
    if not iso_str:
        return None
    try:
        return iso_str[:10]
    except Exception:
        return None


# ---------------------- Nodes ----------------------

async def fetch_arxiv_today(state: DataProcessingState, config: RunnableConfig) -> DataProcessingState:
    """Fetch latest papers from arXiv within last N days (UTC)."""
    try:
        cfg = config.get("configurable", {}) if isinstance(config, dict) else {}
        categories: List[str] = cfg.get("categories") or [
            c.strip() for c in os.getenv("ARXIV_CATEGORIES", "cs.AI,cs.CV").split(",") if c.strip()
        ]
        days: int = int(cfg.get("days", 1))
        max_results: int = int(cfg.get("max_results", 200))

        raw = await asyncio.to_thread(_search_papers_by_window, categories, days, max_results)
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


def _create_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("AFFILIATION_MODEL", os.getenv("QWEN_MODEL", "qwen-max")),
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        temperature=0.0,
    )


def _download_first_page_text(pdf_url: str, timeout: int = 60) -> str:
    try:
        import pdfplumber
        from io import BytesIO

        r = requests.get(pdf_url, timeout=timeout, headers=HTTP_HEADERS)
        r.raise_for_status()
        with pdfplumber.open(BytesIO(r.content)) as pdf:
            if not pdf.pages:
                return ""
            first_page = pdf.pages[0]
            txt = first_page.extract_text() or ""
            return " ".join(txt.split())[:20000]
    except Exception:
        return ""


def _download_first_page_text_with_retries(pdf_url: str) -> str:
    for i in range(3):
        txt = _download_first_page_text(pdf_url)
        if txt:
            return txt
        # brief backoff
        try:
            import time
            time.sleep(0.4 * (i + 1))
        except Exception:
            pass
        continue
    return ""


async def process_single_paper(state: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single paper: fetch first page text and map author->affiliations via LLM.

    Input state must contain key `paper`. Returns {"papers": [enriched_paper]}.
    """
    paper = state.get("paper", {})
    authors = paper.get("authors", [])
    pdf_url = paper.get("pdf_url")
    if not authors or not pdf_url:
        return {"papers": [{**paper, "author_affiliations": []}]}

    async with _AFF_SEM:
        first_page_text = await asyncio.to_thread(_download_first_page_text_with_retries, pdf_url)
        if not first_page_text:
            return {"papers": [{**paper, "author_affiliations": []}]}

        llm = _create_llm()
        user_prompt = build_affiliation_user_prompt(authors, first_page_text)
        try:
            resp = await llm.ainvoke([
                SystemMessage(content=AFFILIATION_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ])
            content = resp.content.strip().strip("`")
            import re, json
            content = re.sub(r"^json\n", "", content, flags=re.IGNORECASE).strip()
            data = json.loads(content)
            mapped = []
            aff_by_name = { (a.get("name") or "").strip(): a.get("affiliations") or [] for a in data.get("authors", []) }
            for name in authors:
                aff = aff_by_name.get(name, [])
                aff = [s.strip() for s in aff if s and s.strip()]
                mapped.append({"name": name, "affiliations": aff})
            return {"papers": [{**paper, "author_affiliations": mapped}]}
        except Exception:
            return {"papers": [{**paper, "author_affiliations": []}]}


def dispatch_affiliations(state: DataProcessingState):
    """Dispatch parallel jobs using Send for each paper in `raw_papers`."""
    raw = state.get("raw_papers", []) or []
    if not raw:
        return []
    return [Send("process_single_paper", {"paper": p}) for p in raw]


async def upsert_papers(state: DataProcessingState, config: RunnableConfig) -> DataProcessingState:
    """Create normalized schema and insert papers/authors/categories/affiliations.
    DB writes remain in a single node to avoid deadlocks.
    """
    try:
        if state.get("processing_status") not in ("fetched", "completed"):
            return {"processing_status": "error", "error_message": "Nothing to upsert"}
        
        db_uri = os.getenv("DATABASE_URL")
        if not db_uri:
            return {"processing_status": "error", "error_message": "DATABASE_URL not set"}
        
        await DatabaseManager.initialize(db_uri)
        pool = await DatabaseManager.get_pool()

        inserted = 0; skipped = 0
        papers: List[Dict[str, Any]] = state.get("papers", []) or []
        
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await _create_schema_if_not_exists(cur)

                for p in papers:
                    paper_title = p.get("title")
                    published_date = _iso_to_date(p.get("published_at"))
                    updated_date = _iso_to_date(p.get("updated_at"))
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
                    except Exception:
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
                    for idx, name_en in enumerate(p.get("authors", []), start=1):
                        author_id = None
                        await cur.execute("SELECT id FROM authors WHERE author_name_en = %s LIMIT 1", (name_en,))
                        rowa = await cur.fetchone()
                        if rowa:
                            author_id = rowa[0]
                        else:
                            await cur.execute("INSERT INTO authors (author_name_en) VALUES (%s) RETURNING id", (name_en,))
                            rowa2 = await cur.fetchone()
                            if rowa2:
                                author_id = rowa2[0]
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
                            await cur.execute(
                                "INSERT INTO affiliations (aff_name) VALUES (%s) ON CONFLICT (aff_name) DO NOTHING RETURNING id",
                                (aff_name,),
                            )
                            rowaf = await cur.fetchone()
                            if rowaf and rowaf[0]:
                                aff_id = rowaf[0]
                            else:
                                await cur.execute("SELECT id FROM affiliations WHERE aff_name = %s LIMIT 1", (aff_name,))
                                rowaf2 = await cur.fetchone()
                                if not rowaf2:
                                    continue
                                aff_id = rowaf2[0]
                            await cur.execute(
                                """
                                INSERT INTO author_affiliation (author_id, affiliation_id)
                                VALUES (%s, %s)
                                ON CONFLICT (author_id, affiliation_id) DO NOTHING
                                """,
                                (author_id, aff_id),
                            )

        return {"processing_status": "completed", "inserted": inserted, "skipped": skipped}
    except Exception as e:
        return {"processing_status": "error", "error_message": str(e)}


# ---------------------- Schema creation ----------------------

async def _create_schema_if_not_exists(cur) -> None:
    """Create all tables and constraints per db_schema.md (simplified types with identity PK)."""
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS papers (
            id BIGSERIAL PRIMARY KEY,
            paper_title VARCHAR(300),
            published DATE,
            updated DATE,
            abstract TEXT,
            doi VARCHAR(100) UNIQUE,
            pdf_source VARCHAR(300),
            arxiv_entry VARCHAR(100) UNIQUE,
            UNIQUE (paper_title, published)
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS authors (
            id BIGSERIAL PRIMARY KEY,
            author_name_en VARCHAR(100),
            author_name_cn VARCHAR(100),
            email VARCHAR(100) UNIQUE,
            orcid VARCHAR(100) UNIQUE
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS affiliations (
            id BIGSERIAL PRIMARY KEY,
            aff_name VARCHAR(300) UNIQUE,
            aff_type VARCHAR(50),
            country VARCHAR(100),
            state VARCHAR(100),
            city VARCHAR(100)
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ranking_systems (
            id BIGSERIAL PRIMARY KEY,
            system_name VARCHAR(100) UNIQUE,
            update_frequency VARCHAR(50)
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS keywords (
            id BIGSERIAL PRIMARY KEY,
            keyword VARCHAR(300) UNIQUE
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id BIGSERIAL PRIMARY KEY,
            category VARCHAR(300) UNIQUE
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS people_verified (
            id BIGSERIAL PRIMARY KEY,
            name_en VARCHAR(300),
            name_cn VARCHAR(300)
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS author_paper (
            id BIGSERIAL PRIMARY KEY,
            author_id INT,
            paper_id INT,
            author_order INT NOT NULL,
            is_corresponding BOOLEAN,
            UNIQUE (author_id, paper_id),
            FOREIGN KEY (author_id) REFERENCES authors(id) ON DELETE CASCADE,
            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS author_affiliation (
            id BIGSERIAL PRIMARY KEY,
            author_id INT,
            affiliation_id INT,
            latest_time DATE,
            work VARCHAR(100),
            UNIQUE (author_id, affiliation_id),
            FOREIGN KEY (author_id) REFERENCES authors(id) ON DELETE CASCADE,
            FOREIGN KEY (affiliation_id) REFERENCES affiliations(id) ON DELETE CASCADE
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_category (
            id BIGSERIAL PRIMARY KEY,
            paper_id INT,
            category_id INT,
            UNIQUE (paper_id, category_id),
            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_keyword (
            id BIGSERIAL PRIMARY KEY,
            paper_id INT,
            keyword_id INT,
            UNIQUE (paper_id, keyword_id),
            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
            FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS affiliation_rankings (
            id BIGSERIAL PRIMARY KEY,
            aff_id INT,
            rank_system_id INT,
            rank_value VARCHAR(50),
            rank_year INT,
            UNIQUE (aff_id, rank_system_id, rank_year),
            FOREIGN KEY (aff_id) REFERENCES affiliations(id) ON DELETE CASCADE,
            FOREIGN KEY (rank_system_id) REFERENCES ranking_systems(id) ON DELETE CASCADE
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS author_people_verified (
            id BIGSERIAL PRIMARY KEY,
            author_id INT,
            people_verified_id INT,
            UNIQUE (author_id, people_verified_id),
            FOREIGN KEY (author_id) REFERENCES authors(id) ON DELETE CASCADE,
            FOREIGN KEY (people_verified_id) REFERENCES people_verified(id) ON DELETE CASCADE
        )
        """
    )


# ---------------------- Graph ----------------------

def _route(state: DataProcessingState) -> str:
    status = state.get("processing_status")
    if status == "fetched":
        return "fetch_arxiv_today"  # continue from sender node after map
    if status in {"completed", "error"}:
        return "__end__"


builder = StateGraph(DataProcessingState)

builder.add_node("fetch_arxiv_today", fetch_arxiv_today)
builder.add_node("process_single_paper", process_single_paper)
builder.add_node("upsert_papers", upsert_papers)

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

builder.add_edge("upsert_papers", END)

data_processing_graph = builder.compile()


async def build_data_processing_graph(checkpointer=None):
    if checkpointer:
        return builder.compile(checkpointer=checkpointer)
    return data_processing_graph
