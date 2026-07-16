"""PDF parser: text extraction + figure extraction + Gemini caption filter"""
import os
import logging
import re
import base64
import hashlib
import json
from typing import List, Dict, Optional
from dataclasses import dataclass, field
import fitz
from . import config

logger = logging.getLogger(__name__)

FIGURE_MIN_SIZE = 100
FIGURE_MAX_AREA = 5000 * 5000
FIGURE_MIN_FILE_SIZE = 5000
MAX_EMBEDDED_FIGURES = 10
SCREENSHOT_ZOOM = 1.5
GEMINI_FILTER_ENABLED = True

# Cache directory for Gemini figure filter
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEMINI_FILTER_CACHE_DIR = os.path.join(BASE_DIR, "cache", "gemini_fig_filter")


@dataclass
class ParsedPDF:
    text: str = ""
    pages: List[str] = field(default_factory=list)
    figures: List[Dict] = field(default_factory=list)
    captions: List[Dict] = field(default_factory=list)  # Text-based figure captions


def parse_pdf(pdf_path: str) -> ParsedPDF:
    """Parse PDF: extract text + figures (embedded images + page screenshots)"""
    result = ParsedPDF()
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.error("Cannot open PDF {0}: {1}".format(pdf_path, e))
        return result

    pdf_dir = os.path.dirname(pdf_path)
    pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]

    pages_with_images = set()
    embedded_count = 0

    # --- Pass 1: Extract embedded images + text ---
    for page_num, page in enumerate(doc):
        page_text = page.get_text()
        result.pages.append(page_text)
        result.text += "\n--- Page {0} ---\n{1}".format(page_num + 1, page_text)

        # Find figure caption candidates from text
        candidates = _find_fig_candidates(page_text)
        if candidates:
            classified = _filter_fig_candidates(page, candidates, page_num, pdf_path)
            for c in classified:
                if c.get("type") == "caption":
                    result.captions.append({
                        "fig_num": c["fig_num"],
                        "text": c["text"],
                        "page_num": page_num,
                    })

        image_list = page.get_images(full=True)
        if image_list:
            pages_with_images.add(page_num)

        for img in image_list:
            xref = img[0]
            try:
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)

                if width < FIGURE_MIN_SIZE or height < FIGURE_MIN_SIZE:
                    continue
                if width * height > FIGURE_MAX_AREA:
                    continue
                if len(image_bytes) < FIGURE_MIN_FILE_SIZE:
                    continue

                embedded_count += 1
                fig_filename = "{0}_fig{1}.{2}".format(pdf_basename, embedded_count, image_ext)
                fig_path = os.path.join(pdf_dir, fig_filename)
                with open(fig_path, "wb") as f:
                    f.write(image_bytes)

                # Try to find caption for this figure
                caption_text = "Figure {0} (Page {1})".format(embedded_count, page_num + 1)
                page_capts = [c for c in result.captions if c["page_num"] == page_num]
                if page_capts:
                    figs_so_far = len([f for f in result.figures if f.get("page_num") == page_num])
                    idx = min(figs_so_far, len(page_capts) - 1)
                    caption_text = page_capts[idx]["text"]

                result.figures.append({
                    "figure_number": str(embedded_count),
                    "file_path": fig_path,
                    "caption": caption_text,
                    "page_num": page_num,
                    "width": width,
                    "height": height,
                    "file_size": len(image_bytes),
                })
                logger.info("  Extracted figure: {0} ({1}x{2}, {3} bytes)".format(fig_path, width, height, len(image_bytes)))
            except Exception as e:
                logger.warning("  Figure extract failed (xref={0}): {1}".format(xref, e))

    # Trim to MAX_EMBEDDED_FIGURES, keeping the largest ones
    if len(result.figures) > MAX_EMBEDDED_FIGURES:
        result.figures.sort(key=lambda f: f.get("file_size", 0), reverse=True)
        kept = result.figures[:MAX_EMBEDDED_FIGURES]
        removed = result.figures[MAX_EMBEDDED_FIGURES:]
        result.figures = kept
        for f in removed:
            try:
                os.remove(f["file_path"])
                logger.info("  Removed small figure: {0}".format(f["file_path"]))
            except Exception:
                pass
        for i, f in enumerate(result.figures):
            f["figure_number"] = str(i + 1)
            old_path = f["file_path"]
            new_path = os.path.join(os.path.dirname(old_path),
                "{0}_fig{1}.png".format(pdf_basename, i + 1))
            if old_path != new_path:
                try:
                    os.rename(old_path, new_path)
                    f["file_path"] = new_path
                except Exception:
                    pass
        logger.info("  Trimmed to {0} largest figures".format(len(result.figures)))

    # --- Pass 2: Page screenshots for pages with figure captions ---
    # Take screenshots for pages that have text-based figure captions
    # even if they also have embedded images (which may be sub-components)
    caption_pages = set(c["page_num"] for c in result.captions)
    if caption_pages:
        logger.info("Taking page screenshots for %d pages with figure captions..." % len(caption_pages))
        for page_num in sorted(caption_pages):
            _screenshot_page(doc, page_num, pdf_dir, pdf_basename, result)

    # --- Pass 3: Supplement with page screenshots for image-rich pages ---
    if embedded_count < 3 and pages_with_images:
        logger.info("Only {0} embedded images, supplementing with page screenshots...".format(embedded_count))
        for page_num in sorted(pages_with_images):
            if page_num in caption_pages:
                continue  # Already screenshotted in Pass 2
            figs_on_page = [f for f in result.figures if f["page_num"] == page_num]
            if len(figs_on_page) >= 2:
                continue
            _screenshot_page(doc, page_num, pdf_dir, pdf_basename, result)

    # --- Pass 4: Fallback - screenshot early pages ---
    if len(result.figures) < 3 and len(doc) > 0:
        logger.info("Still fewer than 3 figures, screenshotting early pages...")
        pages_to_screenshot = set(range(min(5, len(doc)))) - {f["page_num"] for f in result.figures}
        for page_num in sorted(pages_to_screenshot)[:4]:
            _screenshot_page(doc, page_num, pdf_dir, pdf_basename, result)

    page_count = len(doc)
    doc.close()
    logger.info("PDF parsed: {0} pages, {1} figures, {2} text captions".format(
        page_count, len(result.figures), len(result.captions)))
    return result


def _find_fig_candidates(page_text: str) -> List[Dict]:
    """Find figure caption candidates from page text using regex.
    Collects multi-line captions when figure label is at line start.

    Returns list of dicts with 'fig_num' and 'text' keys.
    """
    candidates = []
    lines = page_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        line_stripped = line.strip()
        if not line_stripped:
            i += 1
            continue
        # Match "Fig. X", "Figure X", "FIG X" patterns at line start
        match = re.match(
            r"^\s*(?:Fig(?:ure)?s?\s*\.?\s*|FIGS?\s*\.?\s*|FIG\.?\s*)"
            r"(\d+[A-Za-z]?(?:\([^)]*\))?)",
            line_stripped, re.IGNORECASE,
        )
        if match:
            fig_num = match.group(1)
            caption_parts = [line_stripped]
            # Look ahead at subsequent lines to collect full caption text
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if not next_line:
                    break  # Empty line ends the caption block
                # If the next line starts with another figure label, stop
                if re.match(
                    r"^\s*(?:Fig(?:ure)?s?\s*\.?\s*|FIGS?\s*\.?\s*|FIG\.?\s*)"
                    r"(\d+[A-Za-z]?(?:\([^)]*\))?)",
                    next_line, re.IGNORECASE,
                ):
                    break
                caption_parts.append(next_line)
                j += 1
            full_text = " ".join(caption_parts)
            # Deduplicate: keep only first occurrence of each fig_num on this page
            existing = [c for c in candidates if c["fig_num"] == fig_num]
            if not existing:
                candidates.append({
                    "fig_num": fig_num,
                    "text": full_text[:600],
                })
            i = j  # Skip consumed lines
            continue
        # Also match lines containing figure references (inline references, single line)
        match = re.search(
            r"(?:Fig(?:ure)?s?\s*\.?\s*|FIGS?\s*\.?\s*)(\d+[A-Za-z]?(?:\([^)]*\))?)",
            line_stripped, re.IGNORECASE,
        )
        if match:
            fig_num = match.group(1)
            existing = [c for c in candidates if c["fig_num"] == fig_num]
            if not existing:
                candidates.append({
                    "fig_num": fig_num,
                    "text": line_stripped[:300],
                })
        i += 1
    return candidates

def _filter_fig_candidates(page, candidates: List[Dict], page_num: int, pdf_path: str) -> List[Dict]:
    """Classify figure caption candidates using Gemini 3 Flash, with heuristic fallback."""
    if not GEMINI_FILTER_ENABLED:
        return _heuristic_filter(candidates, page.get_text() if page else "")

    gemini_config = _load_gemini_config()
    if not gemini_config:
        logger.debug("Gemini not configured, using heuristic fallback")
        return _heuristic_filter(candidates, page.get_text() if page else "")

    # Check cache
    pdf_md5 = hashlib.md5(pdf_path.encode()).hexdigest()[:12]
    os.makedirs(GEMINI_FILTER_CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(GEMINI_FILTER_CACHE_DIR, "{0}_p{1}.json".format(pdf_md5, page_num + 1))

    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                cached = json.load(f)
            logger.debug("Gemini filter cache hit: {0}".format(cache_path))
            return cached
        except Exception:
            pass

    # Page screenshot -> base64
    try:
        mat = fitz.Matrix(SCREENSHOT_ZOOM, SCREENSHOT_ZOOM)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("png")
        b64 = base64.b64encode(img_bytes).decode()
    except Exception as e:
        logger.warning("Page screenshot failed: {0}, using heuristic fallback".format(e))
        return _heuristic_filter(candidates, page.get_text() if page else "")

    # Build candidates text
    candidate_lines = "\n".join(
        "{0}. [Fig {1}] \"{2}\"".format(i + 1, c["fig_num"], c["text"][:200])
        for i, c in enumerate(candidates)
    )

    # Use Gemini
    try:
        from arxiv_assistant.ai_reader import gemini_classify_captions
        gemini_result = gemini_classify_captions(b64, candidate_lines, gemini_config)
        if gemini_result and "results" in gemini_result:
            result_map = {r["fig"]: r["type"] for r in gemini_result["results"]}
            results = []
            for c in candidates:
                fig_type = result_map.get(c["fig_num"], "reference")
                results.append({**c, "type": fig_type})
            # Cache
            try:
                with open(cache_path, "w") as f:
                    json.dump(results, f)
            except Exception:
                pass
            return results
    except Exception as e:
        logger.warning("Gemini filter failed: {0}, using heuristic fallback".format(e))

    return _heuristic_filter(candidates, page.get_text() if page else "")


def _heuristic_filter(candidates: List[Dict], page_text: str) -> List[Dict]:
    """Fallback: classify candidates using heuristic rules."""
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


def _load_gemini_config() -> Optional[Dict]:
    """Load Gemini API config from config_local.py"""
    try:
        import sys
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


def _screenshot_page(doc, page_num: int, pdf_dir: str, pdf_basename: str, result):
    """Take a page screenshot and add to result.figures"""
    try:
        page = doc[page_num]
        mat = fitz.Matrix(SCREENSHOT_ZOOM, SCREENSHOT_ZOOM)
        pix = page.get_pixmap(matrix=mat)
        fig_filename = "{0}_page{1}.png".format(pdf_basename, page_num + 1)
        fig_path = os.path.join(pdf_dir, fig_filename)
        pix.save(fig_path)

        # Find caption for this page
        caption_text = "Page {0}".format(page_num + 1)
        for capt in result.captions:
            if capt["page_num"] == page_num:
                caption_text = capt["text"]
                break

        result.figures.append({
            "figure_number": "page{0}".format(page_num + 1),
            "file_path": fig_path,
            "caption": caption_text,
            "page_num": page_num,
            "width": pix.width,
            "height": pix.height,
        })
        logger.info("  Page screenshot: {0}".format(fig_path))
    except Exception as e:
        logger.warning("  Page screenshot failed (page {0}): {1}".format(page_num + 1, e))


def extract_text_only(pdf_path: str) -> str:
    """Extract text only (no figures)"""
    try:
        doc = fitz.open(pdf_path)
        text = "".join(page.get_text() + "\n" for page in doc)
        doc.close()
        return text
    except Exception as e:
        logger.error("Text extraction failed: {0}".format(e))
        return ""
