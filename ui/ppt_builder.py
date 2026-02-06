# -*- coding: utf-8 -*-
"""
ppt_builder.py – FINAL JSON-FIRST BUILDER (Option A + A2 fallback)

This version is optimized for:
- CrewAI multi-agent JSON-only outputs
- Stable, deterministic 10-slide PowerPoint reports
- Soft fallback: missing JSON sections -> empty slides (no crash)
- Works with FastAPI /reports/pptx route

Slides generated:
 1) Title
 2) Executive Summary
 3) Key Trends
 4) Market Insights
 5) Opportunities
 6) Risks
 7) Competitors / Actors (table)
 8) Key Numbers (table)
 9) Recommendations
10) Sources

Author: Finalized for Andreas' Azure pipeline
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN


# ---------------------------------------------------------------------------
# JSON sanitizer (IMPORTANT!)
# ---------------------------------------------------------------------------

def _preclean_near_json(s: str) -> str:
    """Clean markdown bullets, code fences, and stray formatting before JSON parsing."""
    import re
    if not isinstance(s, str):
        return ""
    s = s.strip()
    # remove code fences like ```json or ```
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.I|re.M).strip()
    # remove leading "-" or "*" bullets
    lines = [re.sub(r"^\s*[-*]\s+","", ln) for ln in s.splitlines()]
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _safe_filename(base: str) -> str:
    import re
    if not base:
        return "report"
    return re.sub(r"[^A-Za-z0-9._\-]+", "_", base).strip("_") or "report"


def _strip(x: Any) -> str:
    return (x or "").strip()


def _coerce_list(x: Any) -> List[Any]:
    if not x:
        return []
    return list(x) if isinstance(x, list) else [x]


def _style_paragraph(p, size_pt: int = 18, font: str = "Segoe UI"):
    """Safe python-pptx font styling."""
    try:
        p.font.size = Pt(size_pt)
        p.font.name = font
    except Exception:
        pass
    for r in p.runs:
        try:
            r.font.size = Pt(size_pt)
            r.font.name = font
        except Exception:
            pass


# ---------------------------------------------------------------------------
# JSON extraction (Option A2: strict-first, fallback second)
# ---------------------------------------------------------------------------

def _extract_all_json_blocks(tasks_output: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract ALL valid JSON dicts from tasks_output[*].raw/content/text.
    Merge them into one data structure.
    Missing sections -> empty lists (A2).
    """

    merged = {
        "summary": "",
        "trends": [],
        "insights": [],
        "opportunities": [],
        "risks": [],
        "competitors": [],
        "numbers": [],
        "recommendations": [],
        "sources": []
    }

    for blk in tasks_output:
        for key in ("raw", "content", "text"):
            s = blk.get(key)
            if not isinstance(s, str):
                continue
            ss = _preclean_near_json(s.strip())

            # STRICT JSON BLOCK: whole string is JSON
            if ss.startswith("{") and ss.endswith("}"):
                try:
                    obj = json.loads(ss)
                    if isinstance(obj, dict):
                        _merge_json_into(merged, obj)
                except Exception:
                    pass

            # FALLBACK: embedded { ... } blocks
            for obj in _brace_scan_json(ss):
                _merge_json_into(merged, obj)

    return merged


def _brace_scan_json(text: str) -> List[Dict[str, Any]]:
    """Extract { ... } blocks using brace depth scanning."""
    objs = []
    depth = 0
    start = None

    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                block = text[start : i + 1]
                try:
                    obj = json.loads(block)
                    if isinstance(obj, dict):
                        objs.append(obj)
                except Exception:
                    pass
                start = None

    return objs


# ---------------------------------------------------------------------------
# JSON normalization + merging
# ---------------------------------------------------------------------------

def _merge_json_into(merged: Dict[str, Any], obj: Dict[str, Any]) -> None:
    """Merge JSON dict from agent into main structure."""

    # Summary (prefer longest)
    if "summary" in obj:
        s = _strip(obj.get("summary"))
        if s and len(s) > len(merged["summary"]):
            merged["summary"] = s

    # Simple list fields
    for key in ("trends", "insights", "opportunities", "risks", "sources"):
        for item in _coerce_list(obj.get(key)):
            s = _strip(item)
            if s and s not in merged[key]:
                merged[key].append(s)

    # Competitors
    if "competitors" in obj:
        for comp in _coerce_list(obj.get("competitors")):
            if isinstance(comp, dict):
                merged["competitors"].append({
                    "name": _strip(comp.get("name")),
                    "position": _strip(comp.get("position")),
                    "notes": _strip(comp.get("notes")),
                })

    # Numbers
    if "numbers" in obj:
        for n in _coerce_list(obj.get("numbers")):
            if isinstance(n, dict):
                merged["numbers"].append({
                    "metric": _strip(n.get("metric")),
                    "value": _strip(n.get("value")),
                    "source": _strip(n.get("source")),
                })

    # Recommendations
    if "recommendations" in obj:
        for r in _coerce_list(obj.get("recommendations")):
            if isinstance(r, dict):
                merged["recommendations"].append({
                    "priority": r.get("priority"),
                    "action": _strip(r.get("action")),
                    "rationale": _strip(r.get("rationale")),
                })


# ---------------------------------------------------------------------------
# PPT slide helpers
# ---------------------------------------------------------------------------

def _add_bullet_slide(prs, title: str, bullets: List[str], size=18):
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title
    tf = slide.placeholders[1].text_frame
    tf.clear()

    if not bullets:
        tf.text = "No data available."
        return

    for i, line in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = str(line)
        p.level = 0
        _style_paragraph(p, size_pt=size)


def _add_table_slide(prs, title: str, headers: List[str], rows: List[List[str]]):
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = title

    left, top, width, height = Inches(0.6), Inches(1.6), Inches(9.0), Inches(1.0)
    n_rows = max(2, 1 + len(rows))
    n_cols = len(headers)

    table = slide.shapes.add_table(n_rows, n_cols, left, top, width, height).table

    # Header
    for j, h in enumerate(headers):
        cell = table.cell(0, j)
        cell.text = h
        for p in cell.text_frame.paragraphs:
            p.font.bold = True
            p.font.size = Pt(14)
            p.alignment = PP_ALIGN.LEFT

    # Rows
    if rows:
        for i, r in enumerate(rows[: n_rows - 1], start=1):
            for j in range(n_cols):
                cell = table.cell(i, j)
                cell.text = str(r[j]) if j < len(r) else ""
                for p in cell.text_frame.paragraphs:
                    p.font.size = Pt(12)
    else:
        table.cell(1, 0).text = "No structured data available."


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def create_multislide_pptx(result: Dict[str, Any], topic: str, file_path: str) -> str:
    """Build the full 10-slide deck."""
    data = result.get("result", {})
    tasks_output = data.get("tasks_output", [])

    sections = _extract_all_json_blocks(tasks_output)

    if not sections["summary"]:
        sections["summary"] = _strip(data.get("summary")) or "No summary available."

    prs = Presentation()

    # 1) Title
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Multi‑Agent Insights Report"
    slide.placeholders[1].text = topic

    # 2) Executive Summary
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Executive Summary"
    tf = slide.placeholders[1].text_frame
    tf.clear()
    p = tf.paragraphs[0]
    p.text = sections["summary"]
    _style_paragraph(p, size_pt=18)

    # 3–10 slides:
    _add_bullet_slide(prs, "Key Trends", sections["trends"])
    _add_bullet_slide(prs, "Market Insights", sections["insights"])
    _add_bullet_slide(prs, "Opportunities", sections["opportunities"])
    _add_bullet_slide(prs, "Risks", sections["risks"])

    comp_rows = [
        [_strip(c.get("name")), _strip(c.get("position")), _strip(c.get("notes"))]
        for c in sections["competitors"]
    ]
    _add_table_slide(prs, "Competitors / Actors",
                     ["Name", "Position", "Notes"], comp_rows)

    num_rows = [
        [_strip(n.get("metric")), _strip(n.get("value")), _strip(n.get("source"))]
        for n in sections["numbers"]
    ]
    _add_table_slide(prs, "Key Numbers",
                     ["Metric", "Value", "Source"], num_rows)

    rec_lines = []
    for r in sections["recommendations"]:
        pr = r.get("priority")
        prefix = f"{pr}) " if isinstance(pr, int) else ""
        line = f"{prefix}{_strip(r.get('action'))} — Why: {_strip(r.get('rationale'))}"
        rec_lines.append(line)
    _add_bullet_slide(prs, "Recommendations", rec_lines)

    _add_bullet_slide(prs, "Sources", sections["sources"], size=16)

    prs.save(file_path)
    return file_path

