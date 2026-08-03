import logging
import re
import time as _time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

import requests

from . import config

logger = logging.getLogger(__name__)


def fetch_today_papers() -> List[Dict]:
    """Fetch recent papers from arXiv listing page, filter by keywords, return full metadata.
    
    Uses main arxiv.org domain only — completely bypasses Fastly CDN (export.arxiv.org).
    Strategy:
      1. Scrape listing page per category -> IDs, titles, authors
      2. Title-only keyword filter (fast, no extra requests)
      3. Fetch abs page only for matched papers
    """
    now_bj = datetime.now(timezone.utc) + timedelta(hours=8)
    weekday = now_bj.weekday()
    
    # Smart date cutoff:
    # arXiv posts Mon-Fri US Eastern time. Deadline is 8PM ET = 8AM Beijing next day.
    # On weekday mornings (before noon Beijing), the previous day's papers may not be posted yet.
    # So we use a generous window:
    #   Mon: look back to Thu (4 days) — arXiv doesn't post weekends
    #   Tue-Sun: look back 3 days (covers weekends + late posts)
    hour_bj = now_bj.hour
    if weekday == 0:
        lookback_days = 4  # Monday: catch Fri
    elif hour_bj < 12:
        # Morning run: before arXiv has posted overnight papers, use wider window
        lookback_days = 3 if weekday <= 4 else 5
    else:
        # Afternoon run: papers should be posted, normal window
        lookback_days = 2 if weekday <= 4 else 5

    cutoff = (now_bj - timedelta(days=lookback_days)).strftime("%Y%m%d")
    logger.info(f"Date cutoff: {cutoff} (weekday={weekday}, hour={hour_bj}, lookback={lookback_days})")
    
    keywords = _load_keywords()
    
    # Collect all title-matched entries across categories, dedup by arxiv_id
    title_matched = {}
    seen_listing = set()

    for category in config.ARXIV_CATEGORIES:
        logger.info(f"Fetching {category} from arXiv listing page...")
        entries = _scrape_listing(category)
        if not entries:
            logger.warning(f"  Listing failed for {category}, trying /new page...")
            entries = _scrape_list_from_abs(category)
        logger.info(f"  Got {len(entries)} entries")
        
        for entry in entries:
            aid = entry["arxiv_id"]
            title_lower = entry["title"].lower()
            hit_kw = []
            for kw in keywords:
                if re.search(re.escape(kw.lower()), title_lower):
                    hit_kw.append(kw)
            if hit_kw and aid not in seen_listing:
                entry["matched_keywords"] = hit_kw
                title_matched[aid] = entry
                seen_listing.add(aid)

    logger.info(f"Title-matched (deduped): {len(title_matched)} papers")

    # Fetch full metadata for matched papers
    all_matched = []
    for aid, entry in title_matched.items():
        paper = _fetch_abs_metadata(aid)
        if not paper:
            continue
        paper["matched_keywords"] = entry["matched_keywords"]

        # Re-check with abstract for more keyword hits
        text = (paper["title"] + " " + paper["abstract"]).lower()
        for kw in keywords:
            if re.search(re.escape(kw.lower()), text) and kw not in paper["matched_keywords"]:
                paper["matched_keywords"].append(kw)

        # Date filter
        pub_str = paper["published"].strftime("%Y%m%d") if isinstance(paper["published"], datetime) else ""
        if pub_str >= cutoff:
            all_matched.append(paper)
        else:
            logger.info(f"  Skip {aid}: published {pub_str} < cutoff {cutoff}")

        _time.sleep(0.3)  # polite delay between abs page requests

    all_matched.sort(key=lambda x: x["published"], reverse=True)
    
    if len(all_matched) > config.MAX_RESULTS_PER_DAY:
        logger.info(f"Capping at {config.MAX_RESULTS_PER_DAY} (got {len(all_matched)})")
        all_matched = all_matched[:config.MAX_RESULTS_PER_DAY]

    return all_matched


def _load_keywords() -> List[str]:
    return config.KEYWORDS


def _scrape_listing(category: str) -> List[Dict]:
    """Scrape arxiv.org/list/{category}/recent for paper IDs, titles, authors."""
    url = f"https://arxiv.org/list/{category}/recent"
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.warning(f"  Listing page failed: {e}")
        return []

    blocks = html.split("name='item")[1:]
    entries = []
    for block in blocks:
        aid_m = re.search(r"arXiv:(\d+\.\d+)", block)
        if not aid_m:
            continue
        arxiv_id = aid_m.group(1)
        title_m = re.search(r"class='list-title mathjax'>.*?<span class='descriptor'>Title:</span>\s*(.*?)\s*</div>", block, re.DOTALL)
        title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""
        authors_m = re.search(r"class='list-authors'>(.*?)</div>", block, re.DOTALL)
        authors = []
        if authors_m:
            authors = [a.strip() for a in re.findall(r">([^<]+)</a>", authors_m.group(1))]
        entries.append({"arxiv_id": arxiv_id, "title": title, "authors": authors})
    return entries


def _scrape_list_from_abs(category: str) -> List[Dict]:
    """Fallback: scrape the /new listing page."""
    url = f"https://arxiv.org/list/{category}/new"
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.warning(f"  /new listing failed: {e}")
        return []

    blocks = html.split("name='item")[1:]
    entries = []
    for block in blocks:
        aid_m = re.search(r"arXiv:(\d+\.\d+)", block)
        if not aid_m:
            continue
        arxiv_id = aid_m.group(1)
        title_m = re.search(r"class='list-title mathjax'>.*?<span class='descriptor'>Title:</span>\s*(.*?)\s*</div>", block, re.DOTALL)
        title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""
        authors_m = re.search(r"class='list-authors'>(.*?)</div>", block, re.DOTALL)
        authors = []
        if authors_m:
            authors = [a.strip() for a in re.findall(r">([^<]+)</a>", authors_m.group(1))]
        entries.append({"arxiv_id": arxiv_id, "title": title, "authors": authors})
    return entries


def _fetch_abs_metadata(arxiv_id: str) -> Optional[Dict]:
    """Scrape arxiv.org/abs/{id} for full metadata."""
    url = f"https://arxiv.org/abs/{arxiv_id}"
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.warning(f"  Abs page failed for {arxiv_id}: {e}")
        return None

    # Title
    title_m = re.search(r'<h1 class="title mathjax">\s*<span class="descriptor">Title:</span>\s*(.*?)\s*</h1>', html, re.DOTALL)
    title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""

    # Authors
    authors = []
    authors_m = re.search(r'<div class="authors">.*?<span class="descriptor">Authors:</span>(.*?)</div>', html, re.DOTALL)
    if authors_m:
        authors = [a.strip() for a in re.findall(r">([^<]+)</a>", authors_m.group(1))]

    # Published date
    published = None
    date_m = re.search(r'<div class="dateline">\s*\[Submitted\s+on\s+(.*?)\]', html)
    if date_m:
        date_str = date_m.group(1).strip()
        for fmt in ["%d %b %Y", "%d %B %Y"]:
            try:
                published = datetime.strptime(date_str, fmt)
                break
            except ValueError:
                continue

    if published is None:
        published = datetime.now()

    # Abstract
    abstract = ""
    abs_m = re.search(r'<blockquote class="abstract mathjax">\s*<span class="descriptor">Abstract:</span>\s*(.*?)\s*</blockquote>', html, re.DOTALL)
    if abs_m:
        abstract = re.sub(r"<[^>]+>", "", abs_m.group(1)).strip()

    # Categories
    categories = []
    cat_m = re.search(r"Subjects:</td>\s*<td class=\"tablecell subjects\">(.*?)</td>", html, re.DOTALL)
    if cat_m:
        cat_text = re.sub(r"<[^>]+>", " ", cat_m.group(1))
        categories = [c.strip() for c in re.split(r"[;,]", cat_text) if c.strip()]

    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "categories": categories,
        "published": published,
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
        "abstract_url": f"https://arxiv.org/abs/{arxiv_id}",
        "source": "arxiv",
    }


def _keyword_filter(papers: List[Dict], keywords: List[str]) -> List[Dict]:
    """Full keyword filter on title + abstract."""
    matched = []
    seen_ids = set()
    for paper in papers:
        aid = paper.get("arxiv_id", "")
        if aid in seen_ids:
            continue
        seen_ids.add(aid)
        text = (paper["title"] + " " + paper.get("abstract", "")).lower()
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
    print(f"\n=== Found {len(papers)} related papers ===\n")
    for p in papers:
        print(f"  [{p['arxiv_id']}] {p['title'][:80]}")
        print(f"    Keywords: {', '.join(p['matched_keywords'][:5])}")
        print(f"    Published: {p['published']}")
        print()

