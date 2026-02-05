# -*- coding: utf-8 -*-
"""
ppt_builder.py — FINAL VERSION for Azure CrewAI pipeline
--------------------------------------------------------

This version replaces ALL older builder logic.

It supports:
1. Structured JSON (preferred)
2. Header-marked text (SUMMARY:, TRENDS:, etc.)
3. Free-text fallback → bullets

It outputs:
- Title slide
- Executive Summary
- Key Trends
- Competitors / Actors (table)
- Key Numbers (table)
- Recommendations
- Sources

Author: Andreas' Copilot (final stable version)
"""

from __future__ import annotations
import json
import re
from typing import Any, Dict, List, Tuple, Union

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN

# ------------------------------------------------------------
# Utility
# ------------------------------------------------------------

def _safe_filename(base: str) -> str:
    if not base:
        return "report"
    safe = re.sub(r"[^A-Za-z0-9._\-]+", "_", base).strip("_")
    return safe or "report"


def _strip(x: Any) -> str:
    return (x or "").strip()


def _coerce_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


# ------------------------------------------------------------
# 1. Structured JSON → section dict
# ------------------------------------------------------------

def try_parse_json_block(s: str) -> Dict[str, Any] | None:
    s = s.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def normalize_json_sections(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize JSON into clean section schema."""
    out = {
        "summary": _strip(obj.get("summary")),
        "trends": [],
        "competitors": [],
        "numbers": [],
        "recommendations": [],
        "sources": [],
    }

    # Trends
    for t in _coerce_list(obj.get("trends")):
        if isinstance(t, dict):
            title = _strip(t.get("title"))
            evidence = _strip(t.get("evidence"))
            why = _strip(t.get("why_it_matters") or t.get("why"))
            segs = [title, evidence, f"Why: {why}" if why else ""]
            line = " — ".join([x for x in segs if x])
            if line:
                out["trends"].append(line)
        else:
            t = _strip(t)
            if t:
                out["trends"].append(t)

    # Competitors
    for c in _coerce_list(obj.get("competitors")):
        if isinstance(c, dict):
            out["competitors"].append({
                "name": _strip(c.get("name")),
                "position": _strip(c.get("position")),
                "notes": _strip(c.get("notes")),
            })
        else:
            s = _strip(c)
            out["competitors"].append({
                "name": s,
                "position": "",
                "notes": "",
            })

    # Numbers
    for n in _coerce_list(obj.get("numbers")):
        if isinstance(n, dict):
            out["numbers"].append({
                "metric": _strip(n.get("metric")),
                "value": _strip(n.get("value")),
                "source": _strip(n.get("source")),
            })
        else:
            s = _strip(n)
            out["numbers"].append({"metric": s, "value": "", "source": ""})

    # Recommendations
    for r in _coerce_list(obj.get("recommendations")):
        if isinstance(r, dict):
            pr = r.get("priority")
            try:
                pr = int(pr)
            except:
                pr = None
            out["recommendations"].append({
                "priority": pr,
                "action": _strip(r.get("action")),
                "rationale": _strip(r.get("rationale") or r.get("why")),
            })
        else:
            s = _strip(r)
            out["recommendations"].append({"priority": None, "action": s, "rationale": ""})

    # Sources
    for s in _coerce_list(obj.get("sources")):
        ss = _strip(s)
        if ss:
            out["sources"].append(ss)

    return out


# ------------------------------------------------------------
# 2. Header-block parser (SUMMARY:, TRENDS:, etc.)
# ------------------------------------------------------------

HEADER_KEYS = ["SUMMARY", "TRENDS", "COMPETITORS", "NUMBERS", "RECOMMENDATIONS", "SOURCES"]

def parse_header_block(text: str) -> Dict[str, Any]:
    out = {
        "summary": "",
        "trends": [],
        "competitors": [],
        "numbers": [],
        "recommendations": [],
        "sources": [],
    }

    current = None
    lines = text.replace("\r", "").split("\n")

    def add(key, line):
        if key == "summary":
            out["summary"] += line + " "
        else:
            out[key].append(line)

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        u = line.upper()

        # Identify header
        if any(u.startswith(h) for h in HEADER_KEYS):
            if u.startswith("SUMMARY"):
                current = "summary"
            elif u.startswith("TRENDS"):
                current = "trends"
            elif u.startswith("COMPETITORS"):
                current = "competitors"
            elif u.startswith("NUMBERS"):
                current = "numbers"
            elif u.startswith("RECOMMENDATIONS"):
                current = "recommendations"
            elif u.startswith("SOURCES"):
                current = "sources"
            continue

        if current:
            if line.startswith("- "):
                add(current, line[2:].strip())
            else:
                add(current, line)

    out["summary"] = out["summary"].strip()
    return out


# ------------------------------------------------------------
# 3. Result coalescing logic
# ------------------------------------------------------------

def coalesce_result(result: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Try structured JSON → header blocks → fallback bullets.
    """

    # CrewAI wraps result under "result"
    if "result" in result and isinstance(result["result"], dict):
        data = result["result"]
    else:
        data = result

    summary_candidates = []
    blocks = []

    # explicit summary if available
    for k in ("summary", "exec_summary", "executive_summary"):
        if _strip(data.get(k)):
            summary_candidates.append(_strip(data.get(k)))

    # fallback to raw
    if _strip(data.get("raw")):
        summary_candidates.append(_strip(data["raw"]))

    # tasks_output collection
    for blk in _coerce_list(data.get("tasks_output")):
        if isinstance(blk, dict):
            for key in ("raw", "content", "text"):
                if _strip(blk.get(key)):
                    blocks.append(_strip(blk.get(key)))

    # 1) Try JSON first
    for part in blocks + summary_candidates:
        js = try_parse_json_block(part)
        if js:
            parsed = normalize_json_sections(js)
            summary = parsed["summary"] or " ".join(summary_candidates)
            return summary, parsed

    # 2) Try header blocks
    combined = "\n\n".join(summary_candidates + blocks).strip()
    if combined:
        hdr = parse_header_block(combined)
        if any(hdr[k] for k in hdr):
            summary = hdr["summary"] or (summary_candidates[0] if summary_candidates else "")
            return summary, hdr

    # 3) Fallback
    fallback = " ".join(summary_candidates).strip() or "No summary available."
    lines = [ln.strip("-• \t") for ln in fallback.split("\n") if ln.strip()]
    bullets = lines[:8]
    return fallback, {
        "summary": fallback,
        "trends": bullets,
        "competitors": [],
        "numbers": [],
        "recommendations": [],
        "sources": [],
    }


# ------------------------------------------------------------
# 4. PPT creation helpers
# ------------------------------------------------------------

def _add_bullet_slide(prs: Presentation, title: str, bullets: List[str], size=18):
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title
    tf = slide.placeholders[1].text_frame
    tf.clear()

    if not bullets:
        tf.text = "No data available."
        return

    for i, line in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.level = 0
        for run in p.runs:
            run.font.size = Pt(size)
            run.font.name = "Segoe UI"


def _add_table_slide(prs: Presentation, title: str, headers: List[str], rows: List[List[str]]):
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = title

    left = Inches(0.5)
    top = Inches(1.5)
    width = Inches(9)

    row_count = max(2, 1 + len(rows))
    col_count = len(headers)

    table = slide.shapes.add_table(row_count, col_count, left, top, width, Inches(0.8)).table

    # header row
    for i, h in enumerate(headers):
        cell = table.cell(0, i)
        cell.text = h
        for p in cell.text_frame.paragraphs:
            p.font.bold = True
            p.font.size = Pt(14)

    # rows
    if rows:
        for idx, row in enumerate(rows, start=1):
            for j in range(col_count):
                table.cell(idx, j).text = row[j] if j < len(row) else ""
    else:
        table.cell(1, 0).text = "No structured data available."


# ------------------------------------------------------------
# 5. PUBLIC API: create_multislide_pptx
# ------------------------------------------------------------

def create_multislide_pptx(result: Dict[str, Any], topic: str, file_path: str) -> str:
    summary, sections = coalesce_result(result)

    prs = Presentation()

    # ---- Title slide
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    slide.shapes.title.text = "Multi‑Agent Insights Report"
    slide.placeholders[1].text = topic

   # --- Executive Summary
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Executive Summary"
    
    tf = slide.placeholders[1].text_frame
    tf.clear()
    
    p = tf.paragraphs[0]
    p.text = summary or "No summary available."
    
    # --- SAFE FONT STYLING ---
    # Paragraph-level defaults (allowed)
    try:
        p.font.size = Pt(18)
        p.font.name = "Segoe UI"
    except Exception:
        pass

    # Ensure all runs get the proper formatting
    for run in p.runs:
        try:
            run.font.size = Pt(18)
            run.font.name = "Segoe UI"
        except Exception:
            pass

    # ---- Trends
    _add_bullet_slide(prs, "Key Trends", sections.get("trends", [])[:8])

    # ---- Competitors
    comp_rows = []
    for c in sections.get("competitors", []):
        if isinstance(c, dict):
            comp_rows.append([
                _strip(c.get("name")),
                _strip(c.get("position")),
                _strip(c.get("notes")),
            ])
        else:
            s = _strip(c)
            comp_rows.append([s, "", ""])
    _add_table_slide(prs, "Competitors / Actors", ["Name", "Position", "Notes"], comp_rows)

    # ---- Numbers
    num_rows = []
    for n in sections.get("numbers", []):
        if isinstance(n, dict):
            num_rows.append([
                _strip(n.get("metric")),
                _strip(n.get("value")),
                _strip(n.get("source")),
            ])
        else:
            s = _strip(n)
            num_rows.append([s, "", ""])
    _add_table_slide(prs, "Key Numbers", ["Metric", "Value", "Source"], num_rows)

    # ---- Recommendations
    rec_lines = []
    for r in sections.get("recommendations", []):
        if isinstance(r, dict):
            pr = r.get("priority")
            pr_str = f"{pr}) " if isinstance(pr, int) else ""
            line = f"{pr_str}{_strip(r.get('action'))} — Why: {_strip(r.get('rationale'))}"
            rec_lines.append(line.strip(" —"))
        else:
            rec_lines.append(str(r))
    _add_bullet_slide(prs, "Recommendations", rec_lines[:8])

    # ---- Sources
    _add_bullet_slide(prs, "Sources", sections.get("sources", [])[:12])

    # Save
    prs.save(file_path)
    return file_path
