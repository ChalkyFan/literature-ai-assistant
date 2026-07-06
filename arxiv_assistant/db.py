"""SQLite database operations"""


import sqlite3
import hashlib


import os


import logging


from datetime import datetime


from typing import List, Dict, Optional


from . import config





logger = logging.getLogger(__name__)





DB_PATH = os.environ.get('LITERATURE_DB_PATH') or os.path.join(os.path.dirname(os.path.dirname(__file__)), config.DB_PATH)








def get_connection() -> sqlite3.Connection:


    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


    conn = sqlite3.connect(DB_PATH, timeout=10)


    conn.row_factory = sqlite3.Row


    conn.execute("PRAGMA journal_mode=WAL")


    conn.execute("PRAGMA foreign_keys=ON")


    return conn








def init_db():


    conn = get_connection()


    try:


        conn.executescript("""


            CREATE TABLE IF NOT EXISTS papers (


                id INTEGER PRIMARY KEY AUTOINCREMENT,


                arxiv_id TEXT UNIQUE NOT NULL,


                title TEXT NOT NULL,


                authors TEXT,


                abstract TEXT,


                categories TEXT,


                published_date TEXT,


                fetched_date TEXT DEFAULT (datetime('now')),


                pdf_path TEXT,


                status TEXT DEFAULT 'unread',


                is_starred INTEGER DEFAULT 0,


                source TEXT DEFAULT 'arxiv',


                created_at TEXT DEFAULT (datetime('now')),


                updated_at TEXT DEFAULT (datetime('now'))


            );


            CREATE TABLE IF NOT EXISTS ai_summaries (


                id INTEGER PRIMARY KEY AUTOINCREMENT,


                paper_id INTEGER NOT NULL,


                core_problem TEXT,


                method TEXT,


                key_results TEXT,


                conclusions TEXT,


                limitations TEXT,


                value_rating INTEGER,


                one_line_value TEXT,


                full_analysis TEXT,


                model_used TEXT,


                created_at TEXT DEFAULT (datetime('now')),


                updated_at TEXT,


                FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE


            );


            CREATE TABLE IF NOT EXISTS figures (


                id INTEGER PRIMARY KEY AUTOINCREMENT,


                paper_id INTEGER NOT NULL,


                figure_number TEXT,


                caption TEXT,


                file_path TEXT,


                ai_description TEXT,


                created_at TEXT DEFAULT (datetime('now')),


                FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE


            );


            CREATE TABLE IF NOT EXISTS keywords_matched (


                id INTEGER PRIMARY KEY AUTOINCREMENT,


                paper_id INTEGER NOT NULL,


                keyword TEXT NOT NULL,


                FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE


            );


            CREATE TABLE IF NOT EXISTS paper_tags (


                id INTEGER PRIMARY KEY AUTOINCREMENT,


                paper_id INTEGER NOT NULL,


                tag_name TEXT NOT NULL,


                created_at TEXT DEFAULT CURRENT_TIMESTAMP,


                FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,


                UNIQUE(paper_id, tag_name)


            );


            CREATE TABLE IF NOT EXISTS ai_conversations (


                id INTEGER PRIMARY KEY AUTOINCREMENT,


                paper_id INTEGER NOT NULL,


                question TEXT NOT NULL,


                answer TEXT,


                created_at TEXT DEFAULT CURRENT_TIMESTAMP,


                FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE


            );


            CREATE INDEX IF NOT EXISTS idx_papers_arxiv_id ON papers(arxiv_id);


            CREATE INDEX IF NOT EXISTS idx_papers_date ON papers(published_date);


            CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status);


            CREATE INDEX IF NOT EXISTS idx_tags_paper ON paper_tags(paper_id);


            CREATE INDEX IF NOT EXISTS idx_conv_paper ON ai_conversations(paper_id);


        """)


    except sqlite3.OperationalError:


        pass


    try:


        conn.execute("ALTER TABLE ai_summaries ADD COLUMN updated_at TEXT")


    except sqlite3.OperationalError:


        pass


    try:


        conn.execute("ALTER TABLE papers ADD COLUMN source TEXT DEFAULT 'arxiv'")


    except sqlite3.OperationalError:


        pass


    try:


        conn.execute("ALTER TABLE papers ADD COLUMN affiliations TEXT DEFAULT \"\"")


    except sqlite3.OperationalError:


        pass


    try:


        conn.execute("ALTER TABLE papers ADD COLUMN is_hidden INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE papers ADD COLUMN uploaded_by TEXT DEFAULT ''")


    except sqlite3.OperationalError:


        pass


    conn.executescript("""


        CREATE TABLE IF NOT EXISTS users (


            id INTEGER PRIMARY KEY AUTOINCREMENT,


            username TEXT UNIQUE NOT NULL,


            color TEXT NOT NULL DEFAULT '#3b82f6',


            role TEXT NOT NULL DEFAULT 'regular',


            created_at TEXT DEFAULT (datetime('now'))


        );


        CREATE TABLE IF NOT EXISTS user_history (


            id INTEGER PRIMARY KEY AUTOINCREMENT,


            paper_id INTEGER NOT NULL,


            username TEXT NOT NULL,


            viewed_at TEXT DEFAULT (datetime('now', 'localtime')),


            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE


        );


        CREATE TABLE IF NOT EXISTS user_stars (


            id INTEGER PRIMARY KEY AUTOINCREMENT,


            paper_id INTEGER NOT NULL,


            username TEXT NOT NULL,


            created_at TEXT DEFAULT (datetime('now', 'localtime')),


            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,


            UNIQUE(paper_id, username)


        );


        CREATE TABLE IF NOT EXISTS detailed_analyses (


                id INTEGER PRIMARY KEY AUTOINCREMENT,


                paper_id INTEGER UNIQUE NOT NULL,


                content TEXT,


                created_at TEXT DEFAULT (datetime('now')),


                FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE


            );


            CREATE TABLE IF NOT EXISTS keyword_weights (


                id INTEGER PRIMARY KEY AUTOINCREMENT,


                keyword TEXT UNIQUE NOT NULL,


                weight REAL NOT NULL DEFAULT 1.0,


                created_at TEXT DEFAULT (datetime('now')),


                created_by TEXT DEFAULT ''


            );


            CREATE TABLE IF NOT EXISTS paper_reporters (


            id INTEGER PRIMARY KEY AUTOINCREMENT,


            paper_id INTEGER NOT NULL,


            username TEXT NOT NULL,


            color TEXT NOT NULL DEFAULT '#3b82f6',


            created_at TEXT DEFAULT CURRENT_TIMESTAMP,


            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,


            UNIQUE(paper_id, username)


        );


    """)


    conn.commit()


    logger.info("Database initialized")


    conn.close()








def paper_exists(arxiv_id: str) -> bool:


    conn = get_connection()


    try:


        row = conn.execute("SELECT 1 FROM papers WHERE arxiv_id = ?", (arxiv_id,)).fetchone()


        return row is not None


    finally:


        conn.close()








def insert_paper(paper: Dict, source: str = "arxiv") -> Optional[int]:


    conn = get_connection()


    try:


        published = paper["published"]


        if hasattr(published, "strftime"):


            published = published.strftime("%Y-%m-%d")


        cursor = conn.execute("""


            INSERT OR IGNORE INTO papers


                (arxiv_id, title, authors, affiliations, abstract, categories, published_date, pdf_path, source)


            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)


        """, (


            paper["arxiv_id"], paper["title"],


            ", ".join(paper["authors"]) if isinstance(paper.get("authors", []), list) else paper.get("authors", ""),


            paper.get("affiliations", ""),


            paper.get("abstract", ""),


            " ".join(paper.get("categories", [])),


            published, paper.get("pdf_path", ""),


            source,


        ))


        paper_id = cursor.lastrowid


        if paper_id == 0:


            row = conn.execute("SELECT id FROM papers WHERE arxiv_id = ?", (paper["arxiv_id"],)).fetchone()


            paper_id = row["id"] if row else None


        else:


            for kw in paper.get("matched_keywords", []):


                conn.execute("INSERT INTO keywords_matched (paper_id, keyword) VALUES (?, ?)", (paper_id, kw))


        conn.commit()


        return paper_id


    finally:


        conn.close()








def get_papers_by_date(date: str = None, sort_by: str = "rating", source: str = "arxiv") -> List[Dict]:


    if date is None:


        date = datetime.now().strftime("%Y-%m-%d")


    conn = get_connection()


    try:


        order_clause = {


            "rating": "CASE WHEN s.value_rating IS NOT NULL THEN s.value_rating ELSE 0 END DESC, p.published_date DESC",


            "date": "p.published_date DESC, p.id DESC",


            "keywords": "(SELECT COUNT(*) FROM keywords_matched k WHERE k.paper_id = p.id) DESC, p.published_date DESC",


        }.get(sort_by, "p.published_date DESC")





        if source:


            rows = conn.execute(


                "SELECT p.*, s.value_rating, s.one_line_value FROM papers p "


                "LEFT JOIN ai_summaries s ON s.paper_id = p.id "


                "WHERE p.published_date = ? AND p.source = ? "


                "ORDER BY " + order_clause,


                (date, source)


            ).fetchall()


        else:


            rows = conn.execute(


                "SELECT p.*, s.value_rating, s.one_line_value FROM papers p "


                "LEFT JOIN ai_summaries s ON s.paper_id = p.id "


                "WHERE p.published_date = ? "


                "ORDER BY " + order_clause,


                (date,)


            ).fetchall()


        return [dict(r) for r in rows]


    finally:


        conn.close()








def get_all_papers(limit: int = 100, offset: int = 0) -> List[Dict]:


    conn = get_connection()


    try:


        rows = conn.execute("""


            SELECT p.*, s.value_rating, s.one_line_value


            FROM papers p LEFT JOIN ai_summaries s ON s.paper_id = p.id


            ORDER BY p.published_date DESC, p.id DESC LIMIT ? OFFSET ?


        """, (limit, offset)).fetchall()


        return [dict(r) for r in rows]


    finally:


        conn.close()








def get_paper_by_id(paper_id: int) -> Optional[Dict]:


    conn = get_connection()


    try:


        paper = conn.execute("""


            SELECT p.*, s.core_problem, s.method, s.key_results, s.conclusions,


                   s.limitations, s.value_rating, s.one_line_value, s.full_analysis


            FROM papers p LEFT JOIN ai_summaries s ON s.paper_id = p.id


            WHERE p.id = ?


        """, (paper_id,)).fetchone()


        if not paper:


            return None


        paper = dict(paper)


        paper["figures"] = [dict(f) for f in conn.execute(


            "SELECT * FROM figures WHERE paper_id = ? ORDER BY figure_number", (paper_id,)


        ).fetchall()]


        paper["keywords"] = [r["keyword"] for r in conn.execute(


            "SELECT keyword FROM keywords_matched WHERE paper_id = ?", (paper_id,)


        ).fetchall()]


        paper["tags"] = [r["tag_name"] for r in conn.execute(


            "SELECT tag_name FROM paper_tags WHERE paper_id = ? ORDER BY created_at", (paper_id,)


        ).fetchall()]


        return paper


    finally:


        conn.close()








def update_paper_status(paper_id: int, status: str):


    conn = get_connection()


    try:


        conn.execute("UPDATE papers SET status = ?, updated_at = datetime('now') WHERE id = ?", (status, paper_id))


        conn.commit()


    finally:


        conn.close()








def toggle_star(paper_id: int, username: str = None) -> bool:


    """Toggle star for a paper. If username is provided, use per-user star."""


    conn = get_connection()


    try:


        if username:


            existing = conn.execute("SELECT 1 FROM user_stars WHERE paper_id=? AND username=?", (paper_id, username)).fetchone()


            if existing:


                conn.execute("DELETE FROM user_stars WHERE paper_id=? AND username=?", (paper_id, username))


                conn.commit()


                return False


            else:


                conn.execute("INSERT OR IGNORE INTO user_stars (paper_id, username) VALUES (?, ?)", (paper_id, username))


                conn.commit()


                return True


        else:


            current = conn.execute("SELECT is_starred FROM papers WHERE id = ?", (paper_id,)).fetchone()


            new_val = 0 if current["is_starred"] else 1


            conn.execute("UPDATE papers SET is_starred = ?, updated_at = datetime('now') WHERE id = ?", (new_val, paper_id))


            conn.commit()


            return bool(new_val)


    finally:


        conn.close()





def save_ai_summary(paper_id: int, summary: Dict):


    conn = get_connection()


    try:


        exists = conn.execute("SELECT 1 FROM ai_summaries WHERE paper_id = ?", (paper_id,)).fetchone()


        if exists:


            conn.execute("""UPDATE ai_summaries SET core_problem=?, method=?, key_results=?, conclusions=?,


                limitations=?, value_rating=?, one_line_value=?, full_analysis=?, updated_at=datetime('now')


                WHERE paper_id=?""", (


                summary.get("core_problem", ""), summary.get("method", ""),


                summary.get("key_results", ""), summary.get("conclusions", ""),


                summary.get("limitations", ""), summary.get("value_rating"),


                summary.get("one_line_value", ""), summary.get("full_analysis", ""), paper_id))


        else:


            conn.execute("""INSERT INTO ai_summaries


                (paper_id, core_problem, method, key_results, conclusions, limitations, value_rating, one_line_value, full_analysis)


                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (


                paper_id, summary.get("core_problem", ""), summary.get("method", ""),


                summary.get("key_results", ""), summary.get("conclusions", ""),


                summary.get("limitations", ""), summary.get("value_rating"),


                summary.get("one_line_value", ""), summary.get("full_analysis", "")))


        conn.commit()


    finally:


        conn.close()








def save_figure(paper_id: int, figure_number: str, caption: str, file_path: str, ai_description: str = ""):


    conn = get_connection()


    try:


        conn.execute("""INSERT OR IGNORE INTO figures


            (paper_id, figure_number, caption, file_path, ai_description)


            VALUES (?, ?, ?, ?, ?)""", (paper_id, figure_number, caption, file_path, ai_description))


        conn.commit()


    finally:


        conn.close()








def search_papers(query: str, limit: int = 50) -> List[Dict]:


    conn = get_connection()


    try:


        rows = conn.execute("""


            SELECT p.*, s.one_line_value FROM papers p


            LEFT JOIN ai_summaries s ON s.paper_id = p.id


            WHERE p.title LIKE ? OR p.authors LIKE ? OR p.abstract LIKE ?


            ORDER BY p.published_date DESC LIMIT ?


        """, (f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()


        return [dict(r) for r in rows]


    finally:


        conn.close()








def add_tag(paper_id: int, tag_name: str) -> bool:


    conn = get_connection()


    try:


        conn.execute("INSERT OR IGNORE INTO paper_tags (paper_id, tag_name) VALUES (?, ?)", (paper_id, tag_name))


        conn.commit()


        return conn.total_changes > 0


    finally:


        conn.close()








def remove_tag(paper_id: int, tag_name: str):


    conn = get_connection()


    try:


        conn.execute("DELETE FROM paper_tags WHERE paper_id = ? AND tag_name = ?", (paper_id, tag_name))


        conn.commit()


    finally:


        conn.close()








def get_tags(paper_id: int) -> List[str]:


    conn = get_connection()


    try:


        rows = conn.execute("SELECT tag_name FROM paper_tags WHERE paper_id = ? ORDER BY created_at", (paper_id,)).fetchall()


        return [r["tag_name"] for r in rows]


    finally:


        conn.close()








def get_papers_by_tag(tag_name: str, limit: int = 50) -> List[Dict]:


    conn = get_connection()


    try:


        rows = conn.execute("""


            SELECT p.*, s.value_rating, s.one_line_value


            FROM papers p LEFT JOIN ai_summaries s ON s.paper_id = p.id


            JOIN paper_tags t ON t.paper_id = p.id


            WHERE t.tag_name = ?


            ORDER BY p.published_date DESC LIMIT ?


        """, (tag_name, limit)).fetchall()


        return [dict(r) for r in rows]


    finally:


        conn.close()








def get_custom_papers(limit: int = 50, offset: int = 0, username: str = None) -> List[Dict]:


    conn = get_connection()


    try:


        rows = conn.execute("""


            SELECT p.*, s.value_rating, s.one_line_value


            FROM papers p LEFT JOIN ai_summaries s ON s.paper_id = p.id


            WHERE p.source = 'custom' AND (p.is_hidden IS NULL OR p.is_hidden = 0)
              AND (p.uploaded_by = ? OR ? IS NULL)


            ORDER BY p.created_at DESC LIMIT ? OFFSET ?


        """, (username, username, limit, offset)).fetchall()


        return [dict(r) for r in rows]


    finally:


        conn.close()








def save_conversation(paper_id: int, question: str, answer: str) -> int:


    conn = get_connection()


    try:


        cursor = conn.execute("INSERT INTO ai_conversations (paper_id, question, answer) VALUES (?, ?, ?)", (paper_id, question, answer))


        conn.commit()


        return cursor.lastrowid


    finally:


        conn.close()








def get_conversations(paper_id: int, limit: int = 20) -> List[Dict]:


    conn = get_connection()


    try:


        rows = conn.execute("SELECT * FROM ai_conversations WHERE paper_id = ? ORDER BY created_at ASC LIMIT ?", (paper_id, limit)).fetchall()


        return [dict(r) for r in rows]


    finally:


        conn.close()








def hide_paper(paper_id: int):


    """Soft delete - hide from web but keep in DB."""


    conn = get_connection()


    try:


        conn.execute("UPDATE papers SET is_hidden=1 WHERE id=?", (paper_id,))


        conn.commit()


    finally:


        conn.close()








def delete_conversation(conv_id: int) -> bool:


    """Delete a single conversation by ID."""


    conn = get_connection()


    try:


        conn.execute("DELETE FROM ai_conversations WHERE id=?", (conv_id,))


        conn.commit()


        return conn.total_changes > 0


    finally:


        conn.close()








def get_starred_papers(limit: int = 50, username: str = None) -> List[Dict]:


    """Get starred papers. If username is provided, use per-user star."""


    conn = get_connection()


    try:


        if username:


            rows = conn.execute("""


                SELECT p.*, s.value_rating, s.one_line_value, 1 as is_starred


                FROM user_stars us


                JOIN papers p ON p.id = us.paper_id


                LEFT JOIN ai_summaries s ON s.paper_id = p.id


                WHERE us.username = ? AND (p.is_hidden IS NULL OR p.is_hidden = 0)


                ORDER BY us.created_at DESC LIMIT ?


            """, (username, limit)).fetchall()


        else:


            rows = conn.execute("""


                SELECT p.*, s.value_rating, s.one_line_value


                FROM papers p LEFT JOIN ai_summaries s ON s.paper_id = p.id


                WHERE p.is_starred = 1 AND (p.is_hidden IS NULL OR p.is_hidden = 0)


                ORDER BY p.updated_at DESC LIMIT ?


            """, (limit,)).fetchall()


        return [dict(r) for r in rows]


    finally:


        conn.close()





def get_or_create_user(username: str, color: str = "#3b82f6", role: str = "regular", password_hash: str = "") -> Dict:


    conn = get_connection()


    try:


        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


        if row:


            return dict(row)


        conn.execute("INSERT INTO users (username, color, role, password_hash) VALUES (?, ?, ?, ?)", (username, color, role, password_hash))


        conn.commit()


        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


        return dict(row)


    finally:


        conn.close()





def get_user(username: str) -> Optional[Dict]:


    conn = get_connection()


    try:


        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


        return dict(row) if row else None


    finally:


        conn.close()





def get_all_users() -> List[Dict]:


    conn = get_connection()


    try:


        rows = conn.execute("SELECT username, color, role FROM users ORDER BY username").fetchall()


        return [dict(r) for r in rows]


    finally:


        conn.close()





def set_paper_report(paper_id: int, username: str, color: str) -> bool:


    conn = get_connection()


    try:


        count = conn.execute("SELECT COUNT(*) as c FROM paper_reporters WHERE paper_id=?", (paper_id,)).fetchone()["c"]


        exists = conn.execute("SELECT 1 FROM paper_reporters WHERE paper_id=? AND username=?", (paper_id, username)).fetchone()


        if exists:


            conn.execute("DELETE FROM paper_reporters WHERE paper_id=? AND username=?", (paper_id, username))


            # Remove tag if no other reporters


            remaining = conn.execute("SELECT COUNT(*) as c FROM paper_reporters WHERE paper_id=?", (paper_id,)).fetchone()["c"]


            if remaining == 0:


                conn.execute("DELETE FROM paper_tags WHERE paper_id=? AND tag_name='\u7ec4\u4f1a\u62a5\u544a'", (paper_id,))


            conn.commit()


            return False


        if count >= 2:


            return False


        conn.execute("INSERT OR IGNORE INTO paper_reporters (paper_id, username, color) VALUES (?, ?, ?)", (paper_id, username, color))


        # Add tag


        conn.execute("INSERT OR IGNORE INTO paper_tags (paper_id, tag_name) VALUES (?, '\u7ec4\u4f1a\u62a5\u544a')", (paper_id,))


        conn.commit()


        return True


    finally:


        conn.close()





def get_paper_reporters(paper_id: int) -> List[Dict]:


    conn = get_connection()


    try:


        rows = conn.execute("SELECT username, color FROM paper_reporters WHERE paper_id=? ORDER BY created_at", (paper_id,)).fetchall()


        return [dict(r) for r in rows]


    finally:


        conn.close()





def get_user_report_papers(username: str) -> List[int]:


    conn = get_connection()


    try:


        rows = conn.execute("SELECT paper_id FROM paper_reporters WHERE username=?", (username,)).fetchall()


        return [r["paper_id"] for r in rows]


    finally:


        conn.close()








def log_view(paper_id: int, username: str):


    """Record a paper view in user history."""


    conn = get_connection()


    try:


        conn.execute("INSERT INTO user_history (paper_id, username) VALUES (?, ?)", (paper_id, username))


        conn.commit()


    finally:


        conn.close()





def get_user_history(username: str, limit: int = 50) -> List[Dict]:


    """Get papers viewed by user in the past 24 hours."""


    conn = get_connection()


    try:


        rows = conn.execute("""


            SELECT p.*, s.value_rating, s.one_line_value, h.viewed_at


            FROM user_history h


            JOIN papers p ON p.id = h.paper_id


            LEFT JOIN ai_summaries s ON s.paper_id = p.id


            WHERE h.username = ? AND h.viewed_at >= datetime('now', '-1 day', 'localtime')


              AND (p.is_hidden IS NULL OR p.is_hidden = 0)


            GROUP BY p.id


            ORDER BY h.viewed_at DESC


            LIMIT ?


        """, (username, limit)).fetchall()


        return [dict(r) for r in rows]


    finally:


        conn.close()





def clear_user_history():


    """Delete history older than 1 day - called daily during pipeline."""


    conn = get_connection()


    try:


        conn.execute("DELETE FROM user_history WHERE viewed_at < datetime('now', '-1 day', 'localtime')")


        conn.commit()


        deleted = conn.total_changes


        return deleted


    finally:


        conn.close()








def get_user_star_map(paper_ids: List[int], username: str) -> Dict[int, bool]:


    """Returns a dict {paper_id: is_starred} for a user."""


    if not paper_ids:


        return {}


    conn = get_connection()


    try:


        placeholders = ",".join("?" * len(paper_ids))


        rows = conn.execute(f"SELECT paper_id FROM user_stars WHERE paper_id IN ({placeholders}) AND username=?", (*paper_ids, username)).fetchall()


        starred_ids = {r["paper_id"] for r in rows}


        return {pid: pid in starred_ids for pid in paper_ids}


    finally:


        conn.close()





def get_keyword_counts(paper_ids: List[int]) -> Dict[int, int]:


    """Returns {paper_id: keyword_count} for a list of paper IDs."""


    if not paper_ids:


        return {}


    conn = get_connection()


    try:


        placeholders = ",".join("?" * len(paper_ids))


        rows = conn.execute(f"SELECT paper_id, COUNT(*) as cnt FROM keywords_matched WHERE paper_id IN ({placeholders}) GROUP BY paper_id", paper_ids).fetchall()


        result = {r["paper_id"]: r["cnt"] for r in rows}


        for pid in paper_ids:


            result.setdefault(pid, 0)


        return result


    finally:


        conn.close()





# ===== Keyword Weight Management =====


def get_all_keywords() -> List[Dict]:


    conn = get_connection()


    try:


        rows = conn.execute("SELECT * FROM keyword_weights ORDER BY keyword").fetchall()


        return [dict(r) for r in rows]


    finally:


        conn.close()





def add_keyword(keyword: str, weight: float, created_by: str = "") -> bool:


    conn = get_connection()


    try:


        conn.execute("INSERT OR IGNORE INTO keyword_weights (keyword, weight, created_by) VALUES (?, ?, ?)",


                     (keyword, weight, created_by))


        conn.commit()


        return conn.total_changes > 0


    finally:


        conn.close()





def update_keyword(kw_id: int, keyword: str = None, weight: float = None) -> bool:


    conn = get_connection()


    try:


        if keyword is not None and weight is not None:


            conn.execute("UPDATE keyword_weights SET keyword=?, weight=? WHERE id=?", (keyword, weight, kw_id))


        elif weight is not None:


            conn.execute("UPDATE keyword_weights SET weight=? WHERE id=?", (weight, kw_id))


        elif keyword is not None:


            conn.execute("UPDATE keyword_weights SET keyword=? WHERE id=?", (keyword, kw_id))


        conn.commit()


        return conn.total_changes > 0


    finally:


        conn.close()





def delete_keyword(kw_id: int) -> bool:


    conn = get_connection()


    try:


        conn.execute("DELETE FROM keyword_weights WHERE id=?", (kw_id,))


        conn.commit()


        return conn.total_changes > 0


    finally:


        conn.close()





def check_keyword_exists(keyword: str) -> bool:


    conn = get_connection()


    try:


        row = conn.execute("SELECT 1 FROM keyword_weights WHERE keyword=?", (keyword,)).fetchone()


        return row is not None


    finally:


        conn.close()





# ===== Detailed Analysis =====


def save_detailed_analysis(paper_id: int, content: str):


    conn = get_connection()


    try:


        conn.execute("""


            INSERT INTO detailed_analyses (paper_id, content) VALUES (?, ?)


            ON CONFLICT(paper_id) DO UPDATE SET content=excluded.content, created_at=datetime("now")


        """, (paper_id, content))


        conn.commit()


    finally:


        conn.close()





def get_detailed_analysis(paper_id: int) -> Optional[Dict]:


    conn = get_connection()


    try:


        row = conn.execute("SELECT * FROM detailed_analyses WHERE paper_id=?", (paper_id,)).fetchone()


        return dict(row) if row else None


    finally:


        conn.close()




def verify_user(username: str, password: str) -> Optional[Dict]:

    """Verify user login with password. Returns user dict or None."""

    conn = get_connection()

    try:

        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

        if not row:

            return None

        user = dict(row)

        pw_hash = hashlib.sha256(password.encode()).hexdigest()

        if user.get("password_hash", "") != pw_hash:

            return None

        return user

    finally:

        conn.close()



