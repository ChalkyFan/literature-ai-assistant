"""arXiv API fetcher + keyword filtering"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict

import arxiv
from . import config

logger = logging.getLogger(__name__)


def _load_keywords() -> List[str]:
    return config.KEYWORDS


def fetch_today_papers() -> List[Dict]:
    """Fetch today papers from arXiv and filter by keywords"""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")

    all_results = []
    for category in config.ARXIV_CATEGORIES:
        logger.info(f"Fetching {category} from arXiv...")
        search = arxiv.Search(
            query=f"cat:{category}",
            max_results=config.ARXIV_BATCH_SIZE,
            sort_by=arxiv.SortCriterion.SubmittedDate,
        )
        client = arxiv.Client()
        papers = []
        for result in client.results(search):
            pub_date = result.published.strftime("%Y%m%d")
            if pub_date in (today, yesterday):
                papers.append(_parse_result(result))
            elif pub_date < yesterday:
                break
        logger.info(f"  {category}: got {len(papers)} new papers")
        all_results.extend(papers)

    matched = _keyword_filter(all_results, _load_keywords())
    matched.sort(key=lambda x: x["published"], reverse=True)

    if len(matched) > config.MAX_RESULTS_PER_DAY:
        logger.info(f"Filtered to {len(matched)} papers, capping at {config.MAX_RESULTS_PER_DAY}")
        matched = matched[:config.MAX_RESULTS_PER_DAY]

    return matched


def _parse_result(result) -> Dict:
    # Extract first author affiliation if available
    affiliations_str = ""
    if result.authors and hasattr(result.authors[0], "affiliation") and result.authors[0].affiliation:
        affiliations_str = "; ".join(result.authors[0].affiliation)
    return {
        "arxiv_id": result.entry_id.split("/")[-1].split("v")[0],
        "title": result.title.replace("\n", " ").strip(),
        "authors": [a.name for a in result.authors],
        "affiliations": affiliations_str,
        "abstract": result.summary.replace("\n", " ").strip(),
        "categories": result.categories if isinstance(result.categories, list) else result.categories.split(),
        "published": result.published,
        "pdf_url": result.pdf_url,
        "abstract_url": result.entry_id,
    }


def _keyword_filter(papers: List[Dict], keywords: List[str]) -> List[Dict]:
    matched = []
    seen_ids = set()
    for paper in papers:
        if paper["arxiv_id"] in seen_ids:
            continue
        seen_ids.add(paper["arxiv_id"])
        text = (paper["title"] + " " + paper["abstract"]).lower()
        hit_keywords = []
        for kw in keywords:
            if re.search(re.escape(kw.lower()), text):
                hit_keywords.append(kw)
        if hit_keywords:
            paper["matched_keywords"] = hit_keywords
            matched.append(paper)
    return matched


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    papers = fetch_today_papers()
    print(f"\nFound {len(papers)} related papers:\n")
    for p in papers:
        print(f"  [{p['arxiv_id']}] {p['title']}")
        print(f"    Keywords: {', '.join(p['matched_keywords'][:5])}\n")
