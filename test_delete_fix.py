
import requests, json, base64

# Test admin delete
s = requests.Session()
r = s.post('http://localhost:8080/api/auth/login', json={'username':'ADMIN','password':'administrator'}, timeout=10)
user = r.json()['user']
encoded = base64.b64encode(json.dumps(user).encode()).decode()
s.cookies.set('arxiv_user', encoded)

# Check all.html for delete btn
r = s.get('http://localhost:8080/all', timeout=10)
t = r.text
has_delete_btn = '\u5220\u9664\u8be5\u6761\u76ee' in t
print('Admin sees delete btn in all.html:', has_delete_btn)

# Test delete via API
r = s.post('http://localhost:8080/api/paper/1/hide', json={'username':'ADMIN'}, timeout=10)
print('Admin delete API:', r.status_code, r.json())

# Unhide
import sqlite3, os, sys
sys.path.insert(0, '.')
from arxiv_assistant import config
db_path = os.path.abspath(config.DB_PATH)
conn = sqlite3.connect(db_path)
conn.execute('UPDATE papers SET is_hidden=0 WHERE id=1')
conn.commit()
conn.close()

# Test regular user does NOT see delete btn
s2 = requests.Session()
r2 = s2.post('http://localhost:8080/api/auth/login', json={'username':'TEST','password':'test'}, timeout=10)
user2 = r2.json()['user']
encoded2 = base64.b64encode(json.dumps(user2).encode()).decode()
s2.cookies.set('arxiv_user', encoded2)
r2 = s2.get('http://localhost:8080/all', timeout=10)
t2 = r2.text
has_delete_regular = '\u5220\u9664\u8be5\u6761\u76ee' in t2
print('Regular user sees delete btn in all.html:', has_delete_regular)

print('\n=== DONE ===')
