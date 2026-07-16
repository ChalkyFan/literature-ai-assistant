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
        "temperature": 0.3,
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
