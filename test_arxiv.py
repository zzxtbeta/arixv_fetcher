import requests
from datetime import datetime, timezone

# Test ArXiv API directly
ARXIV_QUERY_API = "https://export.arxiv.org/api/query"
HTTP_HEADERS = {"User-Agent": "arxiv-scraper/0.1 (+https://example.com)"}

def build_search_query(categories, start_dt, end_dt):
    """Build arXiv API search query with date range and categories."""
    start_str = start_dt.strftime("%Y%m%d%H%M")
    end_str = end_dt.strftime("%Y%m%d%H%M")
    date_window = f"(submittedDate:[{start_str} TO {end_str}] OR lastUpdatedDate:[{start_str} TO {end_str}])"
    cat_q = " OR ".join(f"cat:{c}" for c in categories) if categories else ""
    return f"{date_window} AND ({cat_q})" if cat_q else date_window

# Test with a known date range that should have papers
start_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
end_dt = datetime(2024, 1, 2, tzinfo=timezone.utc)
categories = ["cs.AI"]

search_query = build_search_query(categories, start_dt, end_dt)
print(f"Search query: {search_query}")

params = {
    "search_query": search_query,
    "start": 0,
    "max_results": 5,
    "sortBy": "submittedDate",
    "sortOrder": "descending",
}

print(f"Request params: {params}")
print(f"Request URL: {ARXIV_QUERY_API}")

try:
    resp = requests.get(ARXIV_QUERY_API, params=params, headers=HTTP_HEADERS, timeout=30)
    print(f"Response status: {resp.status_code}")
    print(f"Response headers: {dict(resp.headers)}")
    print(f"Response content length: {len(resp.text)}")
    print(f"Response content (first 1000 chars): {resp.text[:1000]}")
    
    if resp.status_code == 200:
        # Check if we got any entries
        if "<entry>" in resp.text:
            print("Found entries in response!")
            entry_count = resp.text.count("<entry>")
            print(f"Number of entries: {entry_count}")
        else:
            print("No entries found in response")
    else:
        print(f"Error response: {resp.text}")
        
except Exception as e:
    print(f"Error: {e}")