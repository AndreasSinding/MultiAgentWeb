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
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()

    summary = result.get("summary", "No summary available.")
    blocks = [b.get("content", "") for b in result.get("tasks_output", [])]

    # --- helper to find lines containing a marker ---
    def find_section(prefixes):
        items = []
        for b in blocks:
            line = b.strip()
            for p in prefixes:
                if line.lower().startswith(p.lower()):
                    # remove prefix
                    cleaned = line[len(p):].strip()
                    # bullet markers
                    cleaned = cleaned.lstrip("*-0123456789. ").strip()
                    if cleaned:
                        items.append(cleaned)
        return items

    # --- extract sections ---
    trends = find_section(["* økt", "* økende", "* vekst"])
    competitors = find_section(["* ibm", "* microsoft", "* sap"])
    numbers = find_section(["* ai-markedets", "* veksttakt", "* adopsjonsrate", "* investering", "* antall"])
    recommendations = find_section(["1.", "2.", "3.", "4.", "5."])
    sources = find_section(["* mckinsey", "* marketsandmarkets", "* gartner", "* ibm", "* forrester"])

    # Title slide
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Multi-Agent Insights Report"
    slide.placeholders[1].text = topic

    # Executive Summary
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Executive Summary"
    tf = slide.placeholders[1].text_frame
    tf.clear()
    for i, line in enumerate(summary.split("\n")):
        p = tf.add_paragraph() if i else tf.paragraphs[0]
        p.text = line

    # Key Trends
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Key Trends"
    tf = slide.placeholders[1].text_frame
    tf.clear()
    if trends:
        for i, t in enumerate(trends[:6]):
            p = tf.add_paragraph() if i else tf.paragraphs[0]
            p.text = f"- {t}"
    else:
        tf.text = "No trends identified."

    # Competitors
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Competitors / Actors"
    tf = slide.placeholders[1].text_frame
    tf.clear()
    if competitors:
        for i, c in enumerate(competitors[:6]):
            p = tf.add_paragraph() if i else tf.paragraphs[0]
            p.text = f"- {c}"
    else:
        tf.text = "No competitors identified."

    # Numbers
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Key Numbers"
    tf = slide.placeholders[1].text_frame
    tf.clear()
    if numbers:
        for i, n in enumerate(numbers[:6]):
            p = tf.add_paragraph() if i else tf.paragraphs[0]
            p.text = f"- {n}"
    else:
        tf.text = "No numerical insights identified."

    # Recommendations
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Recommendations"
    tf = slide.placeholders[1].text_frame
    tf.clear()
    if recommendations:
        for i, r in enumerate(recommendations[:6]):
            p = tf.add_paragraph() if i else tf.paragraphs[0]
            p.text = f"- {r}"
    else:
        tf.text = "No recommendations extracted."

    # Sources
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Sources"
    tf = slide.placeholders[1].text_frame
    tf.clear()
    if sources:
        for i, s in enumerate(sources[:10]):
            p = tf.add_paragraph() if i else tf.paragraphs[0]
            p.text = f"- {s}"
    else:
        tf.text = "No sources referenced."

    prs.save(file_path)
    return file_path
