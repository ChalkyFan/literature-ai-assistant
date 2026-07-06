"""Check if today's papers have been fetched"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from arxiv_assistant import db
from datetime import datetime

db.init_db()

today = datetime.now().strftime("%Y-%m-%d")
papers = db.get_papers_by_date(today)

if papers:
    print(f"Today ({today}): {len(papers)} papers already fetched.")
    sys.exit(0)  # Already fetched
else:
    print(f"Today ({today}): No papers found. Pipeline should run.")
    sys.exit(2)  # Needs fetching
