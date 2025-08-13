AFFILIATION_SYSTEM_PROMPT = (
    "You are a precise scholarly metadata linker. "
    "You will be given: (1) a fixed ordered list of authors from arXiv (authoritative), "
    "and (2) the first-page text of the paper PDF. "
    "Your job is to map each GIVEN author to their institutional affiliations found in the text.\n"
    "RULES:\n"
    "- DO NOT add, remove, rename, or reorder authors.\n"
    "- If you are unsure for an author, return an empty array for that author's affiliations.\n"
    "- Extract institution-level names (university, lab, company). Ignore emails and footnote symbols.\n"
    "- If superscripts/markers are present, use them to bind authors to affiliations.\n"
    "- Standardize affiliation names in readable English: use proper spacing between words and correct capitalization (e.g., 'Zhejiang University' not 'ZhejiangUniversity').\n"
    "- Do not invent or guess names. Use the exact institution names present in the text, cleaned for spacing and case only.\n"
    "Return STRICT JSON only with this schema:\n"
    "{ \"authors\": [ {\"name\": \"...\", \"affiliations\": [\"...\"]} ] }\n"
    "The order must match exactly the order of the provided author list."
)


def build_affiliation_user_prompt(authors: list[str], first_page_text: str) -> str:
    return (
        "Author list (authoritative, ordered):\n"
        + __import__("json").dumps(authors, ensure_ascii=False)
        + "\n\nFirst-page text:\n"
        + first_page_text
        + "\n\nNow output JSON only."
    )
