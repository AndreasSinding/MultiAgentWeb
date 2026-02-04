# ui/ppt_builder.py
import json
import re
from pptx import Presentation
from pptx.util import Inches, Pt

def _safe_filename(base: str) -> str:
    # Windows-safe filename
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")
    return safe or "report"

def create_multislide_pptx(result: dict, topic: str, file_name: str = None) -> str:
    """
    Builds a multi-slide PPTX from the MultiAgent result JSON.
    Uses:
      - Executive summary from result.result.raw (fallback if summary absent)
      - Structured arrays (trends/competitors/numbers/sources) parsed from tasks_output[0].raw when present
      - Recommendations parsed from any tasks_output containing a JSON with "recommendations"
    """
    data = result.get("result", {})  # {"raw": "...", "tasks_output": [...] , ...}

    # Executive summary (fallback to 'raw')
    exec_summary = data.get("summary") or data.get("raw") or "Ingen oppsummering tilgjengelig"

    # Try to parse the structured 'research' JSON (trends/competitors/numbers/sources)
    research = None
    for block in data.get("tasks_output", []):
        raw = block.get("raw")
        if isinstance(raw, str):
            raw_str = raw.strip()
            if raw_str.startswith("{") and raw_str.endswith("}"):
                try:
                    research = json.loads(raw_str)
                    break
                except Exception:
                    pass

    trends_list = research.get("trends", []) if research else []
    competitors = research.get("competitors", []) if research else []
    numbers = research.get("numbers", []) if research else []
    sources = research.get("sources", []) if research else []

    # Recommendations (from any JSON containing "recommendations")
    recs = []
    for block in data.get("tasks_output", []):
        raw = block.get("raw")
        if isinstance(raw, str):
            raw_str = raw.strip()
            if raw_str.startswith("{") and '"recommendations"' in raw_str:
                try:
                    analysis = json.loads(raw_str)
                    recs = analysis.get("recommendations", [])
                    break
                except Exception:
                    pass

    prs = Presentation()  # blank deck

    # --- Title slide
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "MultiAgent Report"
    slide.placeholders[1].text = topic

    # --- Executive Summary
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Executive Summary"
    tf = slide.placeholders[1].text_frame
    tf.clear()
    p = tf.paragraphs[0]
    p.text = exec_summary
    p.level = 0

    # --- Trends
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Key Trends"
    tf = slide.placeholders[1].text_frame
    tf.clear()
    if trends_list:
        for i, t in enumerate(trends_list[:6]):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            title = t.get("title", "")
            evidence = t.get("evidence", "")
            why = t.get("why_it_matters", "")
            p.text = f"{title} — {evidence}. Why: {why}"
            p.level = 0
    else:
        tf.text = "No structured trends found."

    # --- Competitors (table)
    slide = prs.slides.add_slide(prs.slide_layouts[5])  # Title Only
    slide.shapes.title.text = "Competitors / Actors"
    left, top, width, height = Inches(0.5), Inches(1.5), Inches(9.0), Inches(1.0)
    rows = min(1 + max(1, len(competitors)), 1 + 10)  # header + up to 10
    table = slide.shapes.add_table(rows, 3, left, top, width, height).table
    headers = ["Name", "Position", "Notes"]
    for j, h in enumerate(headers):
        cell = table.cell(0, j)
        cell.text = h
        for para in cell.text_frame.paragraphs:
            para.font.bold = True
            para.font.size = Pt(14)
    if competitors:
        for i, comp in enumerate(competitors[: rows - 1], start=1):
            table.cell(i, 0).text = comp.get("name", "")
            table.cell(i, 1).text = comp.get("position", "")
            table.cell(i, 2).text = comp.get("notes", "")
    else:
        if rows >= 2:
            table.cell(1, 0).text = "No structured competitors found"

    # --- Numbers (table)
    slide = prs.slides.add_slide(prs.slide_layouts[5])  # Title Only
    slide.shapes.title.text = "Key Numbers"
    left, top, width, height = Inches(0.5), Inches(1.5), Inches(9.0), Inches(1.0)
    rows = min(1 + max(1, len(numbers)), 1 + 12)
    table = slide.shapes.add_table(rows, 3, left, top, width, height).table
    headers = ["Metric", "Value", "Source"]
    for j, h in enumerate(headers):
        cell = table.cell(0, j)
        cell.text = h
        for para in cell.text_frame.paragraphs:
            para.font.bold = True
            para.font.size = Pt(14)
    if numbers:
        for i, n in enumerate(numbers[: rows - 1], start=1):
            table.cell(i, 0).text = n.get("metric", "")
            table.cell(i, 1).text = n.get("value", "")
            table.cell(i, 2).text = n.get("source", "")
    else:
        if rows >= 2:
            table.cell(1, 0).text = "No structured numbers found"

    # --- Recommendations (Top 5)
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Recommendations (Top 5)"
    tf = slide.placeholders[1].text_frame
    tf.clear()
    if recs:
        for i, r in enumerate(recs[:5]):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = f"{r.get('priority', i+1)}) {r.get('action','')} — Why: {r.get('rationale','')}"
            p.level = 0
    else:
        tf.text = "No structured recommendations found."

    # --- Sources
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Sources"
    tf = slide.placeholders[1].text_frame
    tf.clear()
    if sources:
        for i, s in enumerate(sources[:12]):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = str(s)
            p.level = 0
    else:
        tf.text = "No structured sources found."

    if not file_name:
        safe_topic = _safe_filename(topic)
        file_name = f"{safe_topic}_report.pptx"
    prs.save(file_name)
    return file_name
