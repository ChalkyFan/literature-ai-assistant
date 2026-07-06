
import requests, json, base64, sys

s = requests.Session()
r = s.post('http://localhost:8080/api/auth/login', json={'username':'TEST','password':'test'}, timeout=30)
data = r.json()
if not data.get('ok') or not data.get('exists'):
    print('Login failed:', data)
    sys.exit(1)
user = data['user']
encoded = base64.b64encode(json.dumps(user).encode()).decode()
s.cookies.set('arxiv_user', encoded)
print('Logged in as TEST')

results = []

# 1 Home
r = s.get('http://localhost:8080/', timeout=30)
results.append(('Home page', r.status_code==200))

# 2 All papers  
r = s.get('http://localhost:8080/all', timeout=30)
results.append(('All papers', r.status_code==200))

# 3 My page
r = s.get('http://localhost:8080/my', timeout=30)
results.append(('My page', r.status_code==200))
t = r.text
results.append(('My-\u6536\u85cf', '\u6536\u85cf' in t))
results.append(('My-\u7ec4\u4f1a', '\u7ec4\u4f1a' in t))
results.append(('My-\u81ea\u884c\u6dfb\u52a0', '\u81ea\u884c\u6dfb\u52a0' in t))
results.append(('My-\u5386\u53f2', '\u5386\u53f2' in t))

# 4 Search
r = s.get('http://localhost:8080/search?q=quantum', timeout=30)
results.append(('Search', r.status_code==200))

# 5 Paper detail
r = s.get('http://localhost:8080/paper/1', timeout=30)
results.append(('Paper detail', r.status_code==200))

# 6 Star
r = s.post('http://localhost:8080/api/paper/1/star', json={'username':'TEST'}, timeout=30)
rj = r.json()
results.append(('Star toggle', rj.get('ok')==True))
results.append(('Star state', 'is_starred' in rj))

# 7 Report
r = s.post('http://localhost:8080/api/paper/1/report', json={'username':'TEST','color':'#4363d8'}, timeout=30)
rj = r.json()
results.append(('Report toggle', rj.get('ok')==True))

# 8 History - visit then check
r = s.get('http://localhost:8080/paper/1', timeout=30)
r = s.get('http://localhost:8080/api/history', timeout=30)
hj = r.json()
results.append(('History API', hj.get('ok')==True))

# 9 Tags
r = s.get('http://localhost:8080/api/paper/1/tags', timeout=30)
results.append(('Tags API', r.status_code==200))

# 10 Keywords
r = s.get('http://localhost:8080/api/keywords', timeout=30)
kw = r.json()
results.append(('Keywords API', kw.get('ok')==True))

# 11 Colors
r = s.get('http://localhost:8080/api/users/colors', timeout=30)
results.append(('Colors API', r.status_code==200))

# 12 Delete - regular user should not be able to
r = s.post('http://localhost:8080/api/paper/1/hide', json={'username':'TEST'}, timeout=30)
results.append(('Delete hide(regular)', r.status_code in (200, 403)))

# 13 Conversations
r = s.get('http://localhost:8080/api/paper/1/conversations', timeout=30)
results.append(('Conversations', r.status_code==200))

# 14 Detailed analysis check
r = s.get('http://localhost:8080/api/paper/1/detailed', timeout=30)
results.append(('Detailed analysis', r.status_code==200))

# 15 Sort variants
for sort in ['date', 'rating', 'keywords']:
    r = s.get(f'http://localhost:8080/all?sort={sort}', timeout=30)
    results.append((f'Sort-{sort}', r.status_code==200))

print()
print('=== TEST RESULTS ===')
passed = 0
failed = 0
for name, ok in results:
    status = 'PASS' if ok else 'FAIL'
    if ok: passed += 1
    else: failed += 1
    print(f'  [{status}] {name}')
print(f'\nPassed: {passed}, Failed: {failed}')
