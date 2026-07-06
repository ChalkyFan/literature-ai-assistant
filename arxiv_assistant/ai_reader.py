"""AI paper analysis - DeepSeek-v4 integration"""
import json
import logging
import os
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def _load_deepseek_config() -> Optional[Dict]:
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
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
