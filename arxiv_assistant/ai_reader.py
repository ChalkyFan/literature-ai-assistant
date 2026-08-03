import json, logging, os, re, base64, sys, requests
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

def _load_deepseek_config() -> Optional[Dict]:
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import config_local
        api_key = getattr(config_local, "DEEPSEEK_API_KEY", "")
        api_url = getattr(config_local, "DEEPSEEK_API_URL", "")
        model = getattr(config_local, "DEEPSEEK_MODEL", "deepseek-v4")
        if api_key and api_url:
            return {"api_key": api_key, "api_url": api_url, "model": model}
    except ImportError:
        pass
    return None

def analyze_paper(paper_text: str, figures: list = None) -> Dict:
    config = _load_deepseek_config()
    if not config:
        logger.warning("DeepSeek API not configured, returning mock analysis")
        return _mock_analysis(paper_text)
    logger.info("Calling {0} for paper analysis...".format(config["model"]))
    return _call_deepseek_api(paper_text, figures, config)

def _build_analysis_prompt(paper_text: str) -> str:
    text = paper_text[:8000]
    return (
        'You are a senior condensed matter physics (experimental) researcher. '
        'Read the paper below and return your analysis as JSON only.\n\n'
        'Paper text:\n{text}\n\n'
        'Return JSON with this structure (no other text):\n'
        '{{\n'
        '    "core_problem": "Describe in Chinese: what scientific problem does this paper address?",\n'
        '    "method": "Describe in Chinese: what experimental or theoretical methods were used?",\n'
        '    "key_results": "Describe in Chinese: key results and findings (be specific with numbers).",\n'
        '    "conclusions": "Describe in Chinese: main conclusions of the authors.",\n'
        '    "limitations": "Describe in Chinese: limitations or open questions.",\n'
        '    "value_rating": integer 1-5 rating of relevance to strongly correlated electron physics,\n'
        '    "one_line_value": "Keep in English: one sentence summary of why this paper matters."\n'
        '}}'
    ).format(text=text)

def _call_deepseek_api(paper_text: str, figures: list, config: Dict) -> Dict:
    prompt = _build_analysis_prompt(paper_text)
    messages = [{"role": "user", "content": prompt}]
    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": 1,
        "max_tokens": 2048,
    }
    headers = {
        "Authorization": "Bearer {0}".format(config["api_key"]),
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(config["api_url"], headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            result["full_analysis"] = content
            return result
        return _mock_analysis(paper_text)
    except Exception as e:
        logger.error("DeepSeek API call failed: {0}".format(e))
        return _mock_analysis(paper_text)

def _mock_analysis(paper_text: str) -> Dict:
    return {
        "core_problem": "(请配置 DeepSeek API key 后使用真实分析)",
        "method": "(请配置 DeepSeek API key 后使用真实分析)",
        "key_results": "(请配置 DeepSeek API key 后使用真实分析)",
        "conclusions": "(请配置 DeepSeek API key 后使用真实分析)",
        "limitations": "(请配置 DeepSeek API key 后使用真实分析)",
        "value_rating": 3,
        "one_line_value": "(Configure DeepSeek API key for real analysis)",
    }

# ===== Gemini 3 Flash Figure Caption Classification =====

def _load_gemini_config() -> Optional[Dict]:
    """Load Gemini API config from config_local.py"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import config_local
        api_key = getattr(config_local, "GEMINI_API_KEY", "")
        api_url = getattr(config_local, "GEMINI_API_URL", "")
        model = getattr(config_local, "GEMINI_MODEL", "gemini-3-flash")
        enabled = getattr(config_local, "GEMINI_FILTER_ENABLED", True)
        if api_key and api_url and enabled:
            return {"api_key": api_key, "api_url": api_url, "model": model}
    except ImportError:
        pass
    return None

def gemini_classify_captions(page_b64: str, candidates_text: str, api_config: Dict) -> Optional[Dict]:
    """Send page screenshot + candidate texts to Gemini 3 Flash for classification."""
    prompt = (
        "You are a physics paper layout expert. Classify each line as "
        '"caption" (standalone figure label) or "reference" (embedded paragraph text).\n\n'
        "Candidates:\n{candidates}\n\n"
        'Respond ONLY with JSON:\n'
        '{{"results": [{{"fig": "1", "type": "caption"}}, {{"fig": "2", "type": "reference"}}]}}'
    ).format(candidates=candidates_text)

    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/png", "data": page_b64}}
            ]
        }]
    }
    headers = {
        "x-goog-api-key": api_config["api_key"],
        "Content-Type": "application/json"
    }
    try:
        resp = requests.post(api_config["api_url"], headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        content = (data.get("candidates", [{}])[0]
                      .get("content", {})
                      .get("parts", [{}])[0]
                      .get("text", ""))
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            logger.info("Gemini classification: {0}".format(result))
            return result
        logger.warning("Gemini response had no JSON: {0}".format(content[:200]))
    except Exception as e:
        logger.warning("Gemini API call failed: {0}".format(e))
    return None

def heuristic_classify_captions(candidates: List[Dict], page_text: str) -> List[Dict]:
    """Fallback: classify caption candidates using heuristic verb-list rules."""
    reference_verbs = [
        "shows", "demonstrates", "illustrates", "presents", "depicts",
        "displays", "reports", "summarizes", "compares", "outlines",
        "plots", "graphs", "sketches", "represents", "highlights",
        "reveals", "describes", "indicates", "provides", "gives",
    ]
    results = []
    for c in candidates:
        text = c.get("text", "")
        is_ref = False
        for v in reference_verbs:
            if re.search(r"\b" + v + r"\b", text, re.IGNORECASE):
                is_ref = True
                break
        if re.search(r"\b(as\s+(shown|seen|displayed|presented|illustrated|demonstrated)\s+(in|by))\b", text, re.IGNORECASE):
            is_ref = True
        if re.search(r"\b(Fig|Figure|FIGS?)\s+[S0-9]", text):
            is_ref = True
        results.append({**c, "type": "reference" if is_ref else "caption"})
    return results


# ===== Kimi K2.6 vision + Gemini paper analysis (preserved from production) =====

def _load_kimi_config() -> Optional[Dict]:
    """Load Kimi K2.6 API config from config_local."""
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        import config_local
        api_key = getattr(config_local, 'KIMI_API_KEY', '')
        api_url = getattr(config_local, 'KIMI_API_URL', '')
        model = getattr(config_local, 'KIMI_MODEL', 'kimi-k2.6')
        vision_model = getattr(config_local, 'KIMI_VISION_MODEL', 'moonshot-v1-128k-vision-preview')
        if api_key and api_url and api_key != 'YOUR_KIMI_API_KEY_HERE':
            return {'api_key': api_key, 'api_url': api_url, 'model': model, 'vision_model': vision_model}
    except ImportError:
        pass
    return None


def kimi_analyze_figures(figures: list) -> str:
    """Analyze figure images using Kimi K2.6 vision API.
    Figures: list of dicts with 'file_path' and 'caption'.
    Returns markdown-formatted figure analysis text.
    """
    config = _load_kimi_config()
    if not config:
        logger.warning('Kimi API not configured, skipping figure analysis')
        return '(Kimi API 未配置，跳过图表分析)'

    import requests
    import base64

    # Build multimodal message content with all figures
    content_parts = [{'type': 'text', 'text': '你是凝聚态物理专业的高级AI研究助手。擅长分析论文图表。请仔细观察每张图表，用自然语言描述你所看到的内容，包括但不限于：图表类型和结构、标注的文字符号、坐标轴刻度、能带/峰值/对称性等关键特征、实验条件或参数，以及这张图给你的核心物理信息。请对每张图分别用中文描述，按图表编号分条阐述，不要套用固定模板。'}]

    # Add figure captions and images (up to 10 figures, max 5MB total)
    total_size = 0
    for fig in figures[:10]:
        fpath = fig.get('file_path', '')
        caption = fig.get('caption', '')[:200]
        fig_num = fig.get('figure_number', '?')

        content_parts.append({'type': 'text', 'text': f'\n--- Figure {fig_num}: {caption} ---'})

        if fpath and os.path.exists(fpath):
            try:
                with open(fpath, 'rb') as f:
                    img_data = f.read()
                total_size += len(img_data)
                if total_size > 5 * 1024 * 1024:
                    logger.warning(f'Total image size exceeds 5MB, skipping remaining figures')
                    break
                img_b64 = base64.b64encode(img_data).decode('utf-8')
                ext = os.path.splitext(fpath)[1].lower().lstrip('.')
                if ext in ('jpg', 'jpeg'):
                    mime = 'image/jpeg'
                elif ext == 'png':
                    mime = 'image/png'
                else:
                    mime = 'image/jpeg'
                content_parts.append({
                    'type': 'image_url',
                    'image_url': {'url': f'data:{mime};base64,{img_b64}'}
                })
            except Exception as e:
                logger.error(f'Failed to load figure image {fpath}: {e}')

    messages = [{'role': 'user', 'content': content_parts}]
    payload = {
        'model': config['vision_model'],
        'messages': messages,
        'temperature': 0.3,
        'max_tokens': 4096,
    }
    api_key_str = config['api_key']
    headers = {
        'Authorization': 'Bearer ' + api_key_str,
        'Content-Type': 'application/json',
    }

    try:
        resp = requests.post(config['api_url'], headers=headers, json=payload, timeout=180)
        resp.raise_for_status()
        result = resp.json()
        return result['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f'Kimi API call failed: {e}')
        return '(Kimi 图表分析失败)'

def analyze_paper(paper_text: str, figures: list = None) -> Dict:
    """Analyze paper using DeepSeek-v4 API. Returns structured analysis."""
    config = _load_deepseek_config()
    if not config:
        logger.warning("DeepSeek API not configured, returning mock analysis")
        return _mock_analysis(paper_text)
    logger.info("Calling {0} for paper analysis...".format(config["model"]))
    return _call_deepseek_api(paper_text, figures, config)


def _build_analysis_prompt(paper_text: str) -> str:
    text = paper_text[:8000]
    return (
        'You are a senior condensed matter physics (experimental) researcher. '
        'Read the paper below and return your analysis as JSON only.\n\n'
        'Paper text:\n{text}\n\n'
        'Return JSON with this structure (no other text):\n'
        '{{\n'
        '    "core_problem": "Describe in Chinese: what scientific problem does this paper address?",\n'
        '    "method": "Describe in Chinese: what experimental or theoretical methods were used?",\n'
        '    "key_results": "Describe in Chinese: key results and findings (be specific with numbers).",\n'
        '    "conclusions": "Describe in Chinese: main conclusions of the authors.",\n'
        '    "limitations": "Describe in Chinese: limitations or open questions.",\n'
        '    "value_rating": integer 1-5 rating of relevance to strongly correlated electron physics,\n'
        '    "one_line_value": "Keep in English: one sentence summary of why this paper matters."\n'
        '}}'
    ).format(text=text)


def _call_deepseek_api(paper_text: str, figures: list, config: Dict) -> Dict:
    import requests
    prompt = _build_analysis_prompt(paper_text)
    messages = [{"role": "user", "content": prompt}]

    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": 1,
        "max_tokens": 2048,
    }
    headers = {
        "Authorization": "Bearer {0}".format(config["api_key"]),
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(config["api_url"], headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            result["full_analysis"] = content
            return result
        return _mock_analysis(paper_text)
    except Exception as e:
        logger.error("DeepSeek API call failed: {0}".format(e))
        return _mock_analysis(paper_text)


def gemini_analyze_paper(paper_text, figures=None):
    """Analyze paper using Gemini 3 Flash. Returns structured analysis dict."""
    config = _load_gemini_config()
    if not config:
        logger.warning('Gemini not configured, falling back to DeepSeek')
        return analyze_paper(paper_text, figures)
    logger.info('Calling Gemini ' + config['model'] + ' for paper analysis...')
    import requests, base64
    text_excerpt = paper_text[:8000]
    content_parts = []
    if figures:
        txt = 'You are a condensed matter physics researcher. '
        txt += 'Analyze this paper and its figures.'
        txt += '\nPaper text:\n' + text_excerpt
        txt += '\n\nFigures captions:\n'
        for fig in figures[:10]:
            cap = (fig.get('caption', '') or '')[:200]
            fn = fig.get('figure_number', '?')
            if cap:
                txt += 'Figure ' + str(fn) + ': ' + cap + '\n'
        txt += '\n\nReturn your analysis as JSON with keys: core_problem, method, key_results, conclusions, limitations, value_rating (1-5), one_line_value'
        content_parts.append({'type': 'text', 'text': txt})
        total_size = 0
        for fig in figures[:5]:
            fp = fig.get('file_path', '')
            if fp and os.path.exists(fp):
                try:
                    with open(fp, 'rb') as imgf:
                        img_data = imgf.read()
                    total_size += len(img_data)
                    if total_size > 5 * 1024 * 1024: break
                    b64 = base64.b64encode(img_data).decode()
                    ext = os.path.splitext(fp)[1].lower()
                    mime = 'image/png' if ext == '.png' else 'image/jpeg'
                    content_parts.append({'type': 'image_url', 'image_url': {'url': 'data:' + mime + ';base64,' + b64}})
                except: pass
    else:
        content_parts.append({'type': 'text', 'text': _build_analysis_prompt(paper_text)})
    contents_list = []
    for cp in content_parts:
        if cp['type'] == 'text':
            contents_list.append({'role': 'user', 'parts': [{'text': cp['text']}]})
        elif cp['type'] == 'image_url':
            url = cp['image_url']['url']
            if url.startswith('data:'):
                inline_data = url.split(';base64,')
                mime = inline_data[0].replace('data:', '"')
                contents_list[-1]['parts'].append({'inline_data': {'mime_type': mime, 'data': inline_data[1]}})
    payload = {'contents': contents_list}
    headers = {'x-goog-api-key': config['api_key'], 'Content-Type': 'application/json'}
    try:
        resp = requests.post(config['api_url'], headers=headers, json=payload, timeout=180)
        resp.raise_for_status()
        raw = resp.json()['candidates'][0]['content']['parts'][0]['text']
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            import json as _json
            result = _json.loads(json_match.group())
            result['full_analysis'] = raw
            return result
        return _mock_analysis(paper_text)
    except Exception as e:
        logger.error('Gemini API call failed: ' + str(e))
        return _mock_analysis(paper_text)
