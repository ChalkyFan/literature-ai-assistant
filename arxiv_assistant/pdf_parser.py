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
from PIL import Image
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
    """Parse PDF: extract text + figures (complete figure extraction for pages with captions)"""
    result = ParsedPDF()
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.error("Cannot open PDF {0}: {1}".format(pdf_path, e))
        return result

    pdf_dir = os.path.dirname(pdf_path)
    pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]

    caption_pages = set()
    embedded_count = 0

    # --- Phase 1: Text extraction + caption classification (no embedded images) ---
    for page_num, page in enumerate(doc):
        page_text = page.get_text()
        result.pages.append(page_text)
        result.text += "\n--- Page {0} ---\n{1}".format(page_num + 1, page_text)

        candidates = _find_fig_candidates(page_text)
        if candidates:
            classified = _filter_fig_candidates(page, candidates, page_num, pdf_path)
            page_has_caption = False
            for c in classified:
                if c.get("type") == "caption":
                    result.captions.append({
                        "fig_num": c["fig_num"],
                        "text": c["text"],
                        "page_num": page_num,
                    })
                    page_has_caption = True
            if page_has_caption:
                caption_pages.add(page_num)

    # --- Phase 2: Complete figure extraction for pages with captions ---
    for page_num in sorted(caption_pages):
        page_captions = [c for c in result.captions if c["page_num"] == page_num]
        if page_captions:
            start_num = len(result.figures) + 1
            figures = _extract_complete_figures(doc, page_num, pdf_dir, pdf_basename,
                                                 page_captions, start_num)
            if figures:
                result.figures.extend(figures)
                logger.info("  Page {0}: extracted {1} complete figure(s)".format(
                    page_num + 1, len(figures)))

    # --- Phase 3: Embedded image extraction for pages without complete figures ---
    # Track which pages already got complete figures in Phase 2
    pages_with_complete_figs = set(f["page_num"] for f in result.figures)
    for page_num, page in enumerate(doc):
        if page_num in caption_pages:
            continue
        if page_num in pages_with_complete_figs:
            continue

        image_list = page.get_images(full=True)
        if not image_list:
            continue

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
                logger.info("  Extracted embedded image: {0} ({1}x{2}, {3} bytes)".format(
                    fig_path, width, height, len(image_bytes)))
            except Exception as e:
                logger.warning("  Embedded image extract failed (xref={0}): {1}".format(xref, e))

    # --- Phase 4: Trim to MAX_EMBEDDED_FIGURES, keeping the largest ---
    if len(result.figures) > MAX_EMBEDDED_FIGURES:
        result.figures.sort(key=lambda f: f.get("file_size", 0), reverse=True)
        kept = result.figures[:MAX_EMBEDDED_FIGURES]
        removed = result.figures[MAX_EMBEDDED_FIGURES:]
        result.figures = kept
        for f in removed:
            try:
                os.remove(f["file_path"])
                logger.info("  Removed oversized figure: {0}".format(f["file_path"]))
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

    # --- Phase 5: Fallback screenshots for early pages ---
    if len(result.figures) < 3 and len(doc) > 0:
        logger.info("Fewer than 3 figures, fallback screenshots...")
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
                    "at_line_start": True,
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
                    "at_line_start": False,
                })
        i += 1
    return candidates

def _filter_fig_candidates(page, candidates: List[Dict], page_num: int, pdf_path: str) -> List[Dict]:
    """Classify figure caption candidates using Gemini 3 Flash, with heuristic fallback."""
    # Line-start figure labels are always standalone captions
    need_filter = [c for c in candidates if not c.get("at_line_start", False)]
    if len(need_filter) != len(candidates):
        results = [c for c in candidates if c.get("at_line_start", False)]
        for c in results:
            c["type"] = "caption"
        if not need_filter:
            return results
        candidates = need_filter
    else:
        results = []

    if not GEMINI_FILTER_ENABLED:
        return results + _heuristic_filter(candidates, page.get_text() if page else "")

    gemini_config = _load_gemini_config()
    if not gemini_config:
        logger.debug("Gemini not configured, using heuristic fallback")
        return results + _heuristic_filter(candidates, page.get_text() if page else "")

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
        # Line-start figure labels are always standalone captions
        if c.get("at_line_start", False):
            results.append({**c, "type": "caption"})
            continue
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



def _crop_bottom_blank(img, min_ink_threshold=248, min_ink_ratio=0.001, pad=3):
    """Crop mostly-blank rows from the bottom of a rendered figure.
    
    Scans from bottom-up, finds the last row with meaningful ink content,
    then trims all rows below that plus a small padding. Adapts automatically
    to each figure — works for any paper layout.
    
    Args:
        img: PIL Image object (RGB or grayscale).
        min_ink_threshold: pixel brightness below which is "ink" (0-255).
        min_ink_ratio: minimum fraction of ink pixels for a row to count as content.
        pad: extra rows to keep below last content row as safety margin.
    
    Returns:
        Cropped PIL Image, or original if no significant blank space found.
    """
    import numpy as np
    arr = np.array(img)
    h, w = arr.shape[:2]
    
    # Convert to grayscale
    if len(arr.shape) == 3:
        gray = arr.astype(np.float32).mean(axis=2)
    else:
        gray = arr.astype(np.float32)
    
    # Find last row with significant ink content
    last_content_row = 0
    for row in range(h - 1, -1, -1):
        dark_pixels = (gray[row] < min_ink_threshold).mean()
        if dark_pixels > min_ink_ratio:
            last_content_row = row
            break
    
    # New bottom: content + safety pad
    new_bottom = min(h, last_content_row + pad + 1)
    
    # Only crop if it saves significant space (>3 rows)
    if h - new_bottom <= 3:
        return img
    
    return img.crop((0, 0, w, new_bottom))


def _extract_complete_figures(doc, page_num: int, pdf_dir: str, pdf_basename: str,
                               page_captions: list, start_num: int = 1) -> list:
    """Extract complete figures from a page by grouping nearby image bboxes and cropping.

    Groups image bboxes (sub-panels like a,b,c,d) into complete figure regions,
    renders with clip, and saves the cropped region including caption text.
    Uses y-overlap heuristic for multi-column figure layout.
    """
    FIGURE_CROP_ZOOM = 2.0
    MIN_IMG_DIM = 50
    Y_GAP = 40  # max vertical gap to merge sub-panels on same row

    try:
        page = doc[page_num]
        image_infos = page.get_image_info()

        large_infos = [
            info for info in image_infos
            if info.get("width", 0) >= MIN_IMG_DIM and info.get("height", 0) >= MIN_IMG_DIM
            and info.get("bbox")
        ]

        if not large_infos:
            logger.debug("  No large images found on page {0}".format(page_num + 1))
            return []

        # Convert to Rect objects
        all_rects = [fitz.Rect(b[0], b[1], b[2], b[3]) for b in [i["bbox"] for i in large_infos]]

        # Simple grouping: merge all bboxes into one group per page
        # Physics papers usually have one figure per page
        # If there are captions, use them to determine number of groups
        num_captions = len(page_captions) if page_captions else 1

        # Strategy: sort by y, group using y-overlap + y-gap
        sorted_rects = sorted(all_rects, key=lambda r: r.y0)

        figure_groups = []
        for rect in sorted_rects:
            merged = False
            for i, group in enumerate(figure_groups):
                # Check if rect y-ranges overlap with group y-ranges
                # or if they are very close
                y_overlap = rect.y0 < group.y1 and group.y0 < rect.y1
                y_dist = min(abs(rect.y0 - group.y1), abs(rect.y1 - group.y0))
                x_overlap = rect.x0 < group.x1 and group.x0 < rect.x1

                if y_overlap or (y_dist < Y_GAP and x_overlap):
                    group.x0 = min(group.x0, rect.x0)
                    group.y0 = min(group.y0, rect.y0)
                    group.x1 = max(group.x1, rect.x1)
                    group.y1 = max(group.y1, rect.y1)
                    merged = True
                    break

            if not merged:
                figure_groups.append(rect)

        # If we have more groups than captions, merge some
        if len(figure_groups) > num_captions:
            # Try merging: merge small groups near large ones
            figure_groups.sort(key=lambda g: (g.y1 - g.y0) * (g.x1 - g.x0), reverse=True)
            large_groups = figure_groups[:num_captions]
            small_groups = figure_groups[num_captions:]
            for small_g in small_groups:
                best_idx = 0
                best_dist = float("inf")
                for j, large_g in enumerate(large_groups):
                    d = abs(small_g.y0 - large_g.y1) + abs(small_g.x0 - large_g.x0)
                    if d < best_dist:
                        best_dist = d
                        best_idx = j
                large_groups[best_idx].x0 = min(large_groups[best_idx].x0, small_g.x0)
                large_groups[best_idx].y0 = min(large_groups[best_idx].y0, small_g.y0)
                large_groups[best_idx].x1 = max(large_groups[best_idx].x1, small_g.x1)
                large_groups[best_idx].y1 = max(large_groups[best_idx].y1, small_g.y1)
            figure_groups = large_groups

        results = []
        for idx, group_rect in enumerate(figure_groups):
            PAD = 1
            group_rect.x0 = max(0, group_rect.x0 - PAD)
            group_rect.y0 = max(0, group_rect.y0 - PAD)
            group_rect.x1 += PAD
            group_rect.y1 += PAD

            # Extend downward to include caption text
            if idx < len(page_captions):
                fig_num = page_captions[idx]["fig_num"]
                search_terms = [
                    "Fig. " + fig_num, "Figure " + fig_num, "FIG " + fig_num,
                ]
                if "(" in fig_num:
                    base = fig_num.split("(")[0]
                    search_terms.extend(["Fig. " + base, "Figure " + base])
                found_rect = None
                for term in search_terms:
                    areas = page.search_for(term)
                    if areas:
                        found_rect = areas[0]
                        for ar in areas[1:]:
                            d = abs(ar.y1 - group_rect.y1)
                            if d < abs(found_rect.y1 - group_rect.y1):
                                found_rect = ar
                        found_rect.y1 += 2
                        break
                if found_rect and found_rect.y1 > group_rect.y1:
                    group_rect.y1 = found_rect.y1 + PAD
                    group_rect.x0 = min(group_rect.x0, found_rect.x0 - PAD)
                    group_rect.x1 = max(group_rect.x1, found_rect.x1 + PAD)

            # DEBUG: print group_rect
            logger.info("    group_rect for Fig {0}: ({1:.1f}, {2:.1f}, {3:.1f}, {4:.1f}) = {5:.0f}x{6:.0f}".format(
                idx+1, group_rect.x0, group_rect.y0, group_rect.x1, group_rect.y1,
                group_rect.width, group_rect.height))
            # Render with clip
            mat = fitz.Matrix(FIGURE_CROP_ZOOM, FIGURE_CROP_ZOOM)
            try:
                pix = page.get_pixmap(matrix=mat, clip=group_rect)
            except Exception as render_e:
                logger.warning("  Clip render failed (page {0} fig {1}): {2}".format(
                    page_num + 1, idx + 1, render_e))
                continue

            if pix.width < 100 or pix.height < 100:
                continue

            fig_num = start_num + idx
            fig_filename = "{0}_fig{1}.png".format(pdf_basename, fig_num)
            fig_path = os.path.join(pdf_dir, fig_filename)
            # Content-aware bottom trim: remove excess blank rows below figure content
            try:
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                cropped = _crop_bottom_blank(img)
                if cropped.size[1] < pix.height:
                    logger.info("    Trimmed {0} blank rows from bottom of Fig {1}".format(
                        pix.height - cropped.size[1], fig_num))
                cropped.save(fig_path)
            except Exception as trim_e:
                logger.warning("    Bottom trim failed for Fig {0}: {1}".format(fig_num, trim_e))
                pix.save(fig_path)

            caption_text = page_captions[idx]["text"] if idx < len(page_captions) else "Figure {0} (Page {1})".format(fig_num, page_num + 1)

            results.append({
                "figure_number": str(fig_num),
                "file_path": fig_path,
                "caption": caption_text,
                "page_num": page_num,
                "width": pix.width,
                "height": pix.height,
                "file_size": os.path.getsize(fig_path),
            })
            logger.info("  Complete Figure {0}: {1} ({2}x{3})".format(
                fig_num, fig_path, pix.width, pix.height))

        return results

    except Exception as e:
        logger.warning("  Complete figure extraction failed (page {0}): {1}".format(page_num + 1, e))
        return []
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
