"""Sync production database to development database for testing"""
import os, sys, sqlite3, shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROD_DB = os.path.join(BASE_DIR, "data", "literature.db")
DEV_DB = os.path.join(BASE_DIR, "data", "literature_dev.db")

SYNC_TABLES = [
    "papers",
    "ai_summaries",
    "figures",
    "keywords_matched",
    "paper_tags",
    "ai_conversations",
    "keyword_weights",
    "paper_reporters",
    "detailed_analyses",
]


def sync():
    if not os.path.exists(PROD_DB):
        print("Error: Production database not found at", PROD_DB)
        sys.exit(1)

    print("Syncing from:", PROD_DB)
    print("Syncing to:  ", DEV_DB)

    if os.path.exists(DEV_DB):
        os.remove(DEV_DB)
        print("Removed existing dev database")

    prod_conn = sqlite3.connect(PROD_DB)
    prod_conn.execute("PRAGMA wal_checkpoint(FULL)")
    prod_conn.close()

    shutil.copy2(PROD_DB, DEV_DB)
    print("Copied production database as base")

    dev_conn = sqlite3.connect(DEV_DB)
    dev_conn.execute("PRAGMA foreign_keys=OFF")

    private_tables = ["users", "user_history", "user_stars"]
    for table in private_tables:
        dev_conn.execute("DROP TABLE IF EXISTS " + table)
        print("Dropped user-private table: " + table)

    dev_conn.execute("PRAGMA foreign_keys=ON")
    dev_conn.commit()

    for table in SYNC_TABLES:
        count = dev_conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
        print("  " + table + ": " + str(count) + " rows synced")

    dev_conn.close()
    print()
    print("Sync complete! Dev database is ready.")
    print("Path: " + DEV_DB)


if __name__ == "__main__":
    sync()
