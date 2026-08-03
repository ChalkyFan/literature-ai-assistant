import sys, os, socket, time, logging, traceback, threading
from datetime import datetime, timezone, timedelta

# Setup logging - use app log, not the batch monitor log
log_file = os.path.join(os.path.dirname(__file__), "web_app.log")
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    force=True,
)
logger = logging.getLogger("web")

# Single-instance lock
lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    lock_socket.bind(("127.0.0.1", 18080))
except socket.error:
    logger.warning("Server already running (port 18080 locked)")
    print("Server already running (port 18080 locked)")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from web.app import app
from arxiv_assistant import db
from arxiv_assistant import pipeline_runner

# Global exception handler
@app.errorhandler(Exception)
def handle_exception(e):
    logger.error("Unhandled exception: %s", traceback.format_exc())
    return "Internal Server Error", 500

db.init_db()

# ── Built-in daily scheduler ──
SCHEDULE_HOUR = 11  # Beijing time
SCHEDULE_MINUTE = 0

def daily_scheduler():
    """Run the arXiv pipeline once per day at SCHEDULE_HOUR:SCHEDULE_MINUTE Beijing time."""
    last_run_date = ""
    while True:
        try:
            now_bj = datetime.now(timezone.utc) + timedelta(hours=8)
            today_str = now_bj.strftime("%Y-%m-%d")

            if (now_bj.hour == SCHEDULE_HOUR 
                and now_bj.minute >= SCHEDULE_MINUTE 
                and now_bj.minute < SCHEDULE_MINUTE + 30
                and last_run_date != today_str):
                last_run_date = today_str
                logger.info(f"[Scheduler] Running daily pipeline for {today_str}")
                try:
                    pipeline_runner.run()
                    logger.info("[Scheduler] Pipeline completed successfully")
                except Exception as e:
                    logger.error(f"[Scheduler] Pipeline failed: {e}")
                    # On failure, reset so it tries again next cycle
                    if last_run_date == today_str:
                        last_run_date = ""
        except Exception as e:
            logger.error(f"[Scheduler] Error in scheduler loop: {e}")

        time.sleep(1800)  # Check every 30 minutes

# Start scheduler in background
scheduler_thread = threading.Thread(target=daily_scheduler, daemon=True)
scheduler_thread.start()
logger.info(f"Daily scheduler started: runs at {SCHEDULE_HOUR}:{SCHEDULE_MINUTE:02d} Beijing time daily")
# ── End scheduler ──

logger.info("Web server starting at http://0.0.0.0:8080")
print("Web server starting at http://0.0.0.0:8080")

try:
    app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)
except Exception as e:
    logger.critical("Server crashed: %s", traceback.format_exc())
    print("Server crashed: %s" % e, file=sys.stderr)
    time.sleep(5)
    sys.exit(1)
