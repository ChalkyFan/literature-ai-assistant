# 文献AI助手 Web 改进任务清单

> 本清单由代码审查生成，供开发执行。
> **已排除项**：认证机制重构、密码哈希升级、BibTeX 导出、功能增强候选。
> **执行顺序建议**：先修 Bug（一、1-4），再做性能优化（二、5-9），然后模板修复（三、10），最后清理（四、11-17）。

---

## 一、Bug 修复

### 1. 所有 404 被吞成 500
- **文件**：`run_web_locked.py`
- **问题**：`@app.errorhandler(Exception)` 捕获所有异常，包括 werkzeug 的 `NotFound`，导致访问不存在的页面返回 "Internal Server Error"（web_app.log 中大量此类记录）。
- **修复**：
  ```python
  from werkzeug.exceptions import NotFound, Forbidden

  @app.errorhandler(NotFound)
  def handle_404(e):
      return "Page not found", 404

  @app.errorhandler(Exception)
  def handle_exception(e):
      logger.error("Unhandled exception: %s", traceback.format_exc())
      return "Internal Server Error", 500
  ```

### 2. inject_globals() 的 current_user 永远是 None
- **文件**：`web/app.py` 末尾 `inject_globals()` 函数
- **问题**：`import hashlib as _json` 后调用 `_json.loads(...)`，hashlib 没有 `loads` 方法，异常被 except 吞掉，`current_user` 恒为 None。导致模板中 `{% if current_user and current_user.role == "admin" %}` 永远不成立，服务端渲染的删除按钮等逻辑失效。
- **修复**：把 `import hashlib as _json` 改为 `import json as _json`。

### 3. 上传 PDF 时 AI 分析调用两次
- **文件**：`web/app.py`，`upload_paper()` 函数
- **问题**：函数开头先调用一次 `analysis = ai_reader.analyze_paper(text)`，随后 `if ext == ".pdf"` 分支里解析 PDF 后又调用 `analysis = ai_reader.analyze_paper(parsed.text)`（`else` 分支再调一次）。PDF 上传时同一篇论文被分析两次，浪费 API 费用和时间。
- **修复**：删除函数开头那次调用。PDF 分支用 `parsed.text` 分析，非 PDF 分支用原始 `text` 分析，各只调用一次。

### 4. /api/keywords 的 float() 无异常处理
- **文件**：`web/app.py`，`api_add_keyword()` 和 `api_update_keyword()`
- **问题**：`weight = float(data.get("weight", 1.0))`，传入非数字字符串时抛 ValueError，未捕获返回 500。
- **修复**：
  ```python
  try:
      weight = float(data.get("weight", 1.0))
  except (TypeError, ValueError):
      return jsonify({"ok": False, "error": "权重必须是数字"}), 400
  ```

---

## 二、性能优化

### 5. N+1 查询：列表页逐篇查 reporters
- **文件**：`web/app.py` 的 `index()` / `all_papers()` / `search()`；`arxiv_assistant/db.py`
- **问题**：`for p in papers: p["reporters"] = db.get_paper_reporters(p["id"])`，每页 50 篇 = 51 条 SQL。
- **修复**：在 `db.py` 新增批量查询函数：
  ```python
  def get_paper_reporters_map(paper_ids):
      """返回 {paper_id: [reporter dicts]}，一次查询全部。"""
      if not paper_ids:
          return {}
      conn = get_connection()
      try:
          placeholders = ",".join("?" * len(paper_ids))
          rows = conn.execute(
              "SELECT paper_id, username, color FROM paper_reporters WHERE paper_id IN (" + placeholders + ")",
              paper_ids
          ).fetchall()
          result = {}
          for r in rows:
              result.setdefault(r["paper_id"], []).append({"username": r["username"], "color": r["color"]})
          return result
      finally:
          conn.close()
  ```
  页面代码改为：
  ```python
  reporter_map = db.get_paper_reporters_map([p["id"] for p in papers])
  for p in papers:
      p["reporters"] = reporter_map.get(p["id"], [])
  ```

### 6. /all 排序只排当前页
- **文件**：`web/app.py`，`all_papers()`
- **问题**：先 `LIMIT 50 OFFSET` 取一页，再在内存里排序，导致按评分/关键词排序时只排了当前页 50 篇，跨页排序结果错误。
- **修复**：把排序条件放进 SQL（参考 `get_papers_by_date` 的 order_clause 写法），或先取全部符合条件的论文 id 排序后再分页取数。

### 7. 详细分析把图片 base64 内嵌进 HTML
- **文件**：`web/app.py`，`_run_detailed_analysis_inner()` 和 `_serve_figure_img()`
- **问题**：每张图 base64 内嵌到分析结果 HTML，单页可达数 MB，拖慢加载。
- **修复**：改为 `<img src="/papers/...">` 引用文件路径（从 file_path 中提取相对 papers 目录的部分），或新增一个 `/api/paper/<id>/figures/<n>` 图片接口。

### 8. 时区不一致
- **文件**：`arxiv_assistant/db.py`（fetched_date 默认值）、`web/app.py` 的 `index()`、`run_pipeline.py` / `arxiv_assistant/pipeline_runner.py`
- **问题**：`fetched_date` 存 UTC（`datetime('now')`），网页"今日"用北京时间 `datetime.now().strftime(...)`，pipeline 生成报告用 UTC 日期。凌晨时段（00:00-08:00 北京）日期可能错位，导致当天论文显示不出来。
- **修复**：统一用本地时间：`fetched_date` 默认值改为 `datetime('now', 'localtime')`；报告生成也用本地 `datetime.now()`，去掉 `timezone.utc`。

### 9. 无 CSRF / 无限流
- **文件**：`web/app.py`（所有 POST 接口）
- **问题**：POST API 无 CSRF 防护；登录/注册/ask 接口无速率限制。
- **修复**（最小改动）：引入 `flask_wtf.csrf.CSRFProtect`（或自定义简单 token 校验）；对 `/api/auth/login`、`/api/auth/register` 做简单 IP 频率限制（如内存 dict 计数，1 分钟 10 次）。

---

## 三、模板修复

### 10. all.html 模板结构损坏 + JS 重复
- **文件**：`web/templates/all.html`
- **问题**：`{% block title %}` 里嵌入了 `<script>function toggleStar(...)</script>`（会导致 title 输出异常）；且整个文件里 `toggleStar` 定义了 3 次（重复代码）。
- **修复**：把 title block 恢复为纯标题；删除重复的 script 块只保留一个；把 `toggleStar` 抽到 `base.html` 或公共 JS 文件，供各页面复用。

---

## 四、架构与清理

### 11. 认证解析代码重复约 10 次
- **文件**：`web/app.py`
- **问题**：base64 cookie 解析的 try/except 代码块在多个路由中重复出现（约 10 次）。
- **修复**：抽取 `get_current_user()` 辅助函数统一复用（仅做代码复用，不改动认证机制本身）。

### 12. 死代码 / 垃圾文件
- **文件**：项目根目录
- **问题**：`fix_runner.py`（仅 4 字节）、`pdf_parser.py.bak`、`temp_fix.py`、`_fetcher_replacement.py`、`test_bugs.py` / `test_delete_fix.py` / `test_features.py` / `test_features_visual.py`（非 pytest 规范的临时测试）、`gemini_result_p16.txt`、`web/templates/all.html.bak`。
- **修复**：确认无用后删除，或统一移到 `archive/` 目录。

### 13. requirements.txt 与代码依赖不符
- **文件**：`requirements.txt`、`arxiv_assistant/file_parser.py`
- **问题**：代码用到 `python-docx`、`python-pptx`，但 requirements.txt 只有 flask / PyMuPDF / arxiv / requests / pillow。
- **修复**：补上 `python-docx>=1.0`、`python-pptx>=0.6.21`，并用 `pip freeze` 核对其他遗漏。

### 14. 日志无限增长，无轮转
- **文件**：`run_web_locked.py`、`run_pipeline.py`
- **问题**：`web_app.log` 已 1.2MB、`pipeline.log` 1.5MB、`daily_monitor.log` 130KB，无 rotation。
- **修复**：改用 `logging.handlers.RotatingFileHandler(maxBytes=5MB, backupCount=5)`。

### 15. 数据库无迁移机制
- **文件**：`arxiv_assistant/db.py` 的 `init_db()`
- **问题**：用多个 `ALTER TABLE ... try/except` 硬迁移，新表靠 executescript 拼接，长期维护容易乱。
- **修复**（低成本方案）：加 `schema_version` 表 + 按版本号执行的迁移列表，把现有 ALTER 收敛到迁移函数中。

### 16. web/ 与 web_dev/ 近重复
- **文件**：`web/app.py`、`web_dev/app.py`
- **问题**：两份高度相似的 Flask app，维护时容易改一个忘一个。
- **修复**：确认 web_dev 是否仍在使用；若不再使用则删除，若仍使用则把公共逻辑（db 访问、AI 调用）抽到 `arxiv_assistant/` 共享模块。

### 17. fetcher 用 HTML 爬虫，脆弱
- **文件**：`arxiv_assistant/fetcher.py`
- **问题**：用正则解析 arxiv listing/abs HTML 页面，arXiv 改版即挂；`requirements.txt` 里有 `arxiv` 包但未使用；日志中已出现 arxiv.org 超时告警。
- **修复**：改用 arxiv API 包（`import arxiv`）作为主路径，保留现有 HTML 爬虫作为 fallback。

---

## 验收标准

- [ ] 访问不存在的页面返回 404 而非 500
- [ ] 模板中 `current_user` 能正确取到登录用户（admin 可见删除按钮）
- [ ] 上传 PDF 时 AI 分析只调用一次
- [ ] 传入非法 weight 返回 400 而非 500
- [ ] 列表页 SQL 数量从 N+1 降到 2-3 条
- [ ] `/all` 按评分排序跨页正确
- [ ] 论文详情页 HTML 大小显著下降（无 base64 图片）
- [ ] 凌晨时段也能正确显示当天论文
- [ ] `all.html` 无重复 JS，title 正常显示
- [ ] 日志文件有轮转机制
- [ ] 依赖清单与实际 import 一致
