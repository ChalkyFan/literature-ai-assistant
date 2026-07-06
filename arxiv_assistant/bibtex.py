"""BibTeX generation for literature papers"""

import re
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Characters that need escaping in BibTeX
SPECIAL_CHARS = {
    "\\": "\\textbackslash{}",
    "{": "\\{",
    "}": "\\}",
    "$": "\\$",
    "&": "\\&",
    "#": "\\#",
    "^": "\\textasciicircum{}",
    "_": "\\_",
    "%": "\\%",
    "~": "\\textasciitilde{}",
}


def escape_text(text: str) -> str:
    """Escape special BibTeX characters in text."""
    result = ""
    for ch in text:
        result += SPECIAL_CHARS.get(ch, ch)
    return result


def _format_authors(authors_str: Optional[str]) -> str:
    """Convert comma-separated 'First Last' names to BibTeX format: 'Last, First and Last, First'.

    Handles:
      - "Christopher A. Leong, Bitan Roy" -> "Leong, Christopher A. and Roy, Bitan"
      - "Bitan Roy" -> "Roy, Bitan"
    """
    if not authors_str or not authors_str.strip():
        return ""

    authors = [a.strip() for a in authors_str.split(",") if a.strip()]
    formatted = []
    for author in authors:
        parts = author.strip().split()
        if len(parts) >= 2:
            last = parts[-1]
            first = " ".join(parts[:-1])
            formatted.append(f"{last}, {first}")
        else:
            formatted.append(author.strip())

    return " and ".join(formatted)


def _make_citation_key(arxiv_id: str) -> str:
    """Create a clean BibTeX citation key from arxiv_id.
    
    Examples:
      "2606.27370"   -> "arXiv2606_27370"
      "2101.12345"   -> "arXiv2101_12345"
    """
    clean = arxiv_id.replace("/", "_").replace(".", "_")
    return f"arXiv{clean}"


def _get_year(published_date: Optional[str]) -> str:
    """Extract year from published_date string."""
    if not published_date:
        return ""
    match = re.search(r"(\d{4})", published_date)
    return match.group(1) if match else ""


def generate_bibtex(paper: Dict) -> str:
    """Generate a BibTeX entry for a single paper.
    
    Args:
        paper: dict with keys: arxiv_id, title, authors, abstract, categories, published_date
    
    Returns:
        BibTeX entry as a string
    """
    arxiv_id = paper.get("arxiv_id", "")
    citation_key = _make_citation_key(arxiv_id)
    title = escape_text(paper.get("title", "").strip())
    authors = _format_authors(paper.get("authors"))
    abstract = escape_text(paper.get("abstract", "").strip())
    year = _get_year(paper.get("published_date"))
    categories = paper.get("categories", "").strip()
    
    # Get first category as primary class
    primary_class = categories.split()[0] if categories else ""

    lines = [f"@article{{{citation_key},"]
    
    if authors:
        lines.append(f"  author = {{{authors}}},")
    if title:
        lines.append(f"  title = {{{title}}},")
    if year:
        lines.append(f"  year = {{{year}}},")
    
    lines.append(f'  eprint = "{arxiv_id}",')
    lines.append(f'  archiveprefix = "arXiv",')
    
    if primary_class:
        lines.append(f'  primaryclass = "{primary_class}",')
    
    if abstract:
        # Truncate abstract to first 300 chars for readability
        short_abstract = abstract[:300]
        lines.append(f"  abstract = {{{short_abstract}}},")
    
    if arxiv_id:
        lines.append(f'  url = "https://arxiv.org/abs/{arxiv_id}",')
    
    lines.append("}")
    lines.append("")
    
    return "\n".join(lines)


def generate_batch_bibtex(papers: List[Dict]) -> str:
    """Generate BibTeX entries for multiple papers.
    
    Args:
        papers: list of paper dicts
    
    Returns:
        Combined BibTeX entries as a string
    """
    entries = []
    for paper in papers:
        try:
            entries.append(generate_bibtex(paper))
        except Exception as e:
            arxiv_id = paper.get("arxiv_id", "unknown")
            logger.error(f"Failed to generate BibTeX for {arxiv_id}: {e}")
    return "\n".join(entries)


def generate_ris(paper: Dict) -> str:
    """Generate a RIS format entry (compatible with Zotero import).
    
    Args:
        paper: dict with paper data
    
    Returns:
        RIS entry as a string
    """
    arxiv_id = paper.get("arxiv_id", "")
    title = paper.get("title", "").strip()
    authors = paper.get("authors", "")
    year = _get_year(paper.get("published_date"))
    abstract = paper.get("abstract", "").strip()
    url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""

    lines = ["TY  - JOUR"]
    
    # Add authors (RIS uses AU for each author)
    if authors:
        for author in authors.split(","):
            author = author.strip()
            if author:
                lines.append(f"AU  - {author}")
    
    if title:
        lines.append(f"TI  - {title}")
    if year:
        lines.append(f"PY  - {year}")
    if abstract:
        lines.append(f"AB  - {abstract}")
    if url:
        lines.append(f"UR  - {url}")
    if arxiv_id:
        lines.append(f"ID  - {arxiv_id}")
        lines.append(f"L1  - http://arxiv.org/pdf/{arxiv_id}")
    
    lines.append("ER  - ")
    lines.append("")
    
    return "\n".join(lines)
