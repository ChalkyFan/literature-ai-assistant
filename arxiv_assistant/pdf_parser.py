"""PDF parser: text extraction + figure extraction"""
import os
import logging
from typing import List, Dict
from dataclasses import dataclass, field
import fitz
from . import config

logger = logging.getLogger(__name__)

FIGURE_MIN_SIZE = 100      # minimum width/height in pixels
FIGURE_MAX_AREA = 5000 * 5000
FIGURE_MIN_FILE_SIZE = 5000  # minimum file size in bytes (filter tiny garbage images)
MAX_EMBEDDED_FIGURES = 10    # max embedded images to keep (keep the largest ones)
SCREENSHOT_ZOOM = 1.5      # 150 DPI for page screenshots


@dataclass
class ParsedPDF:
    text: str = ""
    pages: List[str] = field(default_factory=list)
    figures: List[Dict] = field(default_factory=list)


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

    # Track which pages have images and how many we extracted from each
    pages_with_images = set()
    embedded_count = 0

    # --- Pass 1: Extract embedded images (Scheme B) ---
    for page_num, page in enumerate(doc):
        page_text = page.get_text()
        result.pages.append(page_text)
        result.text += "\n--- Page {0} ---\n{1}".format(page_num + 1, page_text)

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

                # Filter out tiny images (icons/logos) and huge ones (full page scans)
                if width < FIGURE_MIN_SIZE or height < FIGURE_MIN_SIZE:
                    continue
                if width * height > FIGURE_MAX_AREA:
                    continue
                # Skip small files (garbage images)
                if len(image_bytes) < FIGURE_MIN_FILE_SIZE:
                    continue

                embedded_count += 1
                fig_filename = "{0}_fig{1}.{2}".format(pdf_basename, embedded_count, image_ext)
                fig_path = os.path.join(pdf_dir, fig_filename)
                with open(fig_path, "wb") as f:
                    f.write(image_bytes)
                result.figures.append({
                    "figure_number": str(embedded_count),
                    "file_path": fig_path,
                    "caption": "Figure {0} (Page {1})".format(embedded_count, page_num + 1),
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
        # Delete removed figure files
        for f in removed:
            try:
                os.remove(f["file_path"])
                logger.info("  Removed small figure: {0}".format(f["file_path"]))
            except Exception:
                pass
        # Re-number figures
        for i, f in enumerate(result.figures):
            f["figure_number"] = str(i + 1)
            f["caption"] = "Figure {0} (Page {1})".format(i + 1, f["page_num"] + 1)
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

    # --- Pass 2: Supplement with page screenshots if not enough figures ---
    # If fewer than 3 embedded images, screenshot pages that contain images
    if embedded_count < 3 and pages_with_images:
        logger.info("Only {0} embedded images, supplementing with page screenshots...".format(embedded_count))
        for page_num in sorted(pages_with_images):
            # Skip pages where we already have >= 2 embedded figures
            figs_on_page = [f for f in result.figures if f["page_num"] == page_num]
            if len(figs_on_page) >= 2:
                continue
            _screenshot_page(doc, page_num, pdf_dir, pdf_basename, result)

    # --- Pass 3: Ultimate fallback - screenshot early pages if still < 3 figures ---
    if len(result.figures) < 3 and len(doc) > 0:
        logger.info("Still fewer than 3 figures, screenshotting early pages...")
        pages_to_screenshot = set(range(min(5, len(doc)))) - {f["page_num"] for f in result.figures}
        for page_num in sorted(pages_to_screenshot)[:4]:  # max 4 extra screenshots
            _screenshot_page(doc, page_num, pdf_dir, pdf_basename, result)

    page_count = len(doc)
    doc.close()
    logger.info("PDF parsed: {0} pages, {1} figures extracted".format(page_count, len(result.figures)))
    return result


def _screenshot_page(doc, page_num: int, pdf_dir: str, pdf_basename: str, result):
    """Take a page screenshot and add to result.figures"""
    try:
        page = doc[page_num]
        mat = fitz.Matrix(SCREENSHOT_ZOOM, SCREENSHOT_ZOOM)
        pix = page.get_pixmap(matrix=mat)
        fig_filename = "{0}_page{1}.png".format(pdf_basename, page_num + 1)
        fig_path = os.path.join(pdf_dir, fig_filename)
        pix.save(fig_path)
        result.figures.append({
            "figure_number": "page{0}".format(page_num + 1),
            "file_path": fig_path,
            "caption": "Page {0}".format(page_num + 1),
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
