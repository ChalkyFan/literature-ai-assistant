
import requests, json, base64

s = requests.Session()
r = s.post('http://localhost:8080/api/auth/login', json={'username':'TEST','password':'test'}, timeout=30)
user = r.json()['user']
encoded = base64.b64encode(json.dumps(user).encode()).decode()
s.cookies.set('arxiv_user', encoded)
print('Logged in as TEST')

# Test star
r = s.post('http://localhost:8080/api/paper/1/star', json={'username':'TEST'}, timeout=30)
print('Star:', r.json().get('ok'))

# Test report
r = s.post('http://localhost:8080/api/paper/1/report', json={'username':'TEST','color':'#4363d8'}, timeout=30)
print('Report:', r.json().get('ok'))

# Test history
r = s.get('http://localhost:8080/paper/1', timeout=30)
print('Detail page:', r.status_code)

r = s.get('http://localhost:8080/api/history', timeout=30)
hj = r.json()
print('History ok:', hj.get('ok'), 'count:', len(hj.get('history',[])))

# Test regular user delete (should fail/403)
r = s.post('http://localhost:8080/api/paper/1/hide', json={'username':'TEST'}, timeout=30)
print('Regular delete:', r.status_code, 'ok:', r.json().get('ok'))

# Test my page
r = s.get('http://localhost:8080/my', timeout=30)
t = r.text
print('My page status:', r.status_code)
print('Has TEST:', 'TEST' in t)
print('Has ??:', '\u6536\u85cf' in t)
print('Has ??:', '\u7ec4\u4f1a' in t)
print('Has ????:', '\u81ea\u884c\u6dfb\u52a0' in t)
print('Has ????:', '\u5386\u53f2' in t)

# Test all papers
r = s.get('http://localhost:8080/all', timeout=30)
print('All papers:', r.status_code, 'len:', len(r.text))
print('Has paper links:', '/paper/' in r.text)

print('\n=== ALL TESTS DONE ===')
