"""Dashboard API endpoints for overview stats and author-centric search."""

from typing import Dict, Any, List, Set, Optional
from datetime import datetime, timedelta, timezone, date
from fastapi import APIRouter, HTTPException, Query, Request

from src.db.supabase_client import supabase_client
from src.agent.data_graph import _orcid_search_and_pick, _best_aff_match_for_institution, _parse_orcid_date
from src.agent.data_graph import _orcid_candidates_by_name

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _gen_thread_id(prefix: str) -> str:
    try:
        import time, secrets
        return f"{prefix}-{int(time.time()*1000)}-{secrets.token_hex(4)}"
    except Exception:
        from datetime import datetime
        return f"{prefix}-{datetime.utcnow().timestamp()}"


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except Exception:
            return None
    return None


@router.get("/overview")
async def overview_stats() -> Dict[str, Any]:
    """Return high-level stats for the dashboard."""
    try:
        papers = supabase_client.count("papers")
        authors = supabase_client.count("authors")
        affiliations = supabase_client.count("affiliations")
        categories = supabase_client.count("categories")
        return {
            "papers": papers,
            "authors": authors,
            "affiliations": affiliations,
            "categories": categories,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"overview failed: {e}")


@router.post("/fetch-arxiv-by-id")
async def trigger_fetch_by_id(request: Request, ids: str = Query(..., description="Comma-separated arXiv IDs"), thread_id: Optional[str] = None) -> Dict[str, Any]:
    """Trigger data ingestion by explicit arXiv IDs using the same LangGraph flow."""
    try:
        id_list = [s.strip() for s in (ids or "").split(",") if s.strip()]
        if not id_list:
            raise HTTPException(status_code=400, detail="ids is required (comma-separated)")
        graph = request.app.state.data_processing_graph
        config = {"configurable": {"thread_id": thread_id or _gen_thread_id("dashboard-arxiv-by-id"), "id_list": id_list}}
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
        raise HTTPException(status_code=500, detail=f"fetch by id failed: {e}")


def _normalize_name(s: str) -> str:
    return "".join(ch for ch in s.lower() if not ch.isspace())


@router.get("/author")
async def author_search(q: str = Query(..., description="Fuzzy author name")) -> Dict[str, Any]:
    """Search an author (case-insensitive, ignore spaces) and return details.

    - Basic author info
    - Affiliations (distinct)
    - Recent papers
    - Top collaborators (co-authors by frequency)
    """
    try:
        norm_q = _normalize_name(q)
        # Primary: ilike by original input (fast path)
        candidates = supabase_client.select_ilike(
            table="authors",
            column="author_name_en",
            pattern=f"%{q}%",
            columns="id, author_name_en, orcid",
            order_by=("id", True),
            limit=100,
        ) or []
        # Secondary: handle inputs like "jiankeyu" vs "Jianke Yu" by space-insensitive matching
        # Fetch a wider batch and locally filter by normalized contains
        extra_pool = supabase_client.select(
            table="authors",
            columns="id, author_name_en, orcid",
            order_by=("id", True),
            limit=1000,
        ) or []
        if extra_pool:
            extra_filtered = [a for a in extra_pool if norm_q in _normalize_name(a.get("author_name_en") or "")]
        else:
            extra_filtered = []
        # Merge and de-duplicate by id
        by_id = {}
        for a in candidates + extra_filtered:
            aid = a.get("id")
            if aid and aid not in by_id:
                by_id[aid] = a
        candidates = list(by_id.values())[:100]
        if not candidates:
            return {"query": q, "results": []}

        results: List[Dict[str, Any]] = []
        for a in candidates:
            author_id = a.get("id")
            name = a.get("author_name_en")
            orcid = a.get("orcid")
            if not author_id:
                continue
            # Author's papers via author_paper
            aps = supabase_client.select("author_paper", filters={"author_id": author_id}, columns="paper_id, author_order")
            paper_ids = [r["paper_id"] for r in aps if r.get("paper_id")]
            # Recent papers (limited)
            recent = []
            if paper_ids:
                recent = supabase_client.select_in(
                    table="papers",
                    column="id",
                    values=paper_ids,
                    columns="id, paper_title, published, pdf_source, arxiv_entry",
                    order_by=("published", False),
                    limit=10,
                )
            # Affiliations
            affs = []
            aff_links = supabase_client.select("author_affiliation", filters={"author_id": author_id}, columns="affiliation_id, role, start_date, end_date, latest_time")
            aff_ids = [r.get("affiliation_id") for r in aff_links if r.get("affiliation_id")]
            if aff_ids:
                affs = supabase_client.select_in("affiliations", "id", aff_ids, columns="id, aff_name, country")
                # attach role/start/end/latest_time from link rows
                meta = {r.get("affiliation_id"): {"role": r.get("role"), "start_date": r.get("start_date"), "end_date": r.get("end_date"), "latest_time": r.get("latest_time")} for r in (aff_links or [])}
                for arow in affs or []:
                    fid = arow.get("id")
                    if fid in meta:
                        arow.update(meta[fid])
                # QS ranks enrichment for this author's affiliations
                rs = supabase_client.select_in("ranking_systems", "system_name", ["QS 2025", "QS 2024"], columns="id, system_name")
                sys_by_name = {r.get("system_name"): r.get("id") for r in rs}
                ar = supabase_client.select_in(
                    "affiliation_rankings",
                    "aff_id",
                    aff_ids,
                    columns="aff_id, rank_system_id, rank_value, rank_year",
                )
                from collections import defaultdict
                aff_to_qs = defaultdict(dict)
                for row in ar or []:
                    fid = row.get("aff_id"); sid = row.get("rank_system_id"); val = row.get("rank_value"); yr = row.get("rank_year")
                    if not fid or not sid:
                        continue
                    if sid == sys_by_name.get("QS 2025") or (yr == 2025):
                        aff_to_qs[fid]["y2025"] = val
                    if sid == sys_by_name.get("QS 2024") or (yr == 2024):
                        aff_to_qs[fid]["y2024"] = val
                for arow in affs:
                    fid = arow.get("id")
                    if fid in aff_to_qs:
                        arow["qs"] = aff_to_qs[fid]
            # Collaborators
            coll_counts: Dict[int, int] = {}
            if paper_ids:
                co_links = supabase_client.select_in("author_paper", "paper_id", paper_ids, columns="author_id, paper_id")
                for row in co_links:
                    co_id = row.get("author_id")
                    if not co_id or co_id == author_id:
                        continue
                    coll_counts[co_id] = coll_counts.get(co_id, 0) + 1
            top_collaborators: List[Dict[str, Any]] = []
            if coll_counts:
                # Fetch top N collaborator names
                top_ids = sorted(coll_counts, key=coll_counts.get, reverse=True)[:10]
                coll_rows = supabase_client.select_in("authors", "id", top_ids, columns="id, author_name_en")
                id_to_name = {r["id"]: r.get("author_name_en") for r in coll_rows}
                top_collaborators = [
                    {"id": aid, "name": id_to_name.get(aid), "count": coll_counts[aid]}
                    for aid in top_ids
                ]

            results.append(
                {
                    "author": {"id": author_id, "name": name, "orcid": orcid},
                    "affiliations": affs,
                    "recent_papers": recent,
                    "top_collaborators": top_collaborators,
                }
            )

        return {"query": q, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"author search failed: {e}")


@router.get("/latest-papers")
async def latest_papers(page: int = 1, limit: int = 20) -> Dict[str, Any]:
    """Return latest papers with authors and categories, paginated."""
    try:
        if page < 1:
            page = 1
        if limit < 1:
            limit = 20
        offset = (page - 1) * limit
        total = supabase_client.count("papers")
        papers = supabase_client.select(
            table="papers",
            columns="id, paper_title, published, pdf_source, arxiv_entry",
            order_by=("published", False),
            limit=limit,
            offset=offset,
        )
        if not papers:
            return {"items": [], "total": total, "page": page, "limit": limit}
        ids = [p["id"] for p in papers]
        # authors
        ap = supabase_client.select_in("author_paper", "paper_id", ids, columns="paper_id, author_id, author_order")
        author_ids = sorted({r["author_id"] for r in ap if r.get("author_id")})
        authors = supabase_client.select_in("authors", "id", author_ids, columns="id, author_name_en") if author_ids else []
        id_to_author = {a["id"]: a.get("author_name_en") for a in authors}
        paper_to_authors: Dict[int, List[Dict[str, Any]]] = {}
        for row in ap:
            pid = row.get("paper_id"); aid = row.get("author_id"); order = row.get("author_order")
            if not pid or not aid:
                continue
            paper_to_authors.setdefault(pid, []).append({"id": aid, "name": id_to_author.get(aid), "order": order})
        for k in paper_to_authors:
            paper_to_authors[k].sort(key=lambda x: (x.get("order") or 0))
        # categories
        pc = supabase_client.select_in("paper_category", "paper_id", ids, columns="paper_id, category_id")
        cat_ids = sorted({r["category_id"] for r in pc if r.get("category_id")})
        cats = supabase_client.select_in("categories", "id", cat_ids, columns="id, category") if cat_ids else []
        id_to_cat = {c["id"]: c.get("category") for c in cats}
        paper_to_cats: Dict[int, List[str]] = {}
        for row in pc:
            pid = row.get("paper_id"); cid = row.get("category_id")
            if not pid or not cid:
                continue
            paper_to_cats.setdefault(pid, []).append(id_to_cat.get(cid))
        # assemble
        items: List[Dict[str, Any]] = []
        for p in papers:
            pid = p["id"]
            items.append({
                "id": pid,
                "paper_title": p.get("paper_title"),
                "published": p.get("published"),
                "pdf_source": p.get("pdf_source"),
                "arxiv_entry": p.get("arxiv_entry"),
                "authors": paper_to_authors.get(pid, []),
                "categories": paper_to_cats.get(pid, []),
            })
        return {"items": items, "total": total, "page": page, "limit": limit}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"latest papers failed: {e}")


@router.get("/charts/affiliation-paper-count")
async def chart_affiliation_paper_count(days: int = 7) -> Dict[str, Any]:
    """Aggregate: number of distinct papers per affiliation in the last N days."""
    try:
        # 1) papers in window (fetch recent and filter locally to avoid SDK date op)
        now = datetime.now(timezone.utc).date()
        start_date = now - timedelta(days=days)
        papers_all = supabase_client.select(
            table="papers",
            columns="id, published",
            order_by=("published", False),
            limit=2000,
        )
        if not papers_all:
            return {"items": [], "days": days}
        papers = [p for p in papers_all if (_to_date(p.get("published")) or date.min) >= start_date]
        if not papers:
            return {"items": [], "days": days}
        paper_ids = [p["id"] for p in papers]
        # 2) author_paper within those papers
        ap = supabase_client.select_in("author_paper", "paper_id", paper_ids, columns="paper_id, author_id")
        if not ap:
            return {"items": [], "days": days}
        paper_to_authors: Dict[int, Set[int]] = {}
        for row in ap:
            pid = row.get("paper_id"); aid = row.get("author_id")
            if not pid or not aid:
                continue
            paper_to_authors.setdefault(pid, set()).add(aid)
        author_ids = sorted({aid for s in paper_to_authors.values() for aid in s})
        if not author_ids:
            return {"items": [], "days": days}
        # 3) author_affiliation for those authors
        aa = supabase_client.select_in("author_affiliation", "author_id", author_ids, columns="author_id, affiliation_id")
        aff_ids = sorted({r.get("affiliation_id") for r in aa if r.get("affiliation_id")}) if aa else []
        if not aff_ids:
            return {"items": [], "days": days}
        aff_rows = supabase_client.select_in("affiliations", "id", aff_ids, columns="id, aff_name")
        id_to_aff = {r["id"]: r.get("aff_name") for r in aff_rows}
        # 4) build map: affiliation -> set(paper_id)
        aff_to_papers: Dict[int, Set[int]] = {}
        # author -> affiliations
        author_to_affs: Dict[int, Set[int]] = {}
        for r in aa or []:
            a = r.get("author_id"); f = r.get("affiliation_id")
            if not a or not f:
                continue
            author_to_affs.setdefault(a, set()).add(f)
        for pid, authors_set in paper_to_authors.items():
            affs_for_paper: Set[int] = set()
            for a in authors_set:
                for f in author_to_affs.get(a, set()):
                    affs_for_paper.add(f)
            for f in affs_for_paper:
                aff_to_papers.setdefault(f, set()).add(pid)
        items = [
            {"affiliation": id_to_aff.get(fid, str(fid)), "count": len(pids)}
            for fid, pids in aff_to_papers.items()
        ]
        # sort desc by count
        items.sort(key=lambda x: x["count"], reverse=True)
        return {"items": items, "days": days}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"affiliation-paper-count failed: {e}")


@router.get("/charts/affiliation-author-count")
async def chart_affiliation_author_count(days: int = 7) -> Dict[str, Any]:
    """Aggregate: number of unique authors per affiliation in the last N days (authors who appeared in papers)."""
    try:
        now = datetime.now(timezone.utc).date()
        start_date = now - timedelta(days=days)
        # papers (fetch recent and filter locally)
        papers_all = supabase_client.select(
            table="papers",
            columns="id, published",
            order_by=("published", False),
            limit=2000,
        )
        if not papers_all:
            return {"items": [], "days": days}
        papers = [p for p in papers_all if (_to_date(p.get("published")) or date.min) >= start_date]
        if not papers:
            return {"items": [], "days": days}
        paper_ids = [p["id"] for p in papers]
        # authors for those papers
        ap = supabase_client.select_in("author_paper", "paper_id", paper_ids, columns="paper_id, author_id")
        author_ids = sorted({r.get("author_id") for r in ap if r.get("author_id")}) if ap else []
        if not author_ids:
            return {"items": [], "days": days}
        # author -> affiliation
        aa = supabase_client.select_in("author_affiliation", "author_id", author_ids, columns="author_id, affiliation_id")
        aff_to_authors: Dict[int, Set[int]] = {}
        for r in aa or []:
            a = r.get("author_id"); f = r.get("affiliation_id")
            if not a or not f:
                continue
            aff_to_authors.setdefault(f, set()).add(a)
        if not aff_to_authors:
            return {"items": [], "days": days}
        aff_ids = sorted(aff_to_authors.keys())
        aff_rows = supabase_client.select_in("affiliations", "id", aff_ids, columns="id, aff_name")
        id_to_aff = {r["id"]: r.get("aff_name") for r in aff_rows}
        items = [
            {"affiliation": id_to_aff.get(fid, str(fid)), "count": len(aids)}
            for fid, aids in aff_to_authors.items()
        ]
        items.sort(key=lambda x: x["count"], reverse=True)
        return {"items": items, "days": days}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"affiliation-author-count failed: {e}") 