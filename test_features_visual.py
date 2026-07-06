
import requests, json, base64, re

s = requests.Session()
r = s.post('http://localhost:8080/api/auth/login', json={'username':'TEST','password':'test'}, timeout=10)
user = r.json()['user']
encoded = base64.b64encode(json.dumps(user).encode()).decode()
s.cookies.set('arxiv_user', encoded)

# Home page
r = s.get('http://localhost:8080/', timeout=10)
t = r.text
print('=== HOME PAGE ===')
print('Has today briefing:', '今日简报' in t)
print('Has star icon:', '☆' in t)
print('Has group meeting btn:', '组会报告' in t)
print('Has delete btn:', '删除该条目' in t)
print('Has keywords btn:', '关键词' in t)

# All papers
r = s.get('http://localhost:8080/all', timeout=10)
t = r.text
print('\n=== ALL PAPERS ===')
print('Has sort select:', 'sort' in t)
paper_divs = len(re.findall(r'id="paper-\d+"', t))
print('Paper count:', paper_divs)

# Paper detail
r = s.get('http://localhost:8080/paper/1', timeout=10)
t = r.text
print('\n=== PAPER DETAIL id=1 ===')
print('Has AI analysis:', 'AI分析' in t or 'ai_summary' in t.lower())
print('Has ask AI:', '追问AI' in t)
print('Has detailed analysis btn:', '详细AI分析' in t)
print('Has bubble hint:', '有不懂' in t)
print('Has figures or images:', 'figure' in t.lower() or '.png' in t or '.jpg' in t)
print('Has report dot:', 'report-dot' in t)
print('Has delete btn in detail:', '删除该条目' in t)

# My page
r = s.get('http://localhost:8080/my', timeout=10)
t = r.text
print('\n=== MY PAGE ===')
print('Has menu items:', '收藏' in t, '组会' in t, '自行添加' in t, '历史' in t)

# Search
r = s.get('http://localhost:8080/search?q=quantum', timeout=10)
print('\n=== SEARCH ===')
print('Search status:', r.status_code)

# Test star in detail page
r = s.post('http://localhost:8080/api/paper/1/star', json={'username':'TEST'}, timeout=10)
print('\nStar toggle on detail:', r.json())

# Test detailed analysis
r = s.get('http://localhost:8080/api/paper/1/detailed-analysis', timeout=10)
print('Detailed analysis GET (existing):', r.status_code)

# Test add keyword as regular user  
r = s.post('http://localhost:8080/api/keywords/add', json={'keyword':'test_kw','weight':1.0,'username':'TEST'}, timeout=10)
print('Add keyword (regular):', r.status_code, r.json() if r.headers.get('content-type','').startswith('application/json') else r.text[:100])

print('\n=== VISUAL TESTS DONE ===')
