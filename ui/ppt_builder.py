# ui/ppt_builder.py
import json
import re
from pptx import Presentation
from pptx.util import Inches, Pt

def _safe_filename(base: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")
    return safe or "report"


# -------------------------------------------------------------------
# TEXT->LIST HELPERS (lightweight NLP)
# -------------------------------------------------------------------

def extract_bullets_from_text(text: str, max_items=8):
    """Convert a block of text into easy PPT bullet points."""
    if not text:
        return []

    lines = re.split(r"[\n•\-]+", text)
    lines = [l.strip() for l in lines if l.strip()]
    return lines[:max_items]


def extract_sections(tasks_output):
    """
    For each slide type, search the task content for keywords.
    This works even if your LLM output is messy or unstructured.
    """

    combined = "\n".join(
        item.get("content", "") for item in tasks_output if isinstance(item, dict)
    )

    def find_section(keyword):
        pattern = rf"{keyword}[:\-]\s*(.+?)(?=\n[A-Z][a-z]|$)"
        match = re.search(pattern, combined, flags=re.IGNORECASE | re.DOTALL)
        return match.group(1).strip() if match else ""

    return {
        "trends": extract_bullets_from_text(find_section("trend")),
        "competitors": extract_bullets_from_text(find_section("competitor")),
        "numbers": extract_bullets_from_text(find_section("number")),
        "recommendations": extract_bullets_from_text(find_section("recommendation")),
        "sources": extract_bullets_from_text(find_section("source"), max_items=12),
    }


# -------------------------------------------------------------------
# GENERATOR
# -------------------------------------------------------------------

def create_multislide_pptx(result: dict, topic: str, file_path: str) -> str:
    """
    NEW VERSION:
        • Uses pipeline's new enriched structure
        • Extracts information directly from 'summary' + 'tasks_output'
        • No structured JSON required
    """

    summary = result.get("summary") or "No summary available."
    tasks_output = result.get("tasks_output", [])

    sections = extract_sections(tasks_output)

    prs = Presentation()

    # -------- Slide 1 — Title --------
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Multi‑Agent Insights Report"
    slide.placeholders[1].text = topic

    # -------- Slide 2 — Executive Summary --------
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Executive Summary"
    tf = slide.placeholders[1].text_frame
    tf.clear()

    for i, line in enumerate(extract_bullets_from_text(summary)):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.level = 0

    # -------- Slide 3 — Key Trends --------
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Key Trends"
    tf = slide.placeholders[1].text_frame
    tf.clear()

    trends = sections["trends"]
    if trends:
        for i, t in enumerate(trends):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = t
    else:
        tf.text = "No trends identified."

    # -------- Slide 4 — Competitors --------
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Competitors / Actors"
    tf = slide.placeholders[1].text_frame
    tf.clear()

    comps = sections["competitors"]
    if comps:
        for i, c in enumerate(comps):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = c
    else:
        tf.text = "No competitors identified."

    # -------- Slide 5 — Key Numbers --------
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Key Numbers"
    tf = slide.placeholders[1].text_frame
    tf.clear()

    numbers = sections["numbers"]
    if numbers:
        for i, n in enumerate(numbers):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = n
    else:
        tf.text = "No numerical insights identified."

    # -------- Slide 6 — Recommendations --------
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Recommendations"
    tf = slide.placeholders[1].text_frame
    tf.clear()

    recs = sections["recommendations"]
    if recs:
        for i, r in enumerate(recs[:5]):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = r
    else:
        tf.text = "No recommendations extracted."

    # -------- Slide 7 — Sources --------
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Sources"
    tf = slide.placeholders[1].text_frame
    tf.clear()

    srcs = sections["sources"]
    if srcs:
        for i, s in enumerate(srcs):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = s
    else:
        tf.text = "No sources referenced."

    prs.save(file_path)
    return file_path
