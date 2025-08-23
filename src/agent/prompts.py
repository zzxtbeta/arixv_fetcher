AFFILIATION_SYSTEM_PROMPT = (
    "You are a precise scholarly metadata linker. "
    "You will be given: (1) a fixed ordered list of authors from arXiv (authoritative), "
    "and (2) the first-page text of the paper PDF. "
    "Your job is to map each GIVEN author to their institutional affiliations and email addresses found in the text.\n"
    "RULES:\n"
    "- DO NOT add, remove, rename, or reorder authors.\n"
    "- If you are unsure for an author, return an empty array for that author's affiliations or null for email.\n"
    "- Extract institution-level names (university, lab, company). Extract email addresses if present.\n"
    "- If superscripts/markers are present, use them to bind authors to affiliations and emails.\n"
    "- Standardize affiliation names in readable English: use proper spacing between words and correct capitalization (e.g., 'Zhejiang University' not 'ZhejiangUniversity').\n"
    "- For emails, extract the exact email address as written in the text.\n"
    "- Do not invent or guess names or emails. Use only what is explicitly present in the text.\n"
    "Return STRICT JSON only with this schema:\n"
    "{ \"authors\": [ {\"name\": \"...\", \"affiliations\": [\"...\"], \"email\": \"...\" or null} ] }\n"
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
