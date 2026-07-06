"""Flask web app - Paper browser"""

import os, sys

from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, render_template, request, jsonify, send_from_directory

from arxiv_assistant import config, db

import hashlib

app = Flask(__name__)

app.config["TEMPLATES_AUTO_RELOAD"] = True

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), config.PAPERS_DIR, "_uploads")

os.makedirs(UPLOAD_DIR, exist_ok=True)

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

    for p in papers:

        p["reporters"] = db.get_paper_reporters(p["id"])

    # Apply per-user star status
    current_user = None
    try:
        import json as _json, base64 as _b64
        uc = request.cookies.get("arxiv_user", "")
        if uc:
            u = _json.loads(_b64.b64decode(uc).decode("utf-8"))
            current_user = u
            if u.get("username"):
                star_map = db.get_user_star_map([p["id"] for p in papers], u["username"])
                for p in papers:
                    p["is_starred"] = star_map.get(p["id"], False)
    except Exception:
        pass
    return render_template("index.html", papers=papers, date=date, sort_by=sort_by, tag=tag, source=src, today=datetime.now().strftime("%Y-%m-%d"), current_user=current_user)

@app.route("/paper/<int:paper_id>")

def paper_detail(paper_id: int):

    paper = db.get_paper_by_id(paper_id)

    if not paper:

        return render_template("error.html", message="Paper not found"), 404

    paper["reporters"] = db.get_paper_reporters(paper_id)

    # Apply per-user star status

    try:

        import json as _json, base64 as _b64

        uc = request.cookies.get("arxiv_user", "")

        if uc:

            u = _json.loads(_b64.b64decode(uc).decode("utf-8"))

            if u.get("username"):

                star_map = db.get_user_star_map([paper["id"]], u["username"])

                paper["is_starred"] = star_map.get(paper["id"], False)

    except Exception:

        pass

    # Log view history if user is logged in

    try:

        import json as _json, base64 as _b64

        uc = request.cookies.get("arxiv_user", "")

        if uc:

            u = _json.loads(_b64.b64decode(uc).decode("utf-8"))

            if u.get("username"):

                db.log_view(paper_id, u["username"])

    except Exception:

        pass

    conversations = db.get_conversations(paper_id)

    return render_template("paper.html", paper=paper, conversations=conversations)

@app.route("/search")

def search():

    query = request.args.get("q", "")

    papers = []

    if query:

        papers = db.search_papers(query)

    # Apply per-user star status

    try:

        import json as _json, base64 as _b64

        uc = request.cookies.get("arxiv_user", "")

        if uc:

            u = _json.loads(_b64.b64decode(uc).decode("utf-8"))

            if u.get("username"):

                star_map = db.get_user_star_map([p["id"] for p in papers], u["username"])

                for p in papers:

                    p["is_starred"] = star_map.get(p["id"], False)

    except Exception:

        pass

    return render_template("search.html", papers=papers, query=query)

@app.route("/all")

def all_papers():

    page = request.args.get("page", 1, type=int)

    sort_by = request.args.get("sort", "date")

    limit = 50

    offset = (page - 1) * limit

    all_papers = db.get_all_papers(limit=limit, offset=offset)

    # Sort in-memory

    if sort_by == "rating":

        all_papers.sort(key=lambda p: p.get("value_rating") or 0, reverse=True)

    elif sort_by == "keywords":

        kw_map = db.get_keyword_counts([p["id"] for p in all_papers if p.get("id")])

        all_papers.sort(key=lambda p: kw_map.get(p["id"], 0), reverse=True)

    papers = [p for p in all_papers if not p.get("is_hidden")]

    for p in papers:

        p["reporters"] = db.get_paper_reporters(p["id"])

    # Apply per-user star status
    current_user = None
    try:
        import json as _json, base64 as _b64
        uc = request.cookies.get("arxiv_user", "")
        if uc:
            u = _json.loads(_b64.b64decode(uc).decode("utf-8"))
            current_user = u
            if u.get("username"):
                star_map = db.get_user_star_map([p["id"] for p in papers], u["username"])
                for p in papers:
                    p["is_starred"] = star_map.get(p["id"], False)
    except Exception:
        pass
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
    try:
        import json as _json, base64 as _b64
        uc = request.cookies.get("arxiv_user", "")
        if uc:
            uu = _json.loads(_b64.b64decode(uc).decode("utf-8"))
            paper["uploaded_by"] = uu.get("username", "")
        else:
            paper["uploaded_by"] = ""
    except Exception:
        paper["uploaded_by"] = ""
    paper_id = db.insert_paper(paper, source="custom")

    if not paper_id:

        return jsonify({"ok": False, "error": "Failed to insert paper"}), 500

    # AI analysis

    from arxiv_assistant import ai_reader

    analysis = ai_reader.analyze_paper(text)

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

        headers = {"Authorization": "Bearer {0}".format(config_local.DEEPSEEK_API_KEY), "Content-Type": "application/json"}

        payload = {

            "model": config_local.DEEPSEEK_MODEL,

            "messages": [{"role": "user", "content": prompt}],

            "temperature": 0.3,

            "max_tokens": 1024,

        }

        resp = requests.post(config_local.DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)

        resp.raise_for_status()

        answer = resp.json()["choices"][0]["message"]["content"]

        db.save_conversation(paper_id, question, answer)

        return jsonify({"ok": True, "answer": answer, "question": question})

    except Exception as e:

        return None

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

    try:

        import json as _json, base64 as _b64

        uc = request.cookies.get("arxiv_user", "")

        if uc:

            u = _json.loads(_b64.b64decode(uc).decode("utf-8"))

            if u.get("username"):

                history = db.get_user_history(u["username"])

                for p in history:

                    try:

                        p["reporters"] = db.get_paper_reporters(p["id"])

                    except Exception:

                        p["reporters"] = []

                return jsonify({"ok": True, "history": history})

    except Exception:

        pass

    return jsonify({"ok": False, "history": []})

@app.route("/papers/<path:filename>")

def serve_paper_file(filename: str):

    papers_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), config.PAPERS_DIR)

    return send_from_directory(papers_dir, filename)

# ===== API: Hide paper (soft delete) =====

@app.route("/api/paper/<int:paper_id>/hide", methods=["POST"])

def hide_paper(paper_id: int):

    import json as _j, base64 as _b64
    try:
        uc = request.cookies.get("arxiv_user", "")
        if uc:
            u = _j.loads(_b64.b64decode(uc).decode("utf-8"))
            if u.get("role") != "admin":
                return jsonify({"ok": False, "error": "Only admin can delete entries"}), 403
    except Exception:
        return jsonify({"ok": False, "error": "Authentication required"}), 401

    db.hide_paper(paper_id)

    return jsonify({"ok": True})

# ===== Keyword Management APIs =====

@app.route("/my")

def my_papers():

    user = None

    try:

        import json as _json, base64 as _b64

        user_cookie = request.cookies.get("arxiv_user", "")

        if user_cookie:

            user = _json.loads(_b64.b64decode(user_cookie).decode("utf-8"))

    except Exception:

        pass

    if user:

        starred = db.get_starred_papers(username=user.get("username", ""))

        all_tagged = db.get_papers_by_tag("组会报告")

        tagged_report = []

        for p in all_tagged:

            reporters = db.get_paper_reporters(p["id"])

            p["reporters"] = reporters

            for r in reporters:

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

    weight = float(data.get("weight", 1.0))

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

    weight = float(data.get("weight", 1.0)) if data else 1.0

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

    """内部详细分析函数，返回分析内容或 None"""

    if not paper or not paper.get("pdf_path") or not os.path.exists(paper["pdf_path"]):

        return None

    import arxiv_assistant.pdf_parser as pdf_parser

    parsed = pdf_parser.parse_pdf(paper["pdf_path"])

    import config_local

    import requests

    cfg = config_local

    api_key = cfg.DEEPSEEK_API_KEY

    api_url = cfg.DEEPSEEK_API_URL

    model_name = cfg.DEEPSEEK_MODEL

    text_excerpt = parsed.text[:8000]

    figure_desc = ""

    for fig in parsed.figures[:10]:

        cap = fig.get("caption", "")[:200]

        fnum = fig.get("figure_number", "?")

        figure_desc += "Figure " + str(fnum) + ": " + cap + "\n"

    prompt = "你是凝聚态物理领域的AI研究助手。请对这篇论文进行详细分析，输出中文。\n\n"

    prompt += "论文文本开头部分：\n" + text_excerpt + "\n\n"

    prompt += "论文包含以下图表（图注）：\n" + figure_desc + "\n\n"

    prompt += "请按以下格式输出：\n\n"

    prompt += "## 1. 摘要翻译\n[将论文摘要翻译为中文]\n\n"

    prompt += "## 2. 图表详细解读\n[按从上到下的顺序，结合图注和文章内容，详细解读每个图表的内容和意义]\n\n"

    prompt += "## 3. 研究方法总结\n[总结文章的主要研究方法]\n\n"

    prompt += "## 4. 主要结论\n[总结文章的核心结论]"

    try:

        payload = {"model": model_name, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 4000}

        headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}

        resp = requests.post(api_url, headers=headers, json=payload, timeout=120)

        resp.raise_for_status()

        analysis_content = resp.json()["choices"][0]["message"]["content"]

    except Exception as e:

        return None

    db.save_detailed_analysis(paper_id, analysis_content)

    return analysis_content

@app.context_processor

def inject_globals():

    user = None

    try:

        import hashlib as _json

        user_cookie = request.cookies.get("arxiv_user", "")

        if user_cookie:

            import base64 as _b64

            user = _json.loads(_b64.b64decode(user_cookie).decode("utf-8"))

    except Exception:

        pass

    return {"now": datetime.now(), "config": config, "current_user": user}

if __name__ == "__main__":

    db.init_db()

    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False)
