"""PDF downloader"""

import os
import logging
import requests
from datetime import datetime
from typing import Dict, Optional
from . import config

logger = logging.getLogger(__name__)


def download_pdf(paper: Dict) -> Optional[str]:
    """Download PDF, return local path. Returns existing path if already downloaded."""
    arxiv_id = paper["arxiv_id"]
    published = paper["published"]
    if hasattr(published, "strftime"):
        date_str = published.strftime("%Y-%m-%d")
        month_dir = published.strftime("%Y-%m")
    else:
        date_str = str(published)[:10]
        month_dir = str(published)[:7]

    base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), config.PAPERS_DIR, month_dir)
    os.makedirs(base_dir, exist_ok=True)

    filename = f"arxiv-{arxiv_id}.pdf"
    filepath = os.path.join(base_dir, filename)

    if os.path.exists(filepath) and os.path.getsize(filepath) > 10000:
        logger.info(f"PDF exists: {filepath}")
        return filepath

    pdf_url = paper.get("pdf_url", f"https://arxiv.org/pdf/{arxiv_id}.pdf")
    try:
        logger.info(f"Downloading: {pdf_url}")
        headers = {"User-Agent": "ArxivAssistant/1.0 (research lab tool)"}
        resp = requests.get(pdf_url, headers=headers, timeout=60)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
        logger.info(f"Downloaded: {filepath} ({len(resp.content)} bytes)")
        return filepath
    except Exception as e:
        logger.error(f"Download failed {pdf_url}: {e}")
        return None
