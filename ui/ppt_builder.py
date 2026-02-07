# -*- coding: utf-8 -*-
"""
ppt_builder.py – BUILDER WITH NO JSON 

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
    return re.sub(r'[^A-Za-z0-9._-]+', '_', base).strip('_') or "report"

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


# --- Markdown-first extraction (with JSON as bonus) --------------------------
import re, json
from typing import Any, Dict, List

SECTION_MAP_NO = {
    "sammendrag": "summary",
    "trender": "trends",
    "innsikt": "insights",
    "muligheter": "opportunities",
    "risiko": "risks",
    "aktører / konkurrenter": "competitors",
    "aktorer / konkurrenter": "competitors",  # fallback ascii
    "nøkkeltall": "numbers",
    "nokkelstall": "numbers",  # fallback ascii
    "anbefalinger": "recommendations",
    "kilder": "sources",
}
SECTION_KEYS_EN = ["summary","trends","insights","opportunities","risks",
                   "competitors","numbers","recommendations","sources"]

def _extract_all_json_blocks(tasks_output: List[Dict[str, Any]], also_consider: List[Any] = None) -> Dict[str, Any]:
    merged = {k: ([] if k!="summary" else "") for k in SECTION_KEYS_EN}
    candidates: List[str] = []

    # Collect possible text sources
    for blk in tasks_output or []:
        for key in ("raw","content","text","final_output"):
            s = blk.get(key)
            if isinstance(s, str) and s.strip():
                candidates.append(s)
        if isinstance(blk.get("artifacts"), list):
            for a in blk["artifacts"]:
                if isinstance(a, dict):
                    for k in ("content","text","raw"):
                        v = a.get(k)
                        if isinstance(v, str) and v.strip():
                            candidates.append(v)

    for extra in also_consider or []:
        if isinstance(extra, str) and extra.strip():
            candidates.append(extra)

    # 1) Try strict JSON first (keeps compatibility)
    for s in candidates:
        ss = s.strip()
        if (ss.startswith("{") and ss.endswith("}")) or (ss.startswith("[") and ss.endswith("]")):
            try:
                obj = json.loads(ss)
                _merge_any_json_into(merged, obj)
                continue
            except Exception:
                pass
        for obj in _brace_scan_json(ss):
            _merge_any_json_into(merged, obj)

    # 2) Markdown-first parsing (Norwegian headings)
    for s in candidates:
        _extract_from_markdown_no(merged, s)

    # 3) URLs anywhere -> sources
    urls = _find_urls(" \n".join(candidates))
    for u in urls:
        if u not in merged["sources"]:
            merged["sources"].append(u)

    return merged

def _merge_json_into(merged: Dict[str, Any], obj: Dict[str, Any]) -> None:
    """Merge JSON dict from agent into main structure."""
    # NEW: Early-app compatibility: nested 'research' object
    if isinstance(obj.get("research"), dict):
        _merge_research_block(merged, obj["research"])

    # Summary (prefer longest)
    if "summary" in obj:
        s = _strip(obj.get("summary"))
        if s and len(s) > len(merged["summary"]):
            merged["summary"] = s

    # Simple list fields (strings)
    for key in ("trends", "insights", "opportunities", "risks", "sources"):
        val = obj.get(key)
        # Accept both strings and dicts for trends (dicts will be formatted)
        if key == "trends" and isinstance(val, list) and all(isinstance(x, dict) for x in val):
            # Convert dict trends using the same formatter as research
            _merge_research_block(merged, {"trends": val})
        else:
            for item in _coerce_list(val):
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


def _merge_any_json_into(merged: Dict[str, Any], obj: Any) -> None:
    if isinstance(obj, dict):
        _merge_json_into(merged, obj)
        return
    if isinstance(obj, list):
        if all(isinstance(x, str) for x in obj):
            for x in obj:
                x = _strip(x)
                if x and x not in merged["insights"]:
                    merged["insights"].append(x)
        elif all(isinstance(x, dict) for x in obj):
            for item in obj:
                _merge_dict_like(merged, item)

def _merge_dict_like(merged: Dict[str, Any], item: Dict[str, Any]) -> None:
    keys = {k.lower() for k in item.keys()}
    if {"name","position"} <= keys:
        merged["competitors"].append({
            "name": _strip(item.get("name")),
            "position": _strip(item.get("position")),
            "notes": _strip(item.get("notes"))
        })
    elif {"metric","value"} <= keys:
        merged["numbers"].append({
            "metric": _strip(item.get("metric")),
            "value": _strip(item.get("value")),
            "source": _strip(item.get("source"))
        })
    elif {"priority","action"} <= keys:
        merged["recommendations"].append({
            "priority": item.get("priority"),
            "action": _strip(item.get("action")),
            "rationale": _strip(item.get("rationale")),
        })
    else:
        s = _strip("; ".join(f"{k}: {v}" for k, v in item.items()))
        if s and s not in merged["insights"]:
            merged["insights"].append(s)

def _brace_scan_json(text: str) -> List[Any]:
    objs, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0: start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                block = text[start:i+1]
                try:
                    objs.append(json.loads(block))
                except Exception:
                    pass
                start = None
    return objs

def _extract_from_markdown_no(merged: Dict[str, Any], s: str) -> None:
    lines = [ln.rstrip() for ln in (s or "").splitlines()]
    current = None
    buf: List[str] = []

    def flush():
        nonlocal buf, current
        if not current or not buf:
            buf = []; return
        key = SECTION_MAP_NO.get(current, None)
        if not key:
            buf = []; return

        if key in ("trends","insights","opportunities","risks","sources"):
            for it in buf:
                val = _strip(_drop_bullet(it))
                if val and val not in merged[key]:
                    merged[key].append(val)

        elif key == "competitors":
            for it in buf:
                name, pos, note = _split3(_drop_bullet(it))
                merged["competitors"].append({"name": name, "position": pos, "notes": note})

        elif key == "numbers":
            for it in buf:
                metric, value, source = _split3(_drop_bullet(it))
                merged["numbers"].append({"metric": metric, "value": value, "source": source})

        elif key == "recommendations":
             clean = [_drop_bullet(x) for x in buf]
             prio, action, why = _split_recommendation(clean)
             for i, (p, a, w) in enumerate(zip(prio, action, why), start=1):
                merged["recommendations"].append({"priority": p or i, "action": a, "rationale": w})
                buf = []

    # Simple header detection: lines that start with '#' or are exact section names
    for ln in lines:
        ln_clean = ln.strip()
        ln_lower = ln_clean.lower().rstrip(":")
        if ln_clean.startswith("#"):
            # Markdown header: take content without '#'
            header = ln_clean.lstrip("# ").lower().rstrip(":")
            if header in SECTION_MAP_NO:
                flush(); current = header; buf = []; continue
        # Support bare headings too
        if ln_lower in SECTION_MAP_NO:
            flush(); current = ln_lower; buf = []; continue

        # Accumulate bullets/paragraphs
        if current:
            if re.match(r'^(\-|\*|•|\d+[.)])\s+', ln_clean) or ln_clean:
                buf.append(ln_clean)

    flush()

def _drop_bullet(s: str) -> str:
    # Remove common bullet markers: -, *, •, "1.", "1)"
    return re.sub(r'^(\-|\*|•|\d+[.)])\s+', '', s).strip()

def _find_urls(s: str) -> List[str]:
    # Simple URL matcher
    return re.findall(r'(https?://[^\s)]+)', s or '')

def _split3(s: str):
    """
    Split a line like:
      "A – B – C" or "A - B - C" or "A | B | C" or "A; B; C" or "A: B: C"
    into 3 fields. Excess separators in notes are tolerated.
    """
    parts = re.split(r'\s+[–\-|;:]\s+', s, maxsplit=2)
    parts += ["", "", ""]
    return _strip(parts[0]), _strip(parts[1]), _strip(parts[2])

def _split_recommendation(items: List[str]):
    """
    Parse lines like:
      "[Prioritet 1] Handling — Hvorfor"
      "Handling — Hvorfor"
    Returns lists for prio, action, why (same length).
    """
    prio, act, why = [], [], []
    for it in items:
        m = re.match(r'^\[?\s*prioritet\s*(\d+)\s*\]?\s*(.+?)(?:\s+[—-]\s+(.+))?$', it, flags=re.I)
        if m:
            prio.append(int(m.group(1)))
            act.append(_strip(m.group(2)))
            why.append(_strip(m.group(3) or ''))
        else:
            prio.append(None)
            segs = re.split(r'\s+[—-]\s+', it, maxsplit=1)
            act.append(_strip(segs[0]))
            why.append(_strip(segs[1] if len(segs) > 1 else ''))
    return prio, act, why
##########################

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

 
    also_consider = []
    for k in ("summary", "final_output", "raw", "content", "text"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            also_consider.append(v)

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

