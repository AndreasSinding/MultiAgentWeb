# -*- coding: utf-8 -*-
"""
ppt_builder.py — Full-deck builder for CrewAI (Option A)
--------------------------------------------------------

Builds a professional multi-slide PowerPoint deck by merging the outputs
from multiple CrewAI tasks (Research, Analysis, Executive Summary).

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

Safe for python-pptx: uses paragraph/run font properties (no p.font assignment).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple, Union

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN


# -------------------------------------------------------------------
# Utilities
# -------------------------------------------------------------------

def _safe_filename(base: str) -> str:
    if not base:
        return "report"
    return re.sub(r"[^A-Za-z0-9._\-]+", "_", base).strip("_") or "report"


def _strip(x: Any) -> str:
    return (x or "").strip()


def _coerce_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _dedupe_str_list(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for s in items:
        s2 = _strip(s)
        if s2 and s2 not in seen:
            seen.add(s2)
            out.append(s2)
    return out


def _dedupe_dict_list(items: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for d in items:
        sig = tuple(_strip(d.get(k, "")) for k in keys)
        if sig not in seen:
            seen.add(sig)
            out.append(d)
    return out

import json
from typing import List, Dict, Any

def _extract_json_objects(s: str) -> List[Dict[str, Any]]:
    """Extract JSON dicts from string s without recursive regex (Python-native)."""
    objs: List[Dict[str, Any]] = []
    if not isinstance(s, str):
        return objs

    # Try full-string JSON first.
    s1 = s.strip()
    if s1.startswith("{") and s1.endswith("}"):
        try:
            obj = json.loads(s1)
            if isinstance(obj, dict):
                objs.append(obj)
        except Exception:
            pass

    # Fallback: scan for {...} blocks using a brace counter.
    start = None
    depth = 0
    for i, ch in enumerate(s):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    block = s[start:i+1]
                    try:
                        obj = json.loads(block)
                        if isinstance(obj, dict):
                            objs.append(obj)
                    except Exception:
                        pass
                    start = None
    return objs
  
# -------------------------------------------------------------------
# JSON normalization and merging
# -------------------------------------------------------------------

def _norm_trend_item(t: Any) -> str | None:
    """
    Accept string or dict with title/evidence/why_it_matters|why → flatten to a line.
    """
    if isinstance(t, dict):
        title = _strip(t.get("title"))
        evidence = _strip(t.get("evidence"))
        why = _strip(t.get("why_it_matters") or t.get("why"))
        segs = [title, evidence, f"Why: {why}" if why else ""]
        line = " — ".join([s for s in segs if s])
        return line or None
    s = _strip(t)
    return s or None


def _norm_comp_item(c: Any) -> Dict[str, str] | None:
    if isinstance(c, dict):
        return {
            "name": _strip(c.get("name")),
            "position": _strip(c.get("position")),
            "notes": _strip(c.get("notes")),
        }
    s = _strip(c)
    if not s:
        return None
    return {"name": s, "position": "", "notes": ""}


def _norm_num_item(n: Any) -> Dict[str, str] | None:
    if isinstance(n, dict):
        return {
            "metric": _strip(n.get("metric")),
            "value": _strip(n.get("value")),
            "source": _strip(n.get("source")),
        }
    s = _strip(n)
    if not s:
        return None
    return {"metric": s, "value": "", "source": ""}


def _norm_rec_item(r: Any) -> Dict[str, Any] | None:
    if isinstance(r, dict):
        pr = r.get("priority")
        try:
            pr = int(pr) if pr is not None else None
        except Exception:
            pr = None
        return {
            "priority": pr,
            "action": _strip(r.get("action")),
            "rationale": _strip(r.get("rationale") or r.get("why")),
        }
    s = _strip(r)
    if not s:
        return None
    return {"priority": None, "action": s, "rationale": ""}


def _try_parse_json(s: str) -> Dict[str, Any] | None:
    s = s.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _normalize_struct(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a possibly heterogeneous JSON blob into our unified schema.
    Accepts variants/synonyms when present.
    """
    out = {
        "summary": _strip(obj.get("summary") or obj.get("executive_summary") or obj.get("summary_long")),
        "trends": [],
        "insights": [],
        "opportunities": [],
        "risks": [],
        "competitors": [],
        "numbers": [],
        "recommendations": [],
        "sources": [],
    }

    # Trends
    for t in _coerce_list(obj.get("trends")):
        line = _norm_trend_item(t)
        if line:
            out["trends"].append(line)

    # Analysis bits
    for z in _coerce_list(obj.get("insights")):
        s = _strip(z)
        if s:
            out["insights"].append(s)

    for z in _coerce_list(obj.get("opportunities")):
        s = _strip(z)
        if s:
            out["opportunities"].append(s)

    for z in _coerce_list(obj.get("risks")):
        s = _strip(z)
        if s:
            out["risks"].append(s)

    # Competitors
    for c in _coerce_list(obj.get("competitors") or obj.get("actors")):
        comp = _norm_comp_item(c)
        if comp:
            out["competitors"].append(comp)

    # Numbers
    for n in _coerce_list(obj.get("numbers") or obj.get("key_numbers")):
        num = _norm_num_item(n)
        if num:
            out["numbers"].append(num)

    # Recommendations
    for r in _coerce_list(obj.get("recommendations") or obj.get("actions")):
        rec = _norm_rec_item(r)
        if rec:
            out["recommendations"].append(rec)

    # Sources
    for s in _coerce_list(obj.get("sources") or obj.get("references")):
        ss = _strip(s)
        if ss:
            out["sources"].append(ss)

    return out


def _merge_struct_into(acc: Dict[str, Any], part: Dict[str, Any]) -> None:
    """
    Merge 'part' into 'acc' (deduping where appropriate).
    """
    # summary: prefer the longest non-empty
    s_acc = acc.get("summary", "")
    s_part = _strip(part.get("summary"))
    if s_part and (len(s_part) > len(s_acc)):
        acc["summary"] = s_part

    # simple lists
    for key in ("trends", "insights", "opportunities", "risks", "sources"):
        acc[key] = _dedupe_str_list(acc.get(key, []) + part.get(key, []))

    # dict lists
    for key, keys in (("competitors", ["name", "position", "notes"]),
                      ("numbers", ["metric", "value", "source"]),
                      ("recommendations", ["priority", "action", "rationale"])):
        acc[key] = _dedupe_dict_list(acc.get(key, []) + part.get(key, []), keys)


# -------------------------------------------------------------------
# Header block (fallback) — language agnostic
# -------------------------------------------------------------------

HEADER_KEYS = [
    "SUMMARY", "TRENDS", "INSIGHTS", "OPPORTUNITIES", "RISKS",
    "COMPETITORS", "NUMBERS", "RECOMMENDATIONS", "SOURCES"
]

def _parse_header_block(text: str) -> Dict[str, Any]:
    out = {
        "summary": "",
        "trends": [], "insights": [], "opportunities": [], "risks": [],
        "competitors": [], "numbers": [], "recommendations": [], "sources": []
    }
    cur: str | None = None
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        u = line.upper()
        if any(u.startswith(h) for h in HEADER_KEYS):
            if u.startswith("SUMMARY"): cur = "summary"
            elif u.startswith("TRENDS"): cur = "trends"
            elif u.startswith("INSIGHTS"): cur = "insights"
            elif u.startswith("OPPORTUNITIES"): cur = "opportunities"
            elif u.startswith("RISKS"): cur = "risks"
            elif u.startswith("COMPETITORS"): cur = "competitors"
            elif u.startswith("NUMBERS"): cur = "numbers"
            elif u.startswith("RECOMMENDATIONS"): cur = "recommendations"
            elif u.startswith("SOURCES"): cur = "sources"
            continue

        if not cur:
            continue
        if cur == "summary":
            out["summary"] += line + " "
        else:
            out[cur].append(line[2:].strip() if line.startswith("- ") else line)

    out["summary"] = out["summary"].strip()
    return out


# -------------------------------------------------------------------
# Coalesce entire result → unified sections dict
# -------------------------------------------------------------------

def _coalesce_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge all task outputs:
      - Parse and merge ALL JSON objects found anywhere in tasks/summary blocks
      - Use header fallback only if at least two distinct headers detected
      - Finally, bulletize any free text as 'trends' if still empty
    """
    data = result["result"] if isinstance(result.get("result"), dict) else result

    text_blocks: List[str] = []
    summaries: List[str] = []

    for k in ("executive_summary", "summary", "summary_long"):
        v = _strip(data.get(k))
        if v:
            summaries.append(v)
    if _strip(data.get("raw")):
        summaries.append(_strip(data["raw"]))

    for blk in _coerce_list(data.get("tasks_output")):
        if isinstance(blk, dict):
            for key in ("raw", "content", "text"):
                s = _strip(blk.get(key))
                if s:
                    text_blocks.append(s)

    merged = {
        "summary": "",
        "trends": [], "insights": [], "opportunities": [], "risks": [],
        "competitors": [], "numbers": [], "recommendations": [], "sources": []
    }

    # 1) Parse and merge ALL JSON objects from all blocks
    found_any_json = False
    for s in text_blocks + summaries:
        for obj in _extract_json_objects(s):
            found_any_json = True
            _merge_struct_into(merged, _normalize_struct(obj))

    # 2) Header fallback only if we truly detect headers
    combined = "\n\n".join(summaries + text_blocks).strip()
    def _count_headers(txt: str) -> int:
        cnt = 0
        up = txt.upper()
        for h in HEADER_KEYS:
            # require header + colon somewhere
            if (h + ":") in up:
                cnt += 1
        return cnt

    if combined and _count_headers(combined) >= 2:
        hdr = _parse_header_block(combined)
        _merge_struct_into(merged, hdr)

    # 3) Final fallbacks
    if not merged["summary"]:
        merged["summary"] = _strip(" ".join(summaries)) or "No summary available."

    if not any(merged[k] for k in ("trends", "insights", "opportunities", "risks",
                                   "competitors", "numbers", "recommendations", "sources")):
        lines = [ln.strip("-• \t ") for ln in merged["summary"].split("\n") if ln.strip()]
        merged["trends"] = lines[:8]

    # trim for readability
    merged["trends"] = merged["trends"][:10]
    merged["insights"] = merged["insights"][:10]
    merged["opportunities"] = merged["opportunities"][:10]
    merged["risks"] = merged["risks"][:10]
    merged["competitors"] = merged["competitors"][:20]
    merged["numbers"] = merged["numbers"][:20]
    merged["recommendations"] = merged["recommendations"][:10]
    merged["sources"] = merged["sources"][:20]

    return merged


# -------------------------------------------------------------------
# PPT helpers (safe font styling)
# -------------------------------------------------------------------

def _style_paragraph(p, size_pt: int = 18, family: str = "Segoe UI"):
    # Paragraph default (safe to set properties)
    try:
        p.font.size = Pt(size_pt)
        p.font.name = family
    except Exception:
        pass
    # Enforce on runs (robust across themes)
    for r in p.runs:
        try:
            r.font.size = Pt(size_pt)
            r.font.name = family
        except Exception:
            pass


def _add_bullet_slide(prs: Presentation, title: str, bullets: List[str], size: int = 18):
    slide = prs.slides.add_slide(prs.slide_layouts[1])  # Title and Content
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


def _add_table_slide(prs: Presentation, title: str, headers: List[str], rows: List[List[str]]):
    slide = prs.slides.add_slide(prs.slide_layouts[5])  # Title Only
    slide.shapes.title.text = title

    left, top, width, height = Inches(0.6), Inches(1.6), Inches(9.2), Inches(0.8)
    n_rows = max(2, 1 + len(rows))
    n_cols = len(headers)

    table = slide.shapes.add_table(n_rows, n_cols, left, top, width, height).table

    # header row
    for j, h in enumerate(headers):
        cell = table.cell(0, j)
        cell.text = h
        for p in cell.text_frame.paragraphs:
            p.font.bold = True
            p.font.size = Pt(14)
            p.alignment = PP_ALIGN.LEFT

    if rows:
        for i, r in enumerate(rows[: n_rows - 1], start=1):
            for j in range(n_cols):
                cell = table.cell(i, j)
                cell.text = str(r[j]) if j < len(r) else ""
                for p in cell.text_frame.paragraphs:
                    p.font.size = Pt(12)
    else:
        table.cell(1, 0).text = "No structured data available."


# -------------------------------------------------------------------
# PUBLIC API
# -------------------------------------------------------------------

def create_multislide_pptx(result: Dict[str, Any], topic: str, file_path: str) -> str:
    """
    Build a full Option-A deck using all Crew outputs.
    """
    sections = _coalesce_result(result)

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
    p.text = sections["summary"] or "No summary available."
    _style_paragraph(p, size_pt=18)

    # 3) Key Trends
    _add_bullet_slide(prs, "Key Trends", sections.get("trends", []), size=18)

    # 4) Market Insights
    _add_bullet_slide(prs, "Market Insights", sections.get("insights", []), size=18)

    # 5) Opportunities
    _add_bullet_slide(prs, "Opportunities", sections.get("opportunities", []), size=18)

    # 6) Risks
    _add_bullet_slide(prs, "Risks", sections.get("risks", []), size=18)

    # 7) Competitors / Actors (table)
    comp_rows: List[List[str]] = []
    for c in _coerce_list(sections.get("competitors")):
        if isinstance(c, dict):
            comp_rows.append([_strip(c.get("name")), _strip(c.get("position")), _strip(c.get("notes"))])
        else:
            s = _strip(c)
            comp_rows.append([s, "", ""])
    _add_table_slide(prs, "Competitors / Actors", ["Name", "Position", "Notes"], comp_rows)

    # 8) Key Numbers (table)
    num_rows: List[List[str]] = []
    for n in _coerce_list(sections.get("numbers")):
        if isinstance(n, dict):
            num_rows.append([_strip(n.get("metric")), _strip(n.get("value")), _strip(n.get("source"))])
        else:
            s = _strip(n)
            num_rows.append([s, "", ""])
    _add_table_slide(prs, "Key Numbers", ["Metric", "Value", "Source"], num_rows)

    # 9) Recommendations
    rec_lines: List[str] = []
    for r in _coerce_list(sections.get("recommendations")):
        if isinstance(r, dict):
            pr = r.get("priority")
            pr_str = f"{pr}) " if isinstance(pr, int) else ""
            line = f"{pr_str}{_strip(r.get('action'))} — Why: {_strip(r.get('rationale'))}".strip(" —")
            if line:
                rec_lines.append(line)
        else:
            s = _strip(r)
            if s:
                rec_lines.append(s)
    _add_bullet_slide(prs, "Recommendations", rec_lines, size=18)

    # 10) Sources
    _add_bullet_slide(prs, "Sources", _coerce_list(sections.get("sources")), size=16)

    # Save
    prs.save(file_path)
    return file_path
