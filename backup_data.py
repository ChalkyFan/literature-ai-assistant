import sqlite3, os, json, time
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db = os.path.join(BASE_DIR, 'data', 'literature.db')
backup_dir = os.path.join(BASE_DIR, 'data')
ts = datetime.now().strftime('%Y%m%d_%H%M%S')
backup_file = os.path.join(backup_dir, f'backup_{ts}.json')

# === Cleanup: remove backups older than 15 days ===
cutoff = datetime.now() - timedelta(days=15)
deleted = 0
for f in os.listdir(backup_dir):
    if f.startswith('backup_') and f.endswith('.json'):
        fpath = os.path.join(backup_dir, f)
        mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
        if mtime < cutoff:
            os.remove(fpath)
            deleted += 1
if deleted:
    print(f'Cleaned {deleted} old backup(s)')

# === Backup ===
if not os.path.exists(db):
    print(f'DB not found: {db}')
    exit(1)

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

backup = {}

cur.execute('SELECT username, role, color, password_hash, created_at FROM users')
backup['users'] = [dict(r) for r in cur.fetchall()]

cur.execute('''
    SELECT pt.id, pt.paper_id, p.arxiv_id, p.title as paper_title, pt.tag_name, pt.created_at
    FROM paper_tags pt LEFT JOIN papers p ON pt.paper_id = p.id ORDER BY pt.id
''')
backup['paper_tags'] = [dict(r) for r in cur.fetchall()]

cur.execute('SELECT * FROM keyword_weights')
backup['keyword_weights'] = [dict(r) for r in cur.fetchall()]

cur.execute('''
    SELECT da.id, da.paper_id, p.arxiv_id, p.title as paper_title,
           substr(da.content, 1, 200) as content_preview, da.created_at
    FROM detailed_analyses da LEFT JOIN papers p ON da.paper_id = p.id ORDER BY da.id
''')
backup['detailed_analyses'] = [dict(r) for r in cur.fetchall()]

cur.execute('''
    SELECT pr.id, pr.paper_id, p.arxiv_id, p.title as paper_title, pr.username, pr.color, pr.created_at
    FROM paper_reporters pr LEFT JOIN papers p ON pr.paper_id = p.id ORDER BY pr.id
''')
backup['paper_reporters'] = [dict(r) for r in cur.fetchall()]

cur.execute('''
    SELECT us.id, us.paper_id, p.arxiv_id, p.title as paper_title, us.username, us.created_at
    FROM user_stars us LEFT JOIN papers p ON us.paper_id = p.id ORDER BY us.id
''')
backup['user_stars'] = [dict(r) for r in cur.fetchall()]

cur.execute('''
    SELECT ac.id, ac.paper_id, p.arxiv_id, p.title as paper_title,
           substr(ac.question, 1, 100) as question_preview,
           substr(ac.answer, 1, 100) as answer_preview,
           ac.created_at
    FROM ai_conversations ac LEFT JOIN papers p ON ac.paper_id = p.id ORDER BY ac.id
''')
backup['ai_conversations'] = [dict(r) for r in cur.fetchall()]

cur.execute('''
    SELECT km.id, km.paper_id, p.arxiv_id, p.title as paper_title, km.keyword
    FROM keywords_matched km LEFT JOIN papers p ON km.paper_id = p.id ORDER BY km.id
''')
backup['keywords_matched'] = [dict(r) for r in cur.fetchall()]

backup['_metadata'] = {
    'export_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'database': 'literature.db'
}

with open(backup_file, 'w', encoding='utf-8') as f:
    json.dump(backup, f, ensure_ascii=False, indent=2)

size_kb = os.path.getsize(backup_file) / 1024
print(f'Backup OK: {os.path.basename(backup_file)} ({size_kb:.1f} KB)')

conn.close()