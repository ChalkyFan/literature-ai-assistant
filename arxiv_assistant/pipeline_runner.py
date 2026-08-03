"""Minimal wrapper to run the daily pipeline from within the web server process."""
import logging, sys, os
logger = logging.getLogger("pipeline_runner")

def run():
    """Run the full pipeline (fetch, download, AI analyze, report)."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    os.chdir(os.path.dirname(os.path.dirname(__file__)))
    from arxiv_assistant import db, fetcher, downloader, pdf_parser, ai_reader
    from arxiv_assistant.report import generate_daily_report
    from datetime import datetime, timezone, timedelta

    db.init_db()

    # Clear old history
    try:
        cleared = db.clear_user_history()
        logger.info(f"  Cleared {cleared} old history entries")
    except Exception as e:
        logger.warning(f"  Failed to clear history: {e}")

    logger.info("[1/4] Fetching new papers from arXiv...")
    import time as _time
    papers = []
    for attempt in range(2):
        try:
            papers = fetcher.fetch_today_papers()
            if papers:
                break
        except Exception as e:
            logger.warning(f"  Fetch attempt {attempt+1} failed: {e}")
        if attempt < 1:
            logger.info("  Waiting 60s before retry...")
            _time.sleep(60)
    logger.info(f"  Filtered to {len(papers)} papers")

    if not papers:
        logger.info("No new papers today. Pipeline done.")
        return

    logger.info("[2/4] Downloading PDFs...")
    new_ids = []
    for paper in papers:
        paper_id = db.insert_paper(paper)
        if paper_id:
            pdf_path = downloader.download_pdf(paper)
            if pdf_path:
                conn = db.get_connection()
                try:
                    conn.execute("UPDATE papers SET pdf_path = ? WHERE id = ?", (pdf_path, paper_id))
                    conn.commit()
                finally:
                    conn.close()
                new_ids.append(paper_id)
    logger.info(f"  Downloaded {len(new_ids)} papers")

    logger.info("[3/4] AI deep reading...")
    for paper_id in new_ids:
        try:
            paper_info = db.get_paper_by_id(paper_id)
            if not paper_info or not paper_info.get("pdf_path") or not os.path.exists(paper_info["pdf_path"]):
                logger.warning(f"  PDF not found for paper_id={paper_id}, skipping")
                continue
            title = paper_info["title"][:60]
            logger.info(f"  Analyzing: {title}...")
            parsed = pdf_parser.parse_pdf(paper_info["pdf_path"])
            analysis = ai_reader.analyze_paper(parsed.text)
            db.save_ai_summary(paper_id, analysis)
            for fig in parsed.figures:
                db.save_figure(
                    paper_id=paper_id,
                    figure_number=fig["figure_number"],
                    caption=fig.get("caption", ""),
                    file_path=fig["file_path"],
                )
            logger.info(f"  Done: {title}")
        except Exception as e:
            logger.error(f"  Failed to process paper_id={paper_id}: {e}")

    logger.info("[4/4] Generating daily report...")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    papers_with_analysis = db.get_papers_by_date(today)
    if not papers_with_analysis:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        papers_with_analysis = db.get_papers_by_date(yesterday)
        if papers_with_analysis:
            today = yesterday
    report_path = generate_daily_report(papers_with_analysis, today)
    logger.info(f"  Report: {report_path}")
    logger.info("Pipeline completed")
