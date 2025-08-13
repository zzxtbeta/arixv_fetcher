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
from datetime import datetime, timezone, timedelta, time
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

import csv
import re

logger = logging.getLogger(__name__)

ARXIV_QUERY_API = "https://export.arxiv.org/api/query"
HTTP_HEADERS = {"User-Agent": "arxiv-scraper/0.1 (+https://example.com)"}

def _log_json_sample(tag: str, obj: Any, limit: int = 2000) -> None:
    # Disabled verbose JSON logging to reduce noise
    pass

def _log_orcid_candidate(info: Dict[str, Any], matched: bool) -> None:
    # Simplified logging - only log matched candidates
    if matched:
        oid = info.get("orcid_id")
        disp = info.get("display_name")
        logger.info(f"ORCID candidate matched: {oid} ({disp})")

# Bounded concurrency for Send tasks to avoid PDF/LLM rate limits
_AFF_MAX = int(os.getenv("AFFILIATION_MAX_CONCURRENCY", "5"))
_AFF_SEM = asyncio.Semaphore(_AFF_MAX)
# Bounded concurrency for ORCID lookups
_ORCID_MAX = int(os.getenv("ORCID_MAX_CONCURRENCY", "5"))
_ORCID_SEM = asyncio.Semaphore(_ORCID_MAX)
_ORCID_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}
_ORCID_SESSION = None
_ORCID_CANDIDATES_CACHE: Dict[str, List[Dict[str, Any]]] = {}

# Reusable HTTP session for arXiv PDF downloads
_PDF_SESSION = None

def _pdf_session():
    global _PDF_SESSION
    if _PDF_SESSION is None:
        try:
            s = requests.Session()
            s.headers.update(HTTP_HEADERS)
            _PDF_SESSION = s
        except Exception:
            _PDF_SESSION = requests
    return _PDF_SESSION


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


def _search_papers_by_range(categories: List[str], start_dt: datetime, end_dt: datetime, max_results: int = 200) -> List[Dict[str, Any]]:
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


def _search_papers_by_window(categories: List[str], days: int, max_results: int = 200) -> List[Dict[str, Any]]:
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=max(1, days))
    return _search_papers_by_range(categories, start_dt, end_dt, max_results)


def _search_papers_by_ids(id_list: List[str]) -> List[Dict[str, Any]]:
    """Fetch papers by explicit arXiv id list using id_list param (batched)."""
    ids = [i.strip() for i in (id_list or []) if i and i.strip()]
    if not ids:
        return []
    # arXiv suggests batching (commonly <= 50 per call)
    batch_size = 50
    results: List[Dict[str, Any]] = []
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        params = {"id_list": ",".join(batch)}
        resp = requests.get(ARXIV_QUERY_API, params=params, headers=HTTP_HEADERS, timeout=30)
        resp.raise_for_status()
        results.extend(_parse_arxiv_atom(resp.text))
    return results


def _iso_to_date(iso_str: Optional[str]) -> Optional[str]:
    if not iso_str:
        return None
    try:
        return iso_str[:10]
    except Exception:
        return None


# ---------------------- Nodes ----------------------

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
            raw = await asyncio.to_thread(_search_papers_by_ids, id_list)
            logger.info(f"arXiv fetch by id_list: count={len(raw)}")
        else:
            # Prefer explicit date range if both provided
            if start_date and end_date:
                try:
                    sd = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    ed = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    start_dt = datetime.combine(sd.date(), time(0, 0, tzinfo=timezone.utc))
                    end_dt = datetime.combine(ed.date(), time(23, 59, tzinfo=timezone.utc))
                    raw = await asyncio.to_thread(_search_papers_by_range, categories, start_dt, end_dt, max_results)
                    cats_label = ",".join(categories) if categories else "all"
                    # logger.info(f"arXiv fetch by range: {start_date} to {end_date}, categories={cats_label}, fetched={len(raw)}")
                except Exception:
                    raw = await asyncio.to_thread(_search_papers_by_window, categories, days, max_results)
                    cats_label = ",".join(categories) if categories else "all"
                    # logger.info(f"arXiv fetch by window (fallback): days={days}, categories={cats_label}, fetched={len(raw)}")
            else:
                raw = await asyncio.to_thread(_search_papers_by_window, categories, days, max_results)
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
        # suppress noisy pdfminer warnings for malformed PDFs
        try:
            logging.getLogger("pdfminer").setLevel(logging.ERROR)
            logging.getLogger("pdfminer.pdfinterp").setLevel(logging.ERROR)
            logging.getLogger("pdfminer.cmapdb").setLevel(logging.ERROR)
        except Exception:
            pass

        sess = _pdf_session()
        r = sess.get(pdf_url, timeout=timeout, headers=HTTP_HEADERS)
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
            import time as _t
            _t.sleep(0.4 * (i + 1))
        except Exception:
            pass
        continue
    return ""


async def process_single_paper(state: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single paper: fetch first page text and map author->affiliations via LLM.

    Input state must contain key `paper`. Returns {"papers": [enriched_paper]}.
    """
    paper = state.get("paper", {})
    title = (paper.get("title") or "(untitled)").strip()
    pub_label = _iso_to_date(paper.get("published_at")) or "unknown"
    logger.info(f"Processing paper: '{title}' (published: {pub_label})")

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


# ---------------------- ORCID enrichment ----------------------

def _orcid_headers() -> Dict[str, str]:
    client_id = os.getenv("ORCID_CLIENT_ID")
    client_secret = os.getenv("ORCID_CLIENT_SECRET")
    headers = {"Accept": "application/json", "User-Agent": "arxiv-scraper/0.1"}
    # Public API works without auth; if member creds exist we could fetch token (omitted for brevity)
    # Keep headers minimal to avoid coupling
    return headers


def _orcid_session():
    global _ORCID_SESSION
    if _ORCID_SESSION is None:
        try:
            s = requests.Session()
            s.headers.update(_orcid_headers())
            _ORCID_SESSION = s
        except Exception:
            _ORCID_SESSION = requests
    return _ORCID_SESSION


def _orcid_base_urls() -> Dict[str, str]:
    # Use public API to avoid OAuth token handling; sufficient for read-public
    base = "https://pub.orcid.org/v3.0"
    return {"base": base, "search": f"{base}/search"}


def _normalize_name_for_strict(s: str) -> str:
    # Lowercase and collapse spaces for strict equality checks
    return " ".join((s or "").lower().split())


def _name_tokens(s: str) -> List[str]:
    txt = (s or "").lower()
    # split by non-alphanumerics and remove empties
    import re as _re
    return [t for t in _re.split(r"[^a-z0-9]+", txt) if t]


def _parse_orcid_date(d: str) -> Optional[str]:
    # ORCID may return dict {year, month, day} or strings like YYYY / YYYY-MM / YYYY-MM-DD
    if not d:
        return None
    try:
        # dict shape
        if isinstance(d, dict):
            y = (d.get("year") or {}).get("value") if isinstance(d.get("year"), dict) else d.get("year")
            m = (d.get("month") or {}).get("value") if isinstance(d.get("month"), dict) else d.get("month")
            day = (d.get("day") or {}).get("value") if isinstance(d.get("day"), dict) else d.get("day")
            if y and m and day:
                return f"{int(y):04d}-{int(m):02d}-{int(day):02d}"
            if y and m:
                return f"{int(y):04d}-{int(m):02d}"
            if y:
                return f"{int(y):04d}"
            return None
        # string shape
        txt = str(d).strip()
        if len(txt) == 4 and txt.isdigit():
            return f"{txt}-01-01"
        if len(txt) == 7 and txt[4] == '-':
            return f"{txt}-01"
        if len(txt) >= 10:
            return txt[:10]
        return None
    except Exception:
        return None


def _best_aff_match_for_institution(aff_name: str, scholar: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # Try to find best matching affiliation (employment first, then education)
    from difflib import SequenceMatcher
    target_norms = _normalize_aff_variants(aff_name)
    if not target_norms:
        return None
    def score_one(org: str, dept: str) -> float:
        best = 0.0
        for k in _normalize_aff_variants(org):
            for t in target_norms:
                best = max(best, SequenceMatcher(None, t, k).ratio())
        # dept helps if present
        if dept:
            for k in _normalize_aff_variants(dept):
                for t in target_norms:
                    best = max(best, SequenceMatcher(None, t, k).ratio())
        return best
    best_emp = None; best_emp_s = 0.0
    for e in (scholar.get("employments") or []):
        s = score_one(e.get("organization", ""), e.get("department", ""))
        if s > best_emp_s:
            best_emp_s = s; best_emp = e
    best_edu = None; best_edu_s = 0.0
    for e in (scholar.get("educations") or []):
        s = score_one(e.get("organization", ""), e.get("department", ""))
        if s > best_edu_s:
            best_edu_s = s; best_edu = e
    # Return best match if it meets threshold
    if best_emp and best_emp_s >= 0.86:
        return {"kind": "employment", **best_emp}
    if best_edu and best_edu_s >= 0.86:
        return {"kind": "education", **best_edu}
    return None


def _orcid_search_and_pick(name: str, institution: str, max_results: int = 10) -> Optional[Dict[str, Any]]:
    urls = _orcid_base_urls(); headers = _orcid_headers()
    # cache key: strict name + normalized institution
    key = f"{_normalize_name_for_strict(name)}|{_norm_string(institution)}"
    if key in _ORCID_CACHE:
        return _ORCID_CACHE[key]
    # Build query: name across given/family/other, with optional affiliation filter
    name = (name or "").strip()
    parts = name.split()
    if len(parts) >= 2:
        given = " ".join(parts[:-1]); family = parts[-1]
        name_query = f'(given-names:"{given}" AND family-name:"{family}") OR (given-names:"{name}" OR family-name:"{name}" OR other-names:"{name}")'
    else:
        name_query = f'(given-names:"{name}" OR family-name:"{name}" OR other-names:"{name}")'
    if institution:
        query = f'({name_query}) AND affiliation-org-name:"{institution}"'
    else:
        query = name_query
    try:
        sess = _orcid_session()
        r = sess.get(urls["search"], params={"q": query, "rows": max_results}, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        results = data.get("result") or []
        if not results:
            _ORCID_CACHE[key] = None
            return None
        # Fetch details for candidates and apply strict name check then institution match
        def fetch_details(orcid_id: str) -> Optional[Dict[str, Any]]:
            base = urls["base"]
            # person
            p = sess.get(f"{base}/{orcid_id}/person", headers=headers, timeout=10)
            person = p.json() if p.status_code == 200 else {}
            # employments
            e = sess.get(f"{base}/{orcid_id}/employments", headers=headers, timeout=10)
            emp = e.json() if e.status_code == 200 else {}
            # educations
            d = sess.get(f"{base}/{orcid_id}/educations", headers=headers, timeout=10)
            edu = d.json() if d.status_code == 200 else {}
            # parse to simple structure compatible with our helper
            # reuse parsing shape of orcid_api.py
            def parse_person(pd: Dict[str, Any]) -> Dict[str, Any]:
                out = {"display_name": "", "given_names": "", "family_name": "", "other_names": []}
                name_obj = (pd or {}).get("name") or {}
                if name_obj:
                    gn = (name_obj.get("given-names") or {}).get("value") if name_obj.get("given-names") else ""
                    fn = (name_obj.get("family-name") or {}).get("value") if name_obj.get("family-name") else ""
                    out["given_names"] = gn or ""; out["family_name"] = fn or ""; out["display_name"] = f"{gn} {fn}".strip()
                ons = []
                other = (pd or {}).get("other-names") or {}
                if other.get("other-name"):
                    for item in other.get("other-name"):
                        if item and item.get("content"):
                            ons.append(item.get("content"))
                out["other_names"] = ons
                return out
            def parse_affs(ad: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
                out: List[Dict[str, Any]] = []
                for group in (ad or {}).get("affiliation-group", []) or []:
                    for s in (group or {}).get("summaries", []) or []:
                        if not s or key not in s:
                            continue
                        sd = s[key]
                        org = (sd or {}).get("organization", {}) or {}
                        out.append({
                            "organization": org.get("name", "") or "",
                            "department": (sd or {}).get("department-name", "") or "",
                            "role": (sd or {}).get("role-title", "") or "",
                            "start_date": (sd or {}).get("start-date"),
                            "end_date": (sd or {}).get("end-date"),
                        })
                # format dates
                for item in out:
                    item["start_date"] = _orcid_format_date(item["start_date"])
                    item["end_date"] = _orcid_format_date(item["end_date"])
                return out
            def _orcid_format_date(obj: Any) -> str:
                if not obj:
                    return ""
                try:
                    y = (obj.get("year") or {}).get("value"); m = (obj.get("month") or {}).get("value"); d = (obj.get("day") or {}).get("value")
                    if y and m and d:
                        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
                    if y and m:
                        return f"{int(y):04d}-{int(m):02d}"
                    if y:
                        return f"{int(y):04d}"
                except Exception:
                    return ""
                return ""
            info = {"orcid_id": orcid_id}
            info.update(parse_person(person))
            info["employments"] = parse_affs(emp, "employment-summary")
            info["educations"] = parse_affs(edu, "education-summary")
            return info
        # Evaluate candidates
        cand: List[Dict[str, Any]] = []
        name_norm = _normalize_name_for_strict(name)
        for r in results:
            orcid_id = ((r or {}).get("orcid-identifier") or {}).get("path")
            if not orcid_id:
                continue
            try:
                info = fetch_details(orcid_id)
            except Exception:
                continue
            if not info:
                continue
            # Strict name equality check
            disp = _normalize_name_for_strict(info.get("display_name", ""))
            gn = _normalize_name_for_strict(info.get("given_names", ""))
            fn = _normalize_name_for_strict(info.get("family_name", ""))
            strict_ok = name_norm == disp or name_norm == f"{gn} {fn}".strip()
            if not strict_ok:
                continue
            # Institution match
            if institution:
                best = _best_aff_match_for_institution(institution, info)
                if not best:
                    continue
            cand.append(info)
        picked = cand[0] if cand else None
        _ORCID_CACHE[key] = picked
        return picked
    except Exception:
        return None


def _orcid_candidates_by_name(name: str, max_candidates: int = 5) -> List[Dict[str, Any]]:
    """Return up to N ORCID candidate profiles that strictly match the author's name.

    Strict match rules:
    - display_name equals name (normalized) OR
    - given_names + family_name equals name (normalized)
    """
    key = f"cands|{_normalize_name_for_strict(name)}|{max_candidates}"
    if key in _ORCID_CANDIDATES_CACHE:
        return _ORCID_CANDIDATES_CACHE[key]
    urls = _orcid_base_urls(); headers = _orcid_headers(); sess = _orcid_session()
    # name-only search to gather a small pool
    name = (name or "").strip()
    parts = name.split()
    if len(parts) >= 2:
        given = " ".join(parts[:-1]); family = parts[-1]
        name_query = f'(given-names:"{given}" AND family-name:"{family}") OR (given-names:"{name}" OR family-name:"{name}" OR other-names:"{name}")'
    else:
        name_query = f'(given-names:"{name}" OR family-name:"{name}" OR other-names:"{name}")'
    try:
        # fetch a wider pool to avoid missing exact match due to ranking
        r = sess.get(urls["search"], params={"q": name_query, "rows": 100}, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json(); results = data.get("result") or []
        # log raw classic search results (truncated)
        _log_json_sample("search", results[:10])
        out: List[Dict[str, Any]] = []
        for row in results:
            if len(out) >= max_candidates:
                break
            orcid_id = ((row or {}).get("orcid-identifier") or {}).get("path")
            if not orcid_id:
                continue
            # fetch details
            try:
                base = urls["base"]
                p = sess.get(f"{base}/{orcid_id}/person", headers=headers, timeout=10)
                person = p.json() if p.status_code == 200 else {}
                e = sess.get(f"{base}/{orcid_id}/employments", headers=headers, timeout=10)
                emp = e.json() if e.status_code == 200 else {}
                d = sess.get(f"{base}/{orcid_id}/educations", headers=headers, timeout=10)
                edu = d.json() if d.status_code == 200 else {}
            except Exception as ex:
                logger.warning(f"ORCID fetch failed for {orcid_id}: {ex}")
                continue
            # parse
            def parse_person(pd: Dict[str, Any]) -> Dict[str, Any]:
                outp = {"display_name": "", "given_names": "", "family_name": "", "other_names": []}
                name_obj = (pd or {}).get("name") or {}
                if name_obj:
                    gn = (name_obj.get("given-names") or {}).get("value") if name_obj.get("given-names") else ""
                    fn = (name_obj.get("family-name") or {}).get("value") if name_obj.get("family-name") else ""
                    outp["given_names"] = gn or ""; outp["family_name"] = fn or ""; outp["display_name"] = f"{gn} {fn}".strip()
                other = (pd or {}).get("other-names") or {}
                ons = []
                if other.get("other-name"):
                    for item in other.get("other-name"):
                        if item and item.get("content"):
                            ons.append(item.get("content"))
                outp["other_names"] = ons
                return outp
            def parse_affs(ad: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
                items: List[Dict[str, Any]] = []
                for group in (ad or {}).get("affiliation-group", []) or []:
                    for s in (group or {}).get("summaries", []) or []:
                        if not s or key not in s:
                            continue
                        sd = s[key]
                        org = (sd or {}).get("organization", {}) or {}
                        items.append({
                            "organization": org.get("name", "") or "",
                            "department": (sd or {}).get("department-name", "") or "",
                            "role": (sd or {}).get("role-title", "") or "",
                            "start_date": _parse_orcid_date((sd or {}).get("start-date")),
                            "end_date": _parse_orcid_date((sd or {}).get("end-date")),
                        })
                # format dates
                for it in items:
                    it["start_date"] = _parse_orcid_date(it["start_date"]) if isinstance(it.get("start_date"), str) else _parse_orcid_date("")
                    it["end_date"] = _parse_orcid_date(it["end_date"]) if isinstance(it.get("end_date"), str) else _parse_orcid_date("")
                return items
            info = {"orcid_id": orcid_id}
            info.update(parse_person(person))
            info["employments"] = parse_affs(emp, "employment-summary")
            info["educations"] = parse_affs(edu, "education-summary")
            # strict name check (display_name or given+family or any other_names)
            target = _name_tokens(name)
            disp_t = _name_tokens(info.get("display_name", ""))
            gn_t = _name_tokens(info.get("given_names", ""))
            fn_t = _name_tokens(info.get("family_name", ""))
            full_gf = gn_t + fn_t if (gn_t or fn_t) else []
            other_list = (info.get("other_names") or [])
            other_ts = [_name_tokens(x) for x in other_list]
            def eq_tokens(a, b):
                return a == b or a == list(reversed(b))
            matched = (
                (disp_t and eq_tokens(disp_t, target))
                or (full_gf and eq_tokens(full_gf, target))
                or any(eq_tokens(t, target) for t in other_ts if t)
            )
            _log_orcid_candidate(info, matched)
            if matched:
                out.append(info)
        # Fallback: use expanded-search if no strict candidate found from classic search
        if len(out) < max_candidates:
            # derive given and family from tokens (last token as family)
            toks = _name_tokens(name)
            if toks:
                given = " ".join(toks[:-1]) if len(toks) > 1 else toks[0]
                family = toks[-1]
                try:
                    er = sess.get(
                        f"{urls['base']}/expanded-search",
                        params={"q": f"given-names:{given} AND family-name:{family}", "rows": 20},
                        headers=headers,
                        timeout=15,
                    )
                    if er.status_code == 200:
                        edata = er.json() or {}
                        eitems = edata.get("result") or edata.get("expanded-result") or []
                        # log raw expanded-search results (truncated)
                        _log_json_sample("expanded-search", eitems[:10])
                        ids: List[str] = []
                        for it in eitems:
                            oid = (it.get("orcid-id") if isinstance(it, dict) else None) or ((it.get("orcid-identifier") or {}).get("path") if isinstance(it, dict) else None)
                            if oid:
                                ids.append(str(oid))
                        # fetch details for ids and apply the same strict check
                        for oid in ids:
                            if len(out) >= max_candidates:
                                break
                            try:
                                p = sess.get(f"{urls['base']}/{oid}/person", headers=headers, timeout=10)
                                person = p.json() if p.status_code == 200 else {}
                                e = sess.get(f"{urls['base']}/{oid}/employments", headers=headers, timeout=10)
                                emp = e.json() if e.status_code == 200 else {}
                                d = sess.get(f"{urls['base']}/{oid}/educations", headers=headers, timeout=10)
                                edu = d.json() if d.status_code == 200 else {}
                            except Exception as ex:
                                logger.warning(f"ORCID fetch failed for {oid}: {ex}")
                                continue
                            info = {"orcid_id": oid}
                            # reuse parsers
                            def parse_person(pd: Dict[str, Any]) -> Dict[str, Any]:
                                outp = {"display_name": "", "given_names": "", "family_name": "", "other_names": []}
                                name_obj = (pd or {}).get("name") or {}
                                if name_obj:
                                    gn = (name_obj.get("given-names") or {}).get("value") if name_obj.get("given-names") else ""
                                    fn = (name_obj.get("family-name") or {}).get("value") if name_obj.get("family-name") else ""
                                    outp["given_names"] = gn or ""; outp["family_name"] = fn or ""; outp["display_name"] = f"{gn} {fn}".strip()
                                other = (pd or {}).get("other-names") or {}
                                ons = []
                                if other.get("other-name"):
                                    for item in other.get("other-name"):
                                        if item and item.get("content"):
                                            ons.append(item.get("content"))
                                outp["other_names"] = ons
                                return outp
                            def parse_affs(ad: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
                                items: List[Dict[str, Any]] = []
                                for group in (ad or {}).get("affiliation-group", []) or []:
                                    for s in (group or {}).get("summaries", []) or []:
                                        if not s or key not in s:
                                            continue
                                        sd = s[key]
                                        org = (sd or {}).get("organization", {}) or {}
                                        items.append({
                                            "organization": org.get("name", "") or "",
                                            "department": (sd or {}).get("department-name", "") or "",
                                            "role": (sd or {}).get("role-title", "") or "",
                                            "start_date": _parse_orcid_date((sd or {}).get("start-date")),
                                            "end_date": _parse_orcid_date((sd or {}).get("end-date")),
                                        })
                                for it in items:
                                    it["start_date"] = _parse_orcid_date(it["start_date"]) if isinstance(it.get("start_date"), str) else _parse_orcid_date("")
                                    it["end_date"] = _parse_orcid_date(it["end_date"]) if isinstance(it.get("end_date"), str) else _parse_orcid_date("")
                                return items
                            info.update(parse_person(person))
                            info["employments"] = parse_affs(emp, "employment-summary")
                            info["educations"] = parse_affs(edu, "education-summary")
                            # strict token check again
                            target = _name_tokens(name)
                            disp_t = _name_tokens(info.get("display_name", ""))
                            gn_t = _name_tokens(info.get("given_names", ""))
                            fn_t = _name_tokens(info.get("family_name", ""))
                            full_gf = gn_t + fn_t if (gn_t or fn_t) else []
                            other_list = (info.get("other_names") or [])
                            other_ts = [_name_tokens(x) for x in other_list]
                            def eq_tokens(a, b):
                                return a == b or a == list(reversed(b))
                            matched2 = (
                                (disp_t and eq_tokens(disp_t, target))
                                or (full_gf and eq_tokens(full_gf, target))
                                or any(eq_tokens(t, target) for t in other_ts if t)
                            )
                            _log_orcid_candidate(info, matched2)
                            if matched2:
                                out.append(info)
                except Exception:
                    pass
        _ORCID_CANDIDATES_CACHE[key] = out
        return out
    except Exception as ex:
        try:
            logger.exception(f"ORCID candidates error for name='{name}': {ex}")
        except Exception:
            pass
        # return whatever was accumulated so far to avoid silent drops
        return locals().get('out', [])


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
            cands = await asyncio.to_thread(_orcid_candidates_by_name, name, 5)
        for cand in cands or []:
            for aff in pool_affs:
                best = _best_aff_match_for_institution(aff, cand)
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
        best_aff = info.get("_best") or _best_aff_match_for_institution(aff_used, info)
        if best_aff:
            # Combine role and department for complete role information
            role_title = (best_aff.get("role") or "").strip()
            department = (best_aff.get("department") or "").strip()
            
            # Only store actual roles, not department names as roles
            if role_title and department:
                role = f"{role_title} ({department})"
            elif role_title:
                role = role_title
            else:
                # Don't use department as role if no actual role exists
                role = None
                
            sd = _parse_orcid_date(best_aff.get("start_date") or "")
            ed = _parse_orcid_date(best_aff.get("end_date") or "")
            norm_key = (" ".join((aff_used or "").split()).replace(" ", "").lower())
            orcid_aff_meta.setdefault(name, {})[norm_key] = {"role": role, "start_date": sd, "end_date": ed}
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
                # Prepare QS mapping and ranking systems once per transaction
                qs_map = _get_qs_map()
                qs_names = _get_qs_names()
                qs_sys_ids = await _ensure_qs_ranking_systems(cur)

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
                            await _enrich_affiliation_from_qs(cur, aff_id, cleaned, qs_map, qs_names, qs_sys_ids)
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
                                sd = meta.get("start_date"); ed = meta.get("end_date")
                                if role:
                                    try:
                                        await cur.execute(
                                            "UPDATE author_affiliation SET role = COALESCE(role, %s) WHERE author_id = %s AND affiliation_id = %s",
                                            (role, author_id, aff_id),
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
            role TEXT,
            start_date DATE,
            end_date DATE,
            latest_time DATE,
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


# ---------------------- Helpers: QS rankings enrichment ----------------------

_QS_CACHE_MAP: Optional[Dict[str, Dict[str, Any]]] = None
_QS_CACHE_NAMES: Optional[List[Dict[str, Any]]] = None


def _norm_string(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


_DEPT_PREFIX = re.compile(r"^(department|dept\.?|school|faculty|college|laboratory|laboratories|lab|centre|center|institute|institutes|academy|division|unit)\s+of\s+", re.IGNORECASE)


def _strip_parentheses(s: str) -> str:
    return re.sub(r"\([^\)]*\)", "", s or "").strip()


def _first_segment_before_comma(s: str) -> str:
    return (s or "").split(",", 1)[0].strip()


def _last_segment_after_comma(s: str) -> str:
    parts = [p.strip() for p in (s or "").split(",") if p and p.strip()]
    if not parts:
        return (s or "").strip()
    return parts[-1]


def _strip_dept_prefix(s: str) -> str:
    return _DEPT_PREFIX.sub("", s or "").strip()


def _normalize_aff_variants(name: str) -> List[str]:
    """Generate normalized variants of an affiliation name for fuzzy matching.
    
    Args:
        name: The original affiliation name
        
    Returns:
        List of normalized variants (lowercased, alphanumeric only)
    """
    if not name or not name.strip():
        return []
    
    # Generate text candidates through various transformations
    tail1 = _last_segment_after_comma(name)
    tail2 = ", ".join([p.strip() for p in name.split(",")[-2:]]) if "," in name else name
    
    candidates = [
        name,
        _strip_parentheses(name),
        _first_segment_before_comma(name),
        _strip_dept_prefix(name),
        _strip_dept_prefix(_first_segment_before_comma(name)),
        _strip_dept_prefix(_strip_parentheses(name)),
        tail1,
        _strip_dept_prefix(tail1),
        tail2,
    ]
    
    # Include article-stripped forms (e.g., "The University" -> "University")
    candidates += [_strip_articles(c) for c in candidates]
    
    # Define organization keywords (academic + corporate)
    org_keywords = re.compile(
        r'\b(university|institute|college|academy|polytechnic|universit[eé]|universidad|universita|'
        r'group|corp|corporation|company|ltd|limited|inc|incorporated|llc|co\.|gmbh|sa|ag|bv|pty|pte|'
        r'technologies|tech|lab|labs|laboratory|laboratories|research|systems|solutions|international|global)\b', 
        re.IGNORECASE
    )
    
    # Normalize and deduplicate
    norms = []
    for c in candidates:
        if not c or not c.strip():
            continue
            
        # For tail segments, ensure they contain recognizable organization keywords
        if c in (tail1, _strip_dept_prefix(tail1), tail2):
            if not org_keywords.search(c):
                continue
                
        normalized = _norm_string(c)
        if normalized and normalized not in norms:
            norms.append(normalized)
    
    return norms
 

def _strip_articles(s: str) -> str:
    # Remove leading English articles
    return re.sub(r"^(\s*(the|a|an)\s+)", "", (s or ""), flags=re.IGNORECASE).strip()


def _build_acronym(s: str) -> str:
    # Build acronym from words, skipping small connectors but keeping key tokens like University
    tokens = re.split(r"[^A-Za-z]+", s or "")
    skip = {"of", "and", "for", "at", "in", "on"}
    letters = [t[0] for t in tokens if t and t.lower() not in skip]
    return ("".join(letters)).lower()


def _project_root() -> str:
    # src/agent/data_graph.py → up two levels to project root
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _qs_csv_path() -> str:
    # resource/qs-world-rankings-2025.csv located at project root /resource
    return os.path.join(_project_root(), "resource", "qs-world-rankings-2025.csv")


def _load_qs_rankings() -> tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    path = _qs_csv_path()
    mapping: Dict[str, Dict[str, Any]] = {}
    names: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # helper to resolve headers even with NBSP/spacing/case differences
            def _norm_header(s: str) -> str:
                txt = (s or "")
                # remove BOM and zero-width characters
                txt = txt.replace("\ufeff", "").replace("\u200b", "")
                # normalize spaces and case
                txt = txt.replace("\xa0", " ")
                txt = re.sub(r"\s+", " ", txt).strip().lower()
                return txt
            header_map = { _norm_header(h): h for h in (reader.fieldnames or []) }
            def _get(row: dict, keys: List[str]) -> str:
                for k in keys:
                    hk = header_map.get(_norm_header(k))
                    if hk in row:
                        return (row.get(hk) or "").strip()
                # last try: iterate row keys
                for rk in row.keys():
                    if _norm_header(rk) in [_norm_header(k) for k in keys]:
                        return (row.get(rk) or "").strip()
                return ""
            for row in reader:
                inst = _get(row, ["Institution Name", "institution", "name"]) 
                if not inst:
                    continue
                # base record
                country = _get(row, ["Location Full", "Location", "Country"]) 
                r2025 = _get(row, ["2025 Rank", "Rank 2025", "2025"]) 
                r2024 = _get(row, ["2024 Rank", "Rank 2024", "2024"]) 
                rec = {"name": inst, "country": country, "r2025": r2025, "r2024": r2024}
                # build multiple normalized keys for better coverage
                keys = _normalize_aff_variants(inst)
                # add parenthetical aliases as additional variants (e.g., "UNSW Sydney")
                try:
                    pars = re.findall(r"\(([^)]*)\)", inst)
                    for txt in pars:
                        for k in _normalize_aff_variants(txt):
                            if k not in keys:
                                keys.append(k)
                except Exception:
                    pass
                # add acronym variant (e.g., "UNSW")
                acr = _build_acronym(inst)
                if acr and acr not in keys:
                    keys.append(acr)
                for k in keys:
                    mapping.setdefault(k, rec)
                # store for fuzzy fallback with its normalized variants
                names.append({"name": inst, "rec": rec, "norms": keys})
    except Exception:
        # If CSV missing or unreadable, keep empty mapping to avoid breaking pipeline
        mapping = {}
        names = []
    return mapping, names


def _get_qs_map() -> Dict[str, Dict[str, Any]]:
    global _QS_CACHE_MAP, _QS_CACHE_NAMES
    if _QS_CACHE_MAP is None:
        _QS_CACHE_MAP, _QS_CACHE_NAMES = _load_qs_rankings()
    return _QS_CACHE_MAP or {}


def _get_qs_names() -> List[Dict[str, Any]]:
    global _QS_CACHE_MAP, _QS_CACHE_NAMES
    if _QS_CACHE_NAMES is None:
        _QS_CACHE_MAP, _QS_CACHE_NAMES = _load_qs_rankings()
    return _QS_CACHE_NAMES or []


async def _ensure_qs_ranking_systems(cur) -> Dict[int, int]:
    """Ensure ranking systems for QS 2025 and QS 2024 exist; return {year: id}."""
    systems = {2025: "QS 2025", 2024: "QS 2024"}
    out: Dict[int, int] = {}
    for year, name in systems.items():
        await cur.execute(
            "INSERT INTO ranking_systems (system_name, update_frequency) VALUES (%s, %s) ON CONFLICT (system_name) DO NOTHING RETURNING id",
            (name, "annual"),
        )
        row = await cur.fetchone()
        if row and row[0]:
            out[year] = row[0]
        else:
            await cur.execute("SELECT id FROM ranking_systems WHERE system_name = %s LIMIT 1", (name,))
            row2 = await cur.fetchone()
            if row2:
                out[year] = row2[0]
    return out


def _find_qs_record_for_aff(name: str, qs_map: Dict[str, Dict[str, Any]], qs_names: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    # 1) try multiple normalized variants exact hit
    for k in _normalize_aff_variants(name):
        rec = qs_map.get(k)
        if rec:
            return rec
    # 1b) try acronym exact hit
    ak = _build_acronym(name)
    if ak:
        rec2 = qs_map.get(ak)
        if rec2:
            return rec2
    # 2) fallback: fuzzy on normalized strings
    try:
        import difflib
        # consider multiple target variants including suffix after first comma (e.g., "UNSW, Sydney" → "unswsydney")
        targets = set(_normalize_aff_variants(name))
        after = ",".join([p.strip() for p in (name or "").split(",")[1:]])
        if after:
            tnorm = _norm_string(after)
            if tnorm:
                targets.add(tnorm)
        if ak:
            targets.add(ak)
        if not targets:
            return None
        best = None; best_score = 0.0
        for item in qs_names:
            norms = item.get("norms", []) or []
            for t in targets:
                for k in norms:
                    score = difflib.SequenceMatcher(None, t, k).ratio()
                    if score > best_score:
                        best_score = score; best = item.get("rec")
        # accept only sufficiently close match
        if best and best_score >= 0.84:
            return best
    except Exception:
        return None
    return None


async def _enrich_affiliation_from_qs(cur, aff_id: int, display_name: str, qs_map: Dict[str, Dict[str, Any]], qs_names: List[Dict[str, Any]], sys_ids: Dict[int, int]) -> None:
    rec = _find_qs_record_for_aff(display_name, qs_map, qs_names)
    if not rec:
        return
    country = (rec.get("country") or "").strip()
    if country:
        # only fill if NULL or empty
        await cur.execute(
            "UPDATE affiliations SET country = COALESCE(NULLIF(country, ''), %s) WHERE id = %s",
            (country, aff_id),
        )
    if rec.get("r2025") and sys_ids.get(2025):
        await cur.execute(
            """
            INSERT INTO affiliation_rankings (aff_id, rank_system_id, rank_value, rank_year)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (aff_id, rank_system_id, rank_year) DO NOTHING
            """,
            (aff_id, sys_ids[2025], str(rec["r2025"]).strip(), 2025),
        )
    if rec.get("r2024") and sys_ids.get(2024):
        await cur.execute(
            """
            INSERT INTO affiliation_rankings (aff_id, rank_system_id, rank_value, rank_year)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (aff_id, rank_system_id, rank_year) DO NOTHING
            """,
            (aff_id, sys_ids[2024], str(rec["r2024"]).strip(), 2024),
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
    if checkpointer:
        return builder.compile(checkpointer=checkpointer)
    return data_processing_graph
