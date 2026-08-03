"""Flask web app - Paper browser"""

import os, sys

from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, render_template, request, jsonify, send_from_directory

from arxiv_assistant import config, db

import hashlib
import logging
import time as _time
from collections import defaultdict
from logging.handlers import RotatingFileHandler
from werkzeug.exceptions import HTTPException, NotFound, Forbidden

app = Flask(__name__)

app.config["TEMPLATES_AUTO_RELOAD"] = True

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), config.PAPERS_DIR, "_uploads")

os.makedirs(UPLOAD_DIR, exist_ok=True)

# Rotating log (5MB x 5 backups) - prevents unbounded log growth
LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web.log")
_log_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
app.logger.addHandler(_log_handler)
app.logger.setLevel(logging.INFO)

# ---- Error handlers: 404 must not be swallowed as 500 ----
@app.errorhandler(NotFound)
def handle_404(e):
    return "Page not found", 404

@app.errorhandler(Forbidden)
def handle_403(e):
    return "Forbidden", 403

@app.errorhandler(Exception)
def handle_exception(e):
    # HTTPExceptions (400/401/405/...) are handled by Flask normally
    if isinstance(e, HTTPException):
        return e
    import traceback
    app.logger.error("Unhandled exception: %s", traceback.format_exc())
    return "Internal Server Error", 500

# ---- Helpers ----
def get_current_user():
    """Parse arxiv_user cookie -> user dict or None (single shared helper)."""
    try:
        import json as _json, base64 as _b64
        uc = request.cookies.get("arxiv_user", "")
        if uc:
            return _json.loads(_b64.b64decode(uc).decode("utf-8"))
    except Exception:
        pass
    return None

# Simple in-memory rate limit: {key: [timestamps]}, 10 requests / 60s
_rate_limit = defaultdict(list)

def _rate_limit_check(limit_key: str, max_count: int = 10, window: float = 60.0) -> bool:
    now = _time.time()
    _rate_limit[limit_key] = [t for t in _rate_limit[limit_key] if now - t < window]
    if len(_rate_limit[limit_key]) >= max_count:
        return False
    _rate_limit[limit_key].append(now)
    return True

@app.route("/")

def index():

    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))

    sort_by = request.args.get("sort", "rating")

    tag = request.args.get("tag", None)

    src = request.args.get("source", "arxiv")

    if src == "custom":

        papers = db.get_custom_papers()

    elif tag:

        papers = db.get_papers_by_tag(tag)

    else:

        papers = db.get_papers_by_date(date, sort_by=sort_by, source=src)

    papers = [p for p in papers if not p.get("is_hidden")]

    reporter_map = db.get_paper_reporters_map([p["id"] for p in papers])

    for p in papers:

        p["reporters"] = reporter_map.get(p["id"], [])

    # Apply per-user star status
    current_user = get_current_user()
    if current_user and current_user.get("username"):
        star_map = db.get_user_star_map([p["id"] for p in papers], current_user["username"])
        for p in papers:
            p["is_starred"] = star_map.get(p["id"], False)
    return render_template("index.html", papers=papers, date=date, sort_by=sort_by, tag=tag, source=src, today=datetime.now().strftime("%Y-%m-%d"), current_user=current_user)

@app.route("/paper/<int:paper_id>")

def paper_detail(paper_id: int):

    paper = db.get_paper_by_id(paper_id)

    if not paper:

        return render_template("error.html", message="Paper not found"), 404

    paper["reporters"] = db.get_paper_reporters(paper_id)

    # Apply per-user star status

    cu = get_current_user()

    if cu and cu.get("username"):

        star_map = db.get_user_star_map([paper["id"]], cu["username"])

        paper["is_starred"] = star_map.get(paper["id"], False)

    # Log view history if user is logged in

    cu = get_current_user()

    if cu and cu.get("username"):

        db.log_view(paper_id, cu["username"])

    conversations = db.get_conversations(paper_id)

    return render_template("paper.html", paper=paper, conversations=conversations)

@app.route("/search")

def search():

    query = request.args.get("q", "")

    papers = []

    if query:

        papers = db.search_papers(query)

    # Apply per-user star status

    current_user = get_current_user()

    if current_user and current_user.get("username"):

        star_map = db.get_user_star_map([p["id"] for p in papers], current_user["username"])

        for p in papers:

            p["is_starred"] = star_map.get(p["id"], False)

    return render_template("search.html", papers=papers, query=query)

@app.route("/all")

def all_papers():

    page = request.args.get("page", 1, type=int)

    sort_by = request.args.get("sort", "date")

    limit = 50

    offset = (page - 1) * limit

    all_papers = db.get_all_papers(limit=limit, offset=offset, sort_by=sort_by)
    papers = [p for p in all_papers if not p.get("is_hidden")]

    reporter_map = db.get_paper_reporters_map([p["id"] for p in papers])

    for p in papers:

        p["reporters"] = reporter_map.get(p["id"], [])

    # Apply per-user star status
    current_user = get_current_user()
    if current_user and current_user.get("username"):
        star_map = db.get_user_star_map([p["id"] for p in papers], current_user["username"])
        for p in papers:
            p["is_starred"] = star_map.get(p["id"], False)
    return render_template("all.html", papers=papers, page=page, sort_by=sort_by, current_user=current_user)

# ===== API: Upload custom file =====

ALLOWED_EXT = {".pdf", ".docx", ".pptx"}

@app.route("/api/paper/upload", methods=["POST"])

def upload_paper():

    if "file" not in request.files:

        return jsonify({"ok": False, "error": "No file provided"}), 400

    file = request.files["file"]

    title = request.form.get("title", "").strip()

    if not title:

        title = os.path.splitext(file.filename)[0]

    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in ALLOWED_EXT:

        return jsonify({"ok": False, "error": "Unsupported file type. Allowed: PDF, DOCX, PPTX"}), 400

    # Save uploaded file

    import uuid

    safe_name = str(uuid.uuid4()) + ext

    file_path = os.path.join(UPLOAD_DIR, safe_name)

    file.save(file_path)

    # Extract text

    from arxiv_assistant.file_parser import extract_text

    text = extract_text(file_path)

    if not text or len(text) < 50:

        return jsonify({"ok": False, "error": "Could not extract enough text from file"}), 400

    # Extract authors from text

    from arxiv_assistant.file_parser import extract_authors

    authors_str = extract_authors(text)[:200] or "User Upload"

    # For custom uploads, try AI to extract first author institution

    authors_affiliation = ""

    try:

        import config_local, requests

        aff_prompt = "Extract ONLY the first author's affiliation (university/institution, country) from this paper text. Return ONLY the affiliation string, nothing else. If uncertain, return empty string.\n\n" + text[:3000]

        aff_resp = requests.post(config_local.DEEPSEEK_API_URL,

            headers={"Authorization": "Bearer " + config_local.DEEPSEEK_API_KEY, "Content-Type": "application/json"},

            json={"model": config_local.DEEPSEEK_MODEL, "messages": [{"role": "user", "content": aff_prompt}], "temperature": 0.1, "max_tokens": 100},

            timeout=30)

        if aff_resp.ok:

            authors_affiliation = aff_resp.json()["choices"][0]["message"]["content"].strip()[:200]

    except Exception:

        pass

    # Create paper entry

    now_str = datetime.now().strftime("%Y-%m-%d")

    paper = {

        "arxiv_id": "custom-" + str(uuid.uuid4())[:8],

        "title": title,

        "authors": authors_str,

        "affiliations": authors_affiliation,

        "abstract": text[:500],

        "categories": [],

        "published": now_str,

        "pdf_path": file_path,

    }

    # Get uploader from cookie
    _cu = get_current_user()
    paper["uploaded_by"] = _cu.get("username", "") if _cu else ""
    paper_id = db.insert_paper(paper, source="custom")

    if not paper_id:

        return jsonify({"ok": False, "error": "Failed to insert paper"}), 500

    # AI analysis

    from arxiv_assistant import ai_reader

    # If PDF, try to extract figures

    if ext == ".pdf":

        from arxiv_assistant import pdf_parser

        parsed = pdf_parser.parse_pdf(file_path)

        analysis = ai_reader.analyze_paper(parsed.text)

        for fig in parsed.figures:

            db.save_figure(paper_id, fig["figure_number"], fig.get("caption", ""), fig["file_path"])

    else:

        analysis = ai_reader.analyze_paper(text)

    db.save_ai_summary(paper_id, analysis)

    # Auto-trigger detailed analysis for custom uploads

    try:

        paper_obj = db.get_paper_by_id(paper_id)

        if paper_obj and paper_obj.get("pdf_path") and os.path.exists(paper_obj["pdf_path"]):

            _run_detailed_analysis_inner(paper_id, paper_obj)

    except Exception:

        pass

    return jsonify({"ok": True, "paper_id": paper_id, "title": title})

# ===== API: Status & Star =====

@app.route("/api/paper/<int:paper_id>/status", methods=["POST"])

def update_status(paper_id: int):

    data = request.get_json()

    status = data.get("status", "unread")

    db.update_paper_status(paper_id, status)

    return jsonify({"ok": True})

@app.route("/api/paper/<int:paper_id>/star", methods=["POST"])

def toggle_star(paper_id: int):

    data = request.get_json() or {}

    username = data.get("username", "").strip().upper() if data else ""

    new_state = db.toggle_star(paper_id, username if username else None)

    return jsonify({"ok": True, "is_starred": new_state})

# ===== API: Tags =====

@app.route("/api/paper/<int:paper_id>/tags", methods=["GET"])

def get_tags(paper_id: int):

    tags = db.get_tags(paper_id)

    return jsonify({"tags": tags})

@app.route("/api/paper/<int:paper_id>/tags", methods=["POST"])

def add_tag(paper_id: int):

    data = request.get_json()

    tag_name = data.get("tag_name", "").strip()

    if not tag_name:

        return jsonify({"ok": False, "error": "Tag name required"}), 400

    success = db.add_tag(paper_id, tag_name)

    return jsonify({"ok": success, "tag_name": tag_name})

@app.route("/api/paper/<int:paper_id>/tags/<tag_name>", methods=["DELETE"])

def remove_tag(paper_id: int, tag_name: str):

    db.remove_tag(paper_id, tag_name)

    return jsonify({"ok": True})

# ===== API: Ask AI =====

@app.route("/api/paper/<int:paper_id>/ask", methods=["POST"])

def ask_ai(paper_id: int):

    data = request.get_json()

    question = data.get("question", "").strip()

    use_gemini = data.get("use_gemini", False)

    if not question:

        return jsonify({"ok": False, "error": "Question required"}), 400

    paper = db.get_paper_by_id(paper_id)

    if not paper:

        return jsonify({"ok": False, "error": "Paper not found"}), 404

    ctx_parts = []

    if paper.get("title"):

        ctx_parts.append("Title: " + paper["title"])

    if paper.get("abstract"):

        ctx_parts.append("Abstract: " + paper["abstract"][:2000])

    if paper.get("core_problem"):

        ctx_parts.append("Core Problem: " + paper["core_problem"])

    if paper.get("method"):

        ctx_parts.append("Method: " + paper["method"])

    if paper.get("key_results"):

        ctx_parts.append("Key Results: " + paper["key_results"])

    if paper.get("conclusions"):

        ctx_parts.append("Conclusions: " + paper["conclusions"])

    context = "\n\n".join(ctx_parts)

    prompt = ("You are a condensed matter physics research assistant. "

              "Answer the question based on the paper context below.\n\n"

              "{context}\n\nQuestion: {question}\n\nAnswer concisely in Chinese.").format(

                  context=context[:6000], question=question)

    try:

        import config_local

        import requests

        if use_gemini:

            model_used = config_local.GEMINI_MODEL

            headers = {"x-goog-api-key": config_local.GEMINI_API_KEY, "Content-Type": "application/json"}

            payload = {

                "contents": [{"role": "user", "parts": [{"text": prompt}]}],

                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1024},

            }

            resp = requests.post(config_local.GEMINI_API_URL, headers=headers, json=payload, timeout=60)

            resp.raise_for_status()

            answer = resp.json()["candidates"][0]["content"]["parts"][0]["text"]

        else:

            model_used = config_local.DEEPSEEK_MODEL

            headers = {"Authorization": "Bearer {0}".format(config_local.DEEPSEEK_API_KEY), "Content-Type": "application/json"}

            payload = {

                "model": model_used,

                "messages": [{"role": "user", "content": prompt}],

                "temperature": 0.3,

                "max_tokens": 1024,

            }

            resp = requests.post(config_local.DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)

            resp.raise_for_status()

            answer = resp.json()["choices"][0]["message"]["content"]

        db.save_conversation(paper_id, question, answer)

        return jsonify({"ok": True, "answer": answer, "question": question, "model": model_used})

    except Exception as e:

        return jsonify({"ok": False, "error": str(e)}), 500

# ===== API: Conversations =====

@app.route("/api/paper/<int:paper_id>/conversations", methods=["GET"])

def get_conversations(paper_id: int):

    convs = db.get_conversations(paper_id)

    return jsonify({"conversations": convs})

@app.route("/api/conversation/<int:conv_id>", methods=["DELETE"])

def delete_conversation(conv_id: int):

    ok = db.delete_conversation(conv_id)

    return jsonify({"ok": ok})

# ===== Static files =====

# ===== Auth APIs =====

@app.route("/api/users/colors", methods=["GET"])

def get_taken_colors():

    users = db.get_all_users()

    return jsonify({"ok": True, "colors": [u["color"] for u in users]})

@app.route("/api/auth/login", methods=["POST"])

def auth_login():

    if not _rate_limit_check("login:" + (request.remote_addr or "?")):

        return jsonify({"ok": False, "error": "尝试次数过多，请稍后再试"}), 429

    data = request.get_json()

    username = (data.get("username", "") if data else "").strip().upper()

    password = (data.get("password", "") if data else "").strip()

    if not username:

        return jsonify({"ok": False, "error": "\u7528\u6237\u540d\u4e0d\u80fd\u4e3a\u7a7a"}), 400

    user = db.get_user(username)

    if not user:

        return jsonify({"ok": True, "exists": False})

    if not user.get("password_hash"):

        return jsonify({"ok": True, "exists": False, "no_password": True})

    if not password:

        return jsonify({"ok": False, "error": "\u8bf7\u8f93\u5165\u5bc6\u7801"}), 400

    verified = db.verify_user(username, password)

    if verified:

        return jsonify({"ok": True, "exists": True, "user": {"username": user["username"], "color": user["color"], "role": user["role"]}})

    return jsonify({"ok": False, "error": "\u5bc6\u7801\u9519\u8bef"}), 403

@app.route("/api/auth/register", methods=["POST"])

def auth_register():

    if not _rate_limit_check("register:" + (request.remote_addr or "?")):

        return jsonify({"ok": False, "error": "尝试次数过多，请稍后再试"}), 429

    data = request.get_json()

    username = (data.get("username", "") if data else "").strip().upper()

    password = (data.get("password", "") if data else "").strip()

    key = (data.get("key", "") if data else "").strip()

    # Load registration keys from config_local (out of git)
    try:
        import config_local as _cfg
        _cfg_register_key = getattr(_cfg, "REGISTER_KEY", "")
        _cfg_admin_key = getattr(_cfg, "ADMIN_REGISTER_KEY", "")
    except ImportError:
        _cfg_register_key = ""
        _cfg_admin_key = ""

    color = (data.get("color", "#3b82f6") if data else "").strip()

    if not username:

        return jsonify({"ok": False, "error": "\u7528\u6237\u540d\u4e0d\u80fd\u4e3a\u7a7a"}), 400

    if not password:

        return jsonify({"ok": False, "error": "\u8bf7\u8f93\u5165\u5bc6\u7801"}), 400

    if not key:

        return jsonify({"ok": False, "error": "\u8bf7\u8f93\u5165\u5bc6\u94a5"}), 400

    if username == "ADMIN":

        if key != _cfg_admin_key:

            return jsonify({"ok": False, "error": "\u5bc6\u94a5\u9519\u8bef"}), 403

        role = "admin"

        color = color or "#000000"

    else:

        if key != _cfg_register_key:

            return jsonify({"ok": False, "error": "\u5bc6\u94a5\u9519\u8bef"}), 403

        role = "regular"

    pw_hash = hashlib.sha256(password.encode()).hexdigest()

    user = db.get_or_create_user(username, color, role, pw_hash)

    return jsonify({"ok": True, "user": {"username": user["username"], "color": user["color"], "role": user["role"]}})

@app.route("/api/paper/<int:paper_id>/report", methods=["POST"])

def toggle_report(paper_id: int):

    data = request.get_json()

    username = (data.get("username", "") if data else "").strip().upper()

    color = (data.get("color", "#3b82f6") if data else "").strip()

    if not username:

        return jsonify({"ok": False, "error": "\u7528\u6237\u540d\u4e0d\u80fd\u4e3a\u7a7a"}), 400

    result = db.set_paper_report(paper_id, username, color)

    reporters = db.get_paper_reporters(paper_id)

    return jsonify({"ok": True, "added": result, "reporters": reporters, "count": len(reporters)})

@app.route("/api/paper/<int:paper_id>/reporters", methods=["GET"])

def get_reporters(paper_id: int):

    reporters = db.get_paper_reporters(paper_id)

    return jsonify({"reporters": reporters, "count": len(reporters)})

# ===== Admin: Force Refresh =====

import subprocess, threading, os as os_mod

@app.route("/api/admin/refresh", methods=["POST"])

def admin_refresh():

    data = request.get_json()

    username = (data.get("username", "") if data else "").strip().upper()

    user = db.get_user(username)

    if not user or user["role"] != "admin":

        return jsonify({"ok": False, "error": "\u65e0\u6743\u9650"}), 403

    def run_pipeline():

        script = os_mod.path.join(os_mod.path.dirname(os_mod.path.dirname(__file__)), "run_pipeline.py")

        subprocess.run(["python", script], capture_output=True)

    threading.Thread(target=run_pipeline, daemon=True).start()

    return jsonify({"ok": True, "message": "\u5df2\u5f00\u59cb\u66f4\u65b0\uff0c\u8bf7\u7a0d\u540e\u5237\u65b0\u9875\u9762"})

# ===== History API =====

@app.route("/api/history", methods=["GET"])

def get_history():

    _cu = get_current_user()

    if _cu and _cu.get("username"):

        history = db.get_user_history(_cu["username"])

        reporter_map = db.get_paper_reporters_map([p["id"] for p in history if p.get("id")])

        for p in history:

            p["reporters"] = reporter_map.get(p["id"], [])

        return jsonify({"ok": True, "history": history})

    return jsonify({"ok": False, "history": []})

@app.route("/papers/<path:filename>")

def serve_paper_file(filename: str):
    # If env var PAPERS_DIR is set (worktree mode), use it; otherwise use config default
    papers_dir = os.environ.get("PAPERS_DIR") or os.path.join(os.path.dirname(os.path.dirname(__file__)), config.PAPERS_DIR)
    return send_from_directory(papers_dir, filename)

# ===== API: Hide paper (soft delete) =====

@app.route("/api/paper/<int:paper_id>/hide", methods=["POST"])

def hide_paper(paper_id: int):

    _u = get_current_user()
    if not _u or _u.get("role") != "admin":
        return jsonify({"ok": False, "error": "Authentication required"}), 401

    db.hide_paper(paper_id)

    return jsonify({"ok": True})

# ===== Keyword Management APIs =====

@app.route("/my")

def my_papers():

    user = get_current_user()

    if user:

        starred = db.get_starred_papers(username=user.get("username", ""))

        all_tagged = db.get_papers_by_tag("组会报告")

        tagged_report = []

        reporter_map = db.get_paper_reporters_map([p["id"] for p in all_tagged])

        for p in all_tagged:

            p["reporters"] = reporter_map.get(p["id"], [])

            for r in p["reporters"]:

                if r["username"] == user.get("username", ""):

                    tagged_report.append(p)

                    break

        custom = db.get_custom_papers(username=user.get("username", "")) if user.get("username") else []

        try:

            history = db.get_user_history(user.get("username", ""))

        except Exception:

            history = []

    else:

        starred = []

        tagged_report = []

        custom = []

        history = []

    return render_template("my.html", starred=starred, tagged_report=tagged_report, custom=custom, history=history, current_user=user)

@app.route("/api/keywords", methods=["GET"])

def api_get_keywords():

    keywords = db.get_all_keywords()

    return jsonify({"ok": True, "keywords": keywords})

@app.route("/api/keywords/check", methods=["GET"])

def api_check_keyword():

    kw = request.args.get("q", "").strip()

    if not kw:

        return jsonify({"exists": False})

    exists = db.check_keyword_exists(kw)

    return jsonify({"exists": exists})

@app.route("/api/keywords", methods=["POST"])

def api_add_keyword():

    data = request.get_json()

    if not data or not data.get("keyword"):

        return jsonify({"ok": False, "error": "缺少参数"}), 400

    kw = data["keyword"].strip()

    try:

        weight = float(data.get("weight", 1.0))

    except (TypeError, ValueError):

        return jsonify({"ok": False, "error": "权重必须是数字"}), 400

    if weight < 0.1 or weight > 1.2:

        return jsonify({"ok": False, "error": "权重必须在 0.1 ~ 1.2 之间"}), 400

    created_by = data.get("username", "")

    if db.check_keyword_exists(kw):

        return jsonify({"ok": False, "error": "缺少参数"}), 400

    ok = db.add_keyword(kw, weight, created_by)

    return jsonify({"ok": ok})

@app.route("/api/keywords/<int:kw_id>", methods=["PUT"])

def api_update_keyword(kw_id: int):

    data = request.get_json()

    kw = data.get("keyword", "").strip() if data else ""

    try:

        weight = float(data.get("weight", 1.0)) if data else 1.0

    except (TypeError, ValueError):

        return jsonify({"ok": False, "error": "权重必须是数字"}), 400

    if weight < 0.1 or weight > 1.2:

        return jsonify({"ok": False, "error": "权重必须在 0.1 ~ 1.2 之间"}), 400

    ok = db.update_keyword(kw_id, kw or None, weight)

    return jsonify({"ok": ok})

@app.route("/api/keywords/<int:kw_id>", methods=["DELETE"])

def api_delete_keyword(kw_id: int):

    ok = db.delete_keyword(kw_id)

    return jsonify({"ok": ok})

# ===== Detailed Analysis API =====

@app.route("/api/paper/<int:paper_id>/detailed-analysis", methods=["GET"])

def get_detailed_analysis(paper_id: int):

    analysis = db.get_detailed_analysis(paper_id)

    if analysis:

        return jsonify({"ok": True, "analysis": analysis["content"], "created_at": analysis["created_at"]})

    return jsonify({"ok": False, "analysis": None})

import subprocess, threading, os as os_mod

@app.route("/api/paper/<int:paper_id>/detailed-analysis", methods=["POST"])

def generate_detailed_analysis(paper_id: int):

    """API wrapper for detailed analysis"""

    paper = db.get_paper_by_id(paper_id)

    result = _run_detailed_analysis_inner(paper_id, paper)

    if result is None:

        return jsonify({"ok": False, "error": "分析失败"}), 500

    return jsonify({"ok": True, "analysis": result})

def _run_detailed_analysis_inner(paper_id, paper):
    import os
    if not paper or not paper.get("pdf_path") or not os.path.exists(paper["pdf_path"]):
        return None
    import arxiv_assistant.pdf_parser as pdf_parser
    parsed = pdf_parser.parse_pdf(paper["pdf_path"])
    text_excerpt = parsed.text[:10000]
    import config_local, requests
    cfg = config_local
    prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompt for analysis.md")
    with open(prompt_path, "r", encoding="utf-8") as pf:
        prompt_template = pf.read()
    figure_parts = []
    for fig in parsed.figures[:10]:
        fn = fig.get("figure_number", "?")
        cap = (fig.get("caption", "") or "")[:300]
        figure_parts.append("### Figure " + str(fn) + "\uff1a" + cap + "\n")
        figure_parts.append("**\u8be6\u7ec6\u89e3\u8bfb\uff1a**\n")
        figure_parts.append("-\u56fe\u4e2d\u5c55\u793a\u4e86\u4ec0\u4e48\u6570\u636e\uff1f\u5750\u6807\u8f74\u542b\u4e49\uff1f\u5173\u952e\u8d8b\u52bf\u548c\u7279\u5f81\uff1f\n")
        figure_parts.append("-\u8be5\u56fe\u4f7f\u7528\u7684\u5b9e\u9a8c\u624b\u6bb5/\u8ba1\u7b97\u65b9\u6cd5\u662f\u4ec0\u4e48\uff1f\u5173\u952e\u7ed3\u679c\u6709\u54ea\u4e9b\uff1f\n")
        figure_parts.append("-\u7ed3\u5408\u6b63\u6587\uff0c\u8be5\u56fe\u652f\u6491\u4e86\u4f5c\u8005\u7684\u54ea\u4e2a\u8bba\u70b9\uff1f\n")
        figure_parts.append("---\n\n")
    figure_section = "".join(figure_parts) if figure_parts else "\uff08\u672c\u6587\u65e0\u56fe\u8868\u6216\u56fe\u8868\u672a\u63d0\u53d6\u6210\u529f\uff09\n"
    # Build multimodal prompt with text + images
    figure_parts = []
    for fig in parsed.figures[:10]:
        fn = fig.get("figure_number", "?")
        cap = (fig.get("caption", "") or "")[:300]
        figure_parts.append("### Figure " + str(fn) + "\uff1a" + cap + "\n")
    figure_section = "".join(figure_parts) if figure_parts else "\uff08\u672c\u6587\u65e0\u56fe\u8868\u6216\u56fe\u8868\u672a\u63d0\u53d6\u6210\u529f\uff09\n"

    prompt = prompt_template.replace("{FIGURES}", figure_section) + "\n\n## Paper\n\n" + text_excerpt

    try:
        headers = {"x-goog-api-key": cfg.GEMINI_API_KEY, "Content-Type": "application/json"}
        
        # Build parts: text first, then figure images
        parts = [{"text": prompt[:20000]}]
        for fig in parsed.figures[:10]:
            fp = fig.get("file_path", "")
            if not fp or not os.path.exists(fp):
                continue
            fn = fig.get("figure_number", "?")
            cap = (fig.get("caption", "") or "")[:100]
            parts.append({"text": "--- Figure " + str(fn) + ": " + cap + " ---"})
            try:
                with open(fp, "rb") as _f:
                    _data = _f.read()
                _b64 = __import__("base64").b64encode(_data).decode()
                _ext = os.path.splitext(fp)[1].lower()
                _mime = "image/png" if _ext == ".png" else "image/jpeg"
                parts.append({"inline_data": {"mime_type": _mime, "data": _b64}})
            except:
                pass
        
        payload = {"contents": [{"role": "user", "parts": parts}]}
        resp = requests.post(cfg.GEMINI_API_URL, headers=headers, json=payload, timeout=600)
        resp.raise_for_status()
        gemini_result = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        gemini_result = "# 1. Abstract\n(Translation failed)\n\n# 2. Methods\n(N/A)\n\n# 3. Figures\n(N/A)\n\n# 4. Outlook\n(N/A)"

    gemini_result = _strip_bold(gemini_result)

    # Inject figure images into the response HTML for web display
    injected = gemini_result
    for i, fig in enumerate(parsed.figures[:10]):
        fn = fig.get("figure_number", str(i+1))
        img_html = _serve_figure_img(fig)
        if not img_html:
            continue
        markers = ["### Figure " + fn, "### Figure " + str(i+1)]
        for marker in markers:
            idx = injected.find(marker)
            if idx >= 0:
                eol = injected.find(chr(10), idx)
                if eol < 0:
                    eol = len(injected)
                insert_pos = eol + 1
                img_block = chr(10) + chr(10) + img_html + chr(10)
                injected = injected[:insert_pos] + img_block + injected[insert_pos:]
                break

    db.save_detailed_analysis(paper_id, injected)


@app.route("/api/paper/<int:paper_id>/re-extract-figures", methods=["POST"])

def re_extract_figures(paper_id: int):

    """Re-extract figures from PDF, replacing old ones."""

    paper = db.get_paper_by_id(paper_id)

    if not paper:

        return jsonify({"status": "error", "message": "论文不存在"}), 404

    pdf_path = paper.get("pdf_path")

    if not pdf_path or not os.path.exists(pdf_path):

        return jsonify({"status": "error", "message": "PDF 文件不存在"}), 400

    try:

        from arxiv_assistant import pdf_parser

        # Parse PDF to extract figures
        parsed = pdf_parser.parse_pdf(pdf_path)

        # Delete old figure records
        db.delete_figures_by_paper(paper_id)

        # Save new figure records
        for fig in parsed.figures:

            db.save_figure(paper_id, fig["figure_number"], fig.get("caption", ""), fig["file_path"])

        # Build response with new figure data for AJAX refresh
        new_figures = []
        for fig in parsed.figures:
            fp = fig["file_path"]
            # Convert path to URL
            parts = fp.split('papers')
            if len(parts) > 1:
                url_path = '/papers' + parts[1].replace('\\', '/')
            else:
                url_path = '/papers/' + os.path.basename(fp)
            new_figures.append({
                "figure_number": fig["figure_number"],
                "caption": fig.get("caption", ""),
                "src": url_path,
                "width": fig.get("width", 0),
                "height": fig.get("height", 0)
            })

        return jsonify({
            "status": "success",
            "message": "成功重新提取 {0} 张图片".format(len(new_figures)),
            "figures": new_figures
        })

    except Exception as e:

        import traceback

        traceback.print_exc()

        return jsonify({"status": "error", "message": "重新截图失败: " + str(e)}), 500




def _figure_url_path(fp):
    """Convert a figure file path to a /papers/... URL path."""
    fp_norm = fp.replace("\\", "/")
    marker = "/papers/"
    idx = fp_norm.find(marker)
    if idx >= 0:
        return fp_norm[idx:]
    papers_dir = (os.environ.get("PAPERS_DIR") or os.path.join(os.path.dirname(os.path.dirname(__file__)), config.PAPERS_DIR)).replace("\\", "/")
    if fp_norm.startswith(papers_dir):
        return "/papers/" + fp_norm[len(papers_dir):].lstrip("/")
    return "/papers/" + os.path.basename(fp)


def _serve_figure_img(fig):
    fp = fig.get("file_path", "")
    if not fp or not os.path.exists(fp):
        return ""
    try:
        src_url = _figure_url_path(fp)
        return '<img src="' + src_url + '" style="max-width:100%;height:auto;margin:10px 0;border:1px solid #ddd;border-radius:4px;">'
    except:
        return ""

def _clean_output(text):
    import re
    text = text.replace("**", "")
    text = re.sub(r"(?<!\*)\*(?!\*)([^*]+?)(?<!\*)\*(?!\*)", lambda m: m.group(1), text)
    for pat in ["\u6b64\u5904\u5e94\u4e3a[^\u3002\n]*[\u622a\u56fe\n]",
                "\u8bf7\u5728\u6b64\u5904\u63d2\u5165[^\u3002\n]*",
                "\(\u8bf7\u5728\u6b64\u5904\u63d2\u5165[^)]*\)"]:
        text = re.sub(pat, "", text)
    text = re.sub(r"\n\s*-{3,}\s*\n", "\n\n", text)
    text = re.sub(r"^-{3,}\s*\n", "", text)
    text = re.sub(r"\A.*?(?=##\s+\d)", "", text, flags=re.DOTALL)
    text = re.sub(r"\n{4,}", "\n", text)
    text = re.sub(r"  +", " ", text)
    return text.strip()

def _strip_bold(text):
    return _clean_output(text)


@app.context_processor

def inject_globals():

    user = get_current_user()

    return {"now": datetime.now(), "config": config, "current_user": user}

if __name__ == "__main__":

    db.init_db()

    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)
