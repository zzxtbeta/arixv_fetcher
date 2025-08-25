"""
Utility functions for the ArXiv data processing pipeline.

Contains helper functions for:
- HTTP session management
- ArXiv API parsing and querying
- PDF text extraction
- ORCID data processing
- QS rankings enrichment
- Tavily web search
- Database schema creation
"""

import os
import logging
import asyncio
import re
import csv
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
import requests

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

try:
    from tavily import TavilyClient
    TAVILY_AVAILABLE = True
except ImportError:
    TavilyClient = None
    TAVILY_AVAILABLE = False

logger = logging.getLogger(__name__)

# Constants
ARXIV_QUERY_API = "https://export.arxiv.org/api/query"
HTTP_HEADERS = {"User-Agent": "arxiv-scraper/0.1 (+https://example.com)"}

# Global variables for session management and caching
_PDF_SESSION = None
_ORCID_SESSION = None
_ORCID_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}
_ORCID_CANDIDATES_CACHE: Dict[str, List[Dict[str, Any]]] = {}
_QS_CACHE_MAP: Optional[Dict[str, Dict[str, Any]]] = None
_QS_CACHE_NAMES: Optional[List[Dict[str, Any]]] = None

# Regex patterns
_DEPT_PREFIX = re.compile(r"^(department|dept\.?|school|faculty|college|laboratory|laboratories|lab|centre|center|institute|institutes|academy|division|unit)\s+of\s+", re.IGNORECASE)

# ---------------------- Logging utilities ----------------------

def log_json_sample(tag: str, obj: Any, limit: int = 2000) -> None:
    """Log JSON sample for debugging (currently disabled to reduce noise)."""
    pass

def log_orcid_candidate(info: Dict[str, Any], matched: bool) -> None:
    """Log ORCID candidate matching results."""
    if matched:
        oid = info.get("orcid_id")
        disp = info.get("display_name")
        logger.info(f"ORCID candidate matched: {oid} ({disp})")

# ---------------------- HTTP Session management ----------------------

def get_pdf_session():
    """Get or create reusable HTTP session for arXiv PDF downloads."""
    global _PDF_SESSION
    if _PDF_SESSION is None:
        try:
            s = requests.Session()
            s.headers.update(HTTP_HEADERS)
            _PDF_SESSION = s
        except Exception:
            _PDF_SESSION = requests
    return _PDF_SESSION

def get_orcid_session():
    """Get or create reusable HTTP session for ORCID API calls."""
    global _ORCID_SESSION
    if _ORCID_SESSION is None:
        try:
            s = requests.Session()
            s.headers.update(get_orcid_headers())
            _ORCID_SESSION = s
        except Exception:
            _ORCID_SESSION = requests
    return _ORCID_SESSION

# ---------------------- ArXiv API utilities ----------------------

def parse_arxiv_atom(xml_text: str) -> List[Dict[str, Any]]:
    """Parse arXiv Atom XML response into structured paper data."""
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

def build_search_query(categories: List[str], start_dt: datetime, end_dt: datetime) -> str:
    """Build arXiv API search query with date range and categories."""
    start_str = start_dt.strftime("%Y%m%d%H%M")
    end_str = end_dt.strftime("%Y%m%d%H%M")
    date_window = f"(submittedDate:[{start_str} TO {end_str}] OR lastUpdatedDate:[{start_str} TO {end_str}])"
    cat_q = " OR ".join(f"cat:{c}" for c in categories) if categories else ""
    return f"{date_window} AND ({cat_q})" if cat_q else date_window

def search_papers_by_range(categories: List[str], start_dt: datetime, end_dt: datetime, max_results: int = 200) -> List[Dict[str, Any]]:
    """Search arXiv papers by date range with pagination."""
    search_query = build_search_query(categories, start_dt, end_dt)
    logger.info(f"arXiv search query: {search_query}")

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
        try:
            logger.debug(f"arXiv API request: {ARXIV_QUERY_API} with params {params}")
            resp = requests.get(ARXIV_QUERY_API, params=params, headers=HTTP_HEADERS, timeout=30)
            resp.raise_for_status()
            papers = parse_arxiv_atom(resp.text)
            logger.info(f"arXiv API returned {len(papers)} papers for page starting at {start}")
            if not papers:
                break
            results.extend(papers)
            if len(papers) < params["max_results"]:
                break
            start += params["max_results"]
        except requests.exceptions.RequestException as e:
            logger.error(f"arXiv API request failed: {e}")
            logger.error(f"Request URL: {ARXIV_QUERY_API}")
            logger.error(f"Request params: {params}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response status: {e.response.status_code}")
                logger.error(f"Response text: {e.response.text[:500]}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in arXiv search: {e}")
            raise

    return results[:max_results]

def search_papers_by_window(categories: List[str], days: int, max_results: int = 200) -> List[Dict[str, Any]]:
    """Search arXiv papers by time window (last N days)."""
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=max(1, days))
    return search_papers_by_range(categories, start_dt, end_dt, max_results)

def search_papers_by_ids(id_list: List[str]) -> List[Dict[str, Any]]:
    """Fetch papers by explicit arXiv ID list using id_list param (batched)."""
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
        results.extend(parse_arxiv_atom(resp.text))
    return results

def iso_to_date(iso_str: Optional[str]) -> Optional[str]:
    """Convert ISO datetime string to date string (YYYY-MM-DD)."""
    if not iso_str:
        return None
    try:
        return iso_str[:10]
    except Exception:
        return None

# ---------------------- LLM and PDF utilities ----------------------

def create_llm():
    """Create ChatOpenAI instance with configured model and API settings."""
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=os.getenv("AFFILIATION_MODEL", os.getenv("QWEN_MODEL", "qwen-max")),
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        temperature=0.0,
    )

def download_first_page_text(pdf_url: str, timeout: int = 60) -> str:
    """Download and extract text from first page of PDF."""
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

        sess = get_pdf_session()
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

def download_first_page_text_with_retries(pdf_url: str) -> str:
    """Download first page text with retries and backoff."""
    for i in range(3):
        txt = download_first_page_text(pdf_url)
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

# ---------------------- ORCID utilities ----------------------

def get_orcid_headers() -> Dict[str, str]:
    """Get headers for ORCID API requests."""
    client_id = os.getenv("ORCID_CLIENT_ID")
    client_secret = os.getenv("ORCID_CLIENT_SECRET")
    headers = {"Accept": "application/json", "User-Agent": "arxiv-scraper/0.1"}
    # Public API works without auth; if member creds exist we could fetch token (omitted for brevity)
    # Keep headers minimal to avoid coupling
    return headers

def get_orcid_base_urls() -> Dict[str, str]:
    """Get ORCID API base URLs."""
    # Use public API to avoid OAuth token handling; sufficient for read-public
    base = "https://pub.orcid.org/v3.0"
    return {"base": base, "search": f"{base}/search"}

def normalize_name_for_strict(s: str) -> str:
    """Normalize name for strict equality checks (lowercase and collapse spaces)."""
    return " ".join((s or "").lower().split())

def name_tokens(s: str) -> List[str]:
    """Split name into alphanumeric tokens."""
    txt = (s or "").lower()
    # split by non-alphanumerics and remove empties
    return [t for t in re.split(r"[^a-z0-9]+", txt) if t]

def parse_orcid_date(d: str) -> Optional[str]:
    """Parse ORCID date object to ISO date string."""
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

def best_aff_match_for_institution(aff_name: str, scholar: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Find best matching affiliation (employment first, then education)."""
    from difflib import SequenceMatcher
    target_norms = normalize_aff_variants(aff_name)
    if not target_norms:
        return None
    def score_one(org: str, dept: str) -> float:
        best = 0.0
        for k in normalize_aff_variants(org):
            for t in target_norms:
                best = max(best, SequenceMatcher(None, t, k).ratio())
        # dept helps if present
        if dept:
            for k in normalize_aff_variants(dept):
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

def orcid_search_and_pick(name: str, institution: str, max_results: int = 10) -> Optional[Dict[str, Any]]:
    """Search ORCID and pick best matching profile."""
    urls = get_orcid_base_urls()
    headers = get_orcid_headers()
    # cache key: strict name + normalized institution
    key = f"{normalize_name_for_strict(name)}|{norm_string(institution)}"
    if key in _ORCID_CACHE:
        return _ORCID_CACHE[key]
    # Build query: name across given/family/other, with optional affiliation filter
    name = (name or "").strip()
    parts = name.split()
    if len(parts) >= 2:
        given = " ".join(parts[:-1])
        family = parts[-1]
        name_query = f'(given-names:"{given}" AND family-name:"{family}") OR (given-names:"{name}" OR family-name:"{name}" OR other-names:"{name}")'
    else:
        name_query = f'(given-names:"{name}" OR family-name:"{name}" OR other-names:"{name}")'
    if institution:
        query = f'({name_query}) AND affiliation-org-name:"{institution}"'
    else:
        query = name_query
    try:
        sess = get_orcid_session()
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
                    out["given_names"] = gn or ""
                    out["family_name"] = fn or ""
                    out["display_name"] = f"{gn} {fn}".strip()
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
                    item["start_date"] = orcid_format_date(item["start_date"])
                    item["end_date"] = orcid_format_date(item["end_date"])
                return out
            def orcid_format_date(obj: Any) -> str:
                if not obj:
                    return ""
                try:
                    y = (obj.get("year") or {}).get("value")
                    m = (obj.get("month") or {}).get("value")
                    d = (obj.get("day") or {}).get("value")
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
        name_norm = normalize_name_for_strict(name)
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
            disp = normalize_name_for_strict(info.get("display_name", ""))
            gn = normalize_name_for_strict(info.get("given_names", ""))
            fn = normalize_name_for_strict(info.get("family_name", ""))
            strict_ok = name_norm == disp or name_norm == f"{gn} {fn}".strip()
            if not strict_ok:
                continue
            # Institution match
            if institution:
                best = best_aff_match_for_institution(institution, info)
                if not best:
                    continue
            cand.append(info)
        picked = cand[0] if cand else None
        _ORCID_CACHE[key] = picked
        return picked
    except Exception:
        return None

def orcid_candidates_by_name(name: str, max_candidates: int = 5) -> List[Dict[str, Any]]:
    """Return up to N ORCID candidate profiles that strictly match the author's name."""
    key = f"cands|{normalize_name_for_strict(name)}|{max_candidates}"
    if key in _ORCID_CANDIDATES_CACHE:
        return _ORCID_CANDIDATES_CACHE[key]
    urls = get_orcid_base_urls()
    headers = get_orcid_headers()
    sess = get_orcid_session()
    # name-only search to gather a small pool
    name = (name or "").strip()
    parts = name.split()
    if len(parts) >= 2:
        given = " ".join(parts[:-1])
        family = parts[-1]
        name_query = f'(given-names:"{given}" AND family-name:"{family}") OR (given-names:"{name}" OR family-name:"{name}" OR other-names:"{name}")'
    else:
        name_query = f'(given-names:"{name}" OR family-name:"{name}" OR other-names:"{name}")'
    try:
        # fetch a wider pool to avoid missing exact match due to ranking
        r = sess.get(urls["search"], params={"q": name_query, "rows": 100}, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        results = data.get("result") or []
        # log raw classic search results (truncated)
        log_json_sample("search", results[:10])
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
                    outp["given_names"] = gn or ""
                    outp["family_name"] = fn or ""
                    outp["display_name"] = f"{gn} {fn}".strip()
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
                            "start_date": parse_orcid_date((sd or {}).get("start-date")),
                            "end_date": parse_orcid_date((sd or {}).get("end-date")),
                        })
                # format dates
                for it in items:
                    it["start_date"] = parse_orcid_date(it["start_date"]) if isinstance(it.get("start_date"), str) else parse_orcid_date("")
                    it["end_date"] = parse_orcid_date(it["end_date"]) if isinstance(it.get("end_date"), str) else parse_orcid_date("")
                return items
            info = {"orcid_id": orcid_id}
            info.update(parse_person(person))
            info["employments"] = parse_affs(emp, "employment-summary")
            info["educations"] = parse_affs(edu, "education-summary")
            # strict name check (display_name or given+family or any other_names)
            target = name_tokens(name)
            disp_t = name_tokens(info.get("display_name", ""))
            gn_t = name_tokens(info.get("given_names", ""))
            fn_t = name_tokens(info.get("family_name", ""))
            full_gf = gn_t + fn_t if (gn_t or fn_t) else []
            other_list = (info.get("other_names") or [])
            other_ts = [name_tokens(x) for x in other_list]
            def eq_tokens(a, b):
                return a == b or a == list(reversed(b))
            matched = (
                (disp_t and eq_tokens(disp_t, target))
                or (full_gf and eq_tokens(full_gf, target))
                or any(eq_tokens(t, target) for t in other_ts if t)
            )
            log_orcid_candidate(info, matched)
            if matched:
                out.append(info)
        # Fallback: use expanded-search if no strict candidate found from classic search
        if len(out) < max_candidates:
            # derive given and family from tokens (last token as family)
            toks = name_tokens(name)
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
                        log_json_sample("expanded-search", eitems[:10])
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
                                    outp["given_names"] = gn or ""
                                    outp["family_name"] = fn or ""
                                    outp["display_name"] = f"{gn} {fn}".strip()
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
                                            "start_date": parse_orcid_date((sd or {}).get("start-date")),
                                            "end_date": parse_orcid_date((sd or {}).get("end-date")),
                                        })
                                for it in items:
                                    it["start_date"] = parse_orcid_date(it["start_date"]) if isinstance(it.get("start_date"), str) else parse_orcid_date("")
                                    it["end_date"] = parse_orcid_date(it["end_date"]) if isinstance(it.get("end_date"), str) else parse_orcid_date("")
                                return items
                            info.update(parse_person(person))
                            info["employments"] = parse_affs(emp, "employment-summary")
                            info["educations"] = parse_affs(edu, "education-summary")
                            # strict token check again
                            target = name_tokens(name)
                            disp_t = name_tokens(info.get("display_name", ""))
                            gn_t = name_tokens(info.get("given_names", ""))
                            fn_t = name_tokens(info.get("family_name", ""))
                            full_gf = gn_t + fn_t if (gn_t or fn_t) else []
                            other_list = (info.get("other_names") or [])
                            other_ts = [name_tokens(x) for x in other_list]
                            def eq_tokens(a, b):
                                return a == b or a == list(reversed(b))
                            matched2 = (
                                (disp_t and eq_tokens(disp_t, target))
                                or (full_gf and eq_tokens(full_gf, target))
                                or any(eq_tokens(t, target) for t in other_ts if t)
                            )
                            log_orcid_candidate(info, matched2)
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

# ---------------------- QS rankings utilities ----------------------

def norm_string(s: str) -> str:
    """Normalize string to alphanumeric lowercase."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())

def strip_parentheses(s: str) -> str:
    """Remove parenthetical content from string."""
    return re.sub(r"\([^\)]*\)", "", s or "").strip()

def first_segment_before_comma(s: str) -> str:
    """Get first segment before comma."""
    return (s or "").split(",", 1)[0].strip()

def last_segment_after_comma(s: str) -> str:
    """Get last segment after comma."""
    parts = [p.strip() for p in (s or "").split(",") if p and p.strip()]
    if not parts:
        return (s or "").strip()
    return parts[-1]

def strip_dept_prefix(s: str) -> str:
    """Remove department prefixes from string."""
    return _DEPT_PREFIX.sub("", s or "").strip()

def strip_articles(s: str) -> str:
    """Remove leading English articles."""
    return re.sub(r"^(\s*(the|a|an)\s+)", "", (s or ""), flags=re.IGNORECASE).strip()

def build_acronym(s: str) -> str:
    """Build acronym from words, skipping small connectors."""
    tokens = re.split(r"[^A-Za-z]+", s or "")
    skip = {"of", "and", "for", "at", "in", "on"}
    letters = [t[0] for t in tokens if t and t.lower() not in skip]
    return ("".join(letters)).lower()

def normalize_aff_variants(name: str) -> List[str]:
    """Generate normalized variants of an affiliation name for fuzzy matching."""
    if not name or not name.strip():
        return []
    
    # Generate text candidates through various transformations
    tail1 = last_segment_after_comma(name)
    tail2 = ", ".join([p.strip() for p in name.split(",")[-2:]]) if "," in name else name
    
    candidates = [
        name,
        strip_parentheses(name),
        first_segment_before_comma(name),
        strip_dept_prefix(name),
        strip_dept_prefix(first_segment_before_comma(name)),
        strip_dept_prefix(strip_parentheses(name)),
        tail1,
        strip_dept_prefix(tail1),
        tail2,
    ]
    
    # Include article-stripped forms (e.g., "The University" -> "University")
    candidates += [strip_articles(c) for c in candidates]
    
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
        if c in (tail1, strip_dept_prefix(tail1), tail2):
            if not org_keywords.search(c):
                continue
                
        normalized = norm_string(c)
        if normalized and normalized not in norms:
            norms.append(normalized)
    
    return norms

def project_root() -> str:
    """Get project root directory path."""
    # src/agent/utils.py → up two levels to project root
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def qs_csv_path() -> str:
    """Get path to QS rankings CSV file."""
    # docs/qs-world-rankings-2025.csv located at project root /docs
    return os.path.join(project_root(), "docs", "qs-world-rankings-2025.csv")

def load_qs_rankings() -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """Load QS rankings data from CSV file."""
    path = qs_csv_path()
    mapping: Dict[str, Dict[str, Any]] = {}
    names: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # helper to resolve headers even with NBSP/spacing/case differences
            def norm_header(s: str) -> str:
                txt = (s or "")
                # remove BOM and zero-width characters
                txt = txt.replace("\ufeff", "").replace("\u200b", "")
                # normalize spaces and case
                txt = txt.replace("\xa0", " ")
                txt = re.sub(r"\s+", " ", txt).strip().lower()
                return txt
            header_map = { norm_header(h): h for h in (reader.fieldnames or []) }
            def get_field(row: dict, keys: List[str]) -> str:
                for k in keys:
                    hk = header_map.get(norm_header(k))
                    if hk in row:
                        return (row.get(hk) or "").strip()
                # last try: iterate row keys
                for rk in row.keys():
                    if norm_header(rk) in [norm_header(k) for k in keys]:
                        return (row.get(rk) or "").strip()
                return ""
            for row in reader:
                inst = get_field(row, ["Institution Name", "institution", "name"]) 
                if not inst:
                    continue
                # base record
                country = get_field(row, ["Location Full", "Location", "Country"]) 
                r2025 = get_field(row, ["2025 Rank", "Rank 2025", "2025"]) 
                r2024 = get_field(row, ["2024 Rank", "Rank 2024", "2024"]) 
                rec = {"name": inst, "country": country, "r2025": r2025, "r2024": r2024}
                # build multiple normalized keys for better coverage
                keys = normalize_aff_variants(inst)
                # add parenthetical aliases as additional variants (e.g., "UNSW Sydney")
                try:
                    pars = re.findall(r"\(([^)]*)\)", inst)
                    for txt in pars:
                        for k in normalize_aff_variants(txt):
                            if k not in keys:
                                keys.append(k)
                except Exception:
                    pass
                # add acronym variant (e.g., "UNSW")
                acr = build_acronym(inst)
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

def get_qs_map() -> Dict[str, Dict[str, Any]]:
    """Get QS rankings mapping (cached)."""
    global _QS_CACHE_MAP, _QS_CACHE_NAMES
    if _QS_CACHE_MAP is None:
        _QS_CACHE_MAP, _QS_CACHE_NAMES = load_qs_rankings()
    return _QS_CACHE_MAP or {}

def get_qs_names() -> List[Dict[str, Any]]:
    """Get QS rankings names list (cached)."""
    global _QS_CACHE_MAP, _QS_CACHE_NAMES
    if _QS_CACHE_NAMES is None:
        _QS_CACHE_MAP, _QS_CACHE_NAMES = load_qs_rankings()
    return _QS_CACHE_NAMES or []

async def ensure_qs_ranking_systems(cur) -> Dict[int, int]:
    """Ensure ranking systems for QS 2025 and QS 2024 exist; return {year: id}."""
    systems = {2025: "QS 2025", 2024: "QS 2024"}
    out: Dict[int, int] = {}
    for year, name in systems.items():
        await cur.execute(
            "INSERT INTO ranking_systems (system_name, update_frequency) VALUES (%s, %s) ON CONFLICT (system_name) DO NOTHING RETURNING id",
            (name, 1),  # 1 year frequency instead of "annual" string
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

def find_qs_record_for_aff(name: str, qs_map: Dict[str, Dict[str, Any]], qs_names: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Find QS ranking record for affiliation name."""
    # 1) try multiple normalized variants exact hit
    for k in normalize_aff_variants(name):
        rec = qs_map.get(k)
        if rec:
            return rec
    # 1b) try acronym exact hit
    ak = build_acronym(name)
    if ak:
        rec2 = qs_map.get(ak)
        if rec2:
            return rec2
    # 2) fallback: fuzzy on normalized strings
    try:
        import difflib
        # consider multiple target variants including suffix after first comma (e.g., "UNSW, Sydney" → "unswsydney")
        targets = set(normalize_aff_variants(name))
        after = ",".join([p.strip() for p in (name or "").split(",")[1:]])
        if after:
            tnorm = norm_string(after)
            if tnorm:
                targets.add(tnorm)
        if ak:
            targets.add(ak)
        if not targets:
            return None
        best = None
        best_score = 0.0
        for item in qs_names:
            norms = item.get("norms", []) or []
            for t in targets:
                for k in norms:
                    score = difflib.SequenceMatcher(None, t, k).ratio()
                    if score > best_score:
                        best_score = score
                        best = item.get("rec")
        # accept only sufficiently close match
        if best and best_score >= 0.84:
            return best
    except Exception:
        return None
    return None

async def enrich_affiliation_from_qs(cur, aff_id: int, display_name: str, qs_map: Dict[str, Dict[str, Any]], qs_names: List[Dict[str, Any]], sys_ids: Dict[int, int]) -> None:
    """Enrich affiliation with QS ranking data."""
    rec = find_qs_record_for_aff(display_name, qs_map, qs_names)
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

# ---------------------- Database schema utilities ----------------------

async def create_schema_if_not_exists(cur) -> None:
    """Create all tables and constraints per db_schema.md (simplified types with identity PK)."""
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS papers (
            id BIGSERIAL PRIMARY KEY,
            paper_title TEXT,
            published DATE,
            updated DATE,
            abstract TEXT,
            doi TEXT,
            pdf_source TEXT,
            arxiv_entry TEXT UNIQUE,
            UNIQUE (paper_title, published)
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS authors (
            id BIGSERIAL PRIMARY KEY,
            author_name_en TEXT NOT NULL,
            author_name_cn TEXT,
            email TEXT UNIQUE,
            orcid TEXT UNIQUE,
            citations INT,
            H_index INT,
            I10_index INT
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS affiliations (
            id BIGSERIAL PRIMARY KEY,
            aff_name TEXT UNIQUE,
            aff_type TEXT,
            country TEXT,
            state TEXT,
            city TEXT
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ranking_systems (
            id BIGSERIAL PRIMARY KEY,
            system_name TEXT UNIQUE,
            update_frequency INT
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS keywords (
            id BIGSERIAL PRIMARY KEY,
            keyword TEXT UNIQUE
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id BIGSERIAL PRIMARY KEY,
            category TEXT UNIQUE
        )
        """
    )
    await cur.execute(
        """
        CREATE TABLE IF NOT EXISTS people_verified (
            id BIGSERIAL PRIMARY KEY,
            name_en TEXT,
            name_cn TEXT
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
            department TEXT,
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
            rank_value INT,
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

# ---------------------- Tavily web search utilities ----------------------

# Global variables for API key rotation
_TAVILY_API_KEYS = [
    "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",
    "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", 
    "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"
]
_CURRENT_TAVILY_KEY_INDEX = 0
_TAVILY_CLIENT_CACHE = {}

# API Rate Limiting Variables
_LAST_TAVILY_REQUEST_TIME = 0.0
_TAVILY_REQUEST_COUNT = 0
_TAVILY_REQUEST_WINDOW_START = 0.0
_TAVILY_SEMAPHORE = None

def _get_tavily_semaphore():
    """Get or create Tavily API semaphore for concurrency control."""
    global _TAVILY_SEMAPHORE
    if _TAVILY_SEMAPHORE is None:
        max_concurrency = int(os.getenv("TAVILY_MAX_CONCURRENCY", "3"))
        _TAVILY_SEMAPHORE = asyncio.Semaphore(max_concurrency)
    return _TAVILY_SEMAPHORE

async def _rate_limit_tavily_request():
    """Apply rate limiting for Tavily API requests."""
    global _LAST_TAVILY_REQUEST_TIME, _TAVILY_REQUEST_COUNT, _TAVILY_REQUEST_WINDOW_START
    
    current_time = time.time()
    
    # Configuration from environment
    request_delay = float(os.getenv("TAVILY_REQUEST_DELAY", "1.0"))
    requests_per_minute = int(os.getenv("TAVILY_REQUESTS_PER_MINUTE", "30"))
    
    # Check if we need to reset the request window (1 minute)
    if current_time - _TAVILY_REQUEST_WINDOW_START >= 60.0:
        _TAVILY_REQUEST_COUNT = 0
        _TAVILY_REQUEST_WINDOW_START = current_time
    
    # Check if we've exceeded requests per minute
    if _TAVILY_REQUEST_COUNT >= requests_per_minute:
        wait_time = 60.0 - (current_time - _TAVILY_REQUEST_WINDOW_START)
        if wait_time > 0:
            logger.info(f"Rate limit reached, waiting {wait_time:.1f} seconds")
            await asyncio.sleep(wait_time)
            # Reset window after waiting
            _TAVILY_REQUEST_COUNT = 0
            _TAVILY_REQUEST_WINDOW_START = time.time()
    
    # Apply minimum delay between requests
    time_since_last = current_time - _LAST_TAVILY_REQUEST_TIME
    if time_since_last < request_delay:
        wait_time = request_delay - time_since_last
        await asyncio.sleep(wait_time)
    
    # Update counters
    _LAST_TAVILY_REQUEST_TIME = time.time()
    _TAVILY_REQUEST_COUNT += 1

def get_next_tavily_api_key() -> Optional[str]:
    """Get the next available Tavily API key in rotation."""
    global _CURRENT_TAVILY_KEY_INDEX
    
    # First try environment variable if set
    env_key = os.getenv("TAVILY_API_KEY")
    if env_key and env_key not in _TAVILY_API_KEYS:
        return env_key
    
    # Use rotation keys
    if _CURRENT_TAVILY_KEY_INDEX < len(_TAVILY_API_KEYS):
        key = _TAVILY_API_KEYS[_CURRENT_TAVILY_KEY_INDEX]
        return key
    
    return None

def rotate_tavily_api_key() -> bool:
    """Rotate to the next Tavily API key. Returns True if rotation successful."""
    global _CURRENT_TAVILY_KEY_INDEX
    
    _CURRENT_TAVILY_KEY_INDEX += 1
    if _CURRENT_TAVILY_KEY_INDEX < len(_TAVILY_API_KEYS):
        logger.info(f"Rotated to Tavily API key #{_CURRENT_TAVILY_KEY_INDEX + 1}")
        return True
    else:
        logger.error("All Tavily API keys exhausted")
        return False

def is_quota_exceeded_error(error_msg: str) -> bool:
    """Check if the error indicates API quota exceeded."""
    quota_indicators = [
        "quota", "limit", "exceeded", "rate limit", 
        "usage limit", "monthly limit", "daily limit",
        "429", "too many requests"
    ]
    error_lower = str(error_msg).lower()
    return any(indicator in error_lower for indicator in quota_indicators)

def get_tavily_client() -> Optional[object]:
    """Get Tavily client instance with API key rotation support."""
    if not TAVILY_AVAILABLE:
        logger.warning("Tavily client not available. Please install: pip install tavily-python")
        return None
    
    api_key = get_next_tavily_api_key()
    if not api_key:
        logger.warning("No Tavily API keys available")
        return None
    
    # Use cached client if available
    if api_key in _TAVILY_CLIENT_CACHE:
        return _TAVILY_CLIENT_CACHE[api_key]
    
    try:
        client = TavilyClient(api_key)
        _TAVILY_CLIENT_CACHE[api_key] = client
        return client
    except Exception as e:
        logger.error(f"Failed to create Tavily client with key {api_key[:10]}...: {e}")
        return None

async def search_person_role_with_tavily(name: str, affiliation: str) -> Optional[Dict[str, Any]]:
    """Search for person's role information using Tavily web search with API key rotation and rate limiting.
    
    Args:
        name: Person's full name
        affiliation: Institution/organization name
        
    Returns:
        Dict with search results and extracted role information, or None if failed
    """
    if not name or not affiliation:
        logger.warning("Name and affiliation are required for Tavily search")
        return None
    
    query = f"What is {name}'s role position job title at {affiliation}?"
    logger.info(f"Tavily searching: {query}")
    
    # Configuration from environment
    max_retries = int(os.getenv("API_MAX_RETRIES", "3"))
    retry_delay = float(os.getenv("API_RETRY_DELAY", "2.0"))
    
    # Apply concurrency control
    semaphore = _get_tavily_semaphore()
    async with semaphore:
        # Try with current API key, rotate if quota exceeded
        for attempt in range(max_retries):
            # Apply rate limiting before each request
            await _rate_limit_tavily_request()
            
            client = get_tavily_client()
            if not client:
                logger.warning(f"No Tavily client available on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                continue
                
            try:
                # Make the API call in a thread to avoid blocking
                response = await asyncio.to_thread(
                    client.search,
                    query=query,
                    search_depth="advanced",
                    include_answer="advanced",
                    max_results=5,
                    include_domains=None,
                    exclude_domains=None
                )
                
                # Extract relevant information
                answer = response.get('answer', '')
                results = response.get('results', [])
                
                # Use LLM to extract role from search results
                extracted_role = await asyncio.to_thread(_extract_role_with_llm, name, affiliation, answer, results)
                
                return {
                    "query": query,
                    "answer": answer,
                    "results": results,
                    "extracted_role": extracted_role,
                    "search_successful": True
                }
            
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Tavily search error on attempt {attempt + 1}: {error_msg}")
                
                # Check if it's a quota exceeded error
                if is_quota_exceeded_error(error_msg):
                    logger.warning(f"API quota exceeded, attempting to rotate to next key")
                    if rotate_tavily_api_key():
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                        continue  # Try with next API key
                    else:
                        logger.error("All Tavily API keys exhausted")
                        break
                else:
                    # Non-quota error, add delay before retry
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                    continue
    
    # All attempts failed
    return {
        "query": query,
        "error": "All Tavily API attempts failed",
        "search_successful": False
    }

async def search_person_general_with_tavily(name: str, affiliation: str, search_prompt: str) -> Optional[Dict[str, Any]]:
    """General Tavily web search for person information with custom prompt, API key rotation, and rate limiting.
    
    Args:
        name: Person's full name
        affiliation: Institution/organization name
        search_prompt: Custom search prompt/question
        
    Returns:
        Dict with search results, or None if failed
    """
    if not name or not affiliation or not search_prompt:
        logger.warning("Name, affiliation, and search prompt are required")
        return None
    
    # Format the query with person and affiliation context
    query = f"{search_prompt} {name} {affiliation}"
    logger.info(f"Tavily searching: {query}")
    
    # Configuration from environment
    max_retries = int(os.getenv("API_MAX_RETRIES", "3"))
    retry_delay = float(os.getenv("API_RETRY_DELAY", "2.0"))
    
    # Apply concurrency control
    semaphore = _get_tavily_semaphore()
    async with semaphore:
        # Try with current API key, rotate if quota exceeded
        for attempt in range(max_retries):
            # Apply rate limiting before each request
            await _rate_limit_tavily_request()
            
            client = get_tavily_client()
            if not client:
                logger.warning(f"No Tavily client available on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                continue
                
            try:
                # Make the API call in a thread to avoid blocking
                response = await asyncio.to_thread(
                    client.search,
                    query=query,
                    search_depth="advanced",
                    include_answer="advanced",
                    max_results=8,
                    include_domains=None,
                    exclude_domains=None
                )
                
                return {
                    "query": query,
                    "answer": response.get('answer', ''),
                    "results": response.get('results', []),
                    "search_successful": True,
                    "person_name": name,
                    "affiliation": affiliation,
                    "search_prompt": search_prompt
                }
            
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Tavily search error on attempt {attempt + 1}: {error_msg}")
                
                # Check if it's a quota exceeded error
                if is_quota_exceeded_error(error_msg):
                    logger.warning(f"API quota exceeded, attempting to rotate to next key")
                    if rotate_tavily_api_key():
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                        continue  # Try with next API key
                    else:
                        logger.error("All Tavily API keys exhausted")
                        break
                else:
                    # Non-quota error, add delay before retry
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                    continue
    
    # All attempts failed
        return {
            "query": query,
            "error": str(e),
            "search_successful": False,
            "person_name": name,
            "affiliation": affiliation,
            "search_prompt": search_prompt
        }

def _extract_role_with_llm(name: str, affiliation: str, answer: str, results: List[Dict[str, Any]]) -> Optional[str]:
    """Extract role information using LLM from search results.
    
    Args:
        name: Person's name
        affiliation: Institution name
        answer: Tavily's answer summary
        results: List of search result dictionaries
        
    Returns:
        Extracted role string or None
    """
    try:
        # Import LLM function (assuming it's available)
        llm = create_llm()
        
        # Prepare context from search results
        context_parts = []
        if answer:
            context_parts.append(f"Summary: {answer}")
        
        for i, result in enumerate(results[:3]):  # Limit to top 3 results
            title = result.get('title', '')
            content = result.get('content', '')
            url = result.get('url', '')
            if content:
                context_parts.append(f"Result {i+1} ({url}): {title}\n{content[:500]}...")
        
        context = "\n\n".join(context_parts)
        
        system_prompt = (
            "You are a precise role extractor. Given a person's name, their affiliation, "
            "and web search results about them, extract their professional role/position. "
            "Return only the role title (e.g., 'Professor', 'Research Scientist', 'CEO', etc.). "
            "If unclear or not found, return 'Unknown'."
        )
        
        user_prompt = (
            f"Person: {name}\n"
            f"Affiliation: {affiliation}\n\n"
            f"Search Results:\n{context}\n\n"
            f"What is {name}'s role/position at {affiliation}? Please provide only the role title:"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # Use LLM to extract role
        response = llm.invoke(messages)
        role = response.content.strip() if hasattr(response, 'content') else str(response).strip()
        
        # Clean up the response
        if role and role.lower() not in ['unknown', 'unclear', 'not found', '']:
            logger.info(f"Extracted role for {name}: {role}")
            return role
        else:
            return None
            
    except Exception as e:
        logger.error(f"LLM role extraction error: {e}")
        return None
