# -*- coding: utf-8 -*-
"""
ppt_builder.py — Stable deck builder for CrewAI multi-agent output
- Handles JSON + Markdown (EN + NO)
- Robust extraction of trends, insights, opportunities, risks, competitors, numbers, recommendations, sources
- Compatible with Exa search results; safe even if only free text is present
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple, Optional

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN

# --------------------------------------------------------------------
# Simple, safe regex patterns
# --------------------------------------------------------------------
BULLET = re.compile(r'^\s*[-*•]\s+')  # basic bullet removal

# fenced code block with optional "json" language tag
FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", flags=re.S | re.I)

URL_PATTERN = re.compile(r"(https?://[^\s)]+)")

# --------------------------------------------------------------------
# Safe Utilities
# --------------------------------------------------------------------
def _strip(x: Any) -> str:
    if x is None:
        return ""
    return str(x).strip()

def _coerce_list(x: Any) -> List[Any]:
    if x is None:
        return []
    return list(x) if isinstance(x, list) else [x]

def _safe_json_loads(s: str):
    try:
        return json.loads(s), None
    except Exception as e:
        return None, e

def _preclean_near_json(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.strip()
    # Remove fenced code blocks (handled separately by FENCE already)
    s = FENCE.sub(lambda m: m.group(1), s)
    # Remove basic bullets
    lines = [BULLET.sub("", ln) for ln in s.splitlines()]
    return "\n".join(lines).strip()

def _collect_strings_deep(obj: Any, limit: int = 20_000) -> List[str]:
    out = []
    def walk(x):
        if isinstance(x, str):
            if x.strip():
                out.append(x.strip())
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    seen, res, total = set(), [], 0
    for s in out:
        if s not in seen:
            seen.add(s)
            res.append(s)
            total += len(s)
            if total > limit:
                break
    return res

def _drop_bullet(s: str) -> str:
    return BULLET.sub("", s or "").strip()

def _find_urls(s: str) -> List[str]:
    return URL_PATTERN.findall(s or "")

def _split3(s: str) -> Tuple[str, str, str]:
    parts = [p.strip() for p in re.split(r"\s*[-–:;]\s*", s or "", maxsplit=2)]
    parts += ["", "", ""]
    return _strip(parts[0]), _strip(parts[1]), _strip(parts[2])

def _split_recommendation(items: List[str]) -> Tuple[List[Optional[int]], List[str], List[str]]:
    prio, act, why = [], [], []
    for it in items:
        # e.g., "[Prioritet 2] Action — Reason"
        m = re.match(r"^\[?\s*prioritet\s*(\d+)\s*\]?\s*(.+?)(?:\s*[–-]\s*(.+))?$", it, flags=re.I)
        if m:
            prio.append(int(m.group(1)))
            act.append(_strip(m.group(2)))
            why.append(_strip(m.group(3) or ""))
        else:
            segs = re.split(r"\s*[–-]\s*", it, maxsplit=1)
            act.append(_strip(segs[0]))
            why.append(_strip(segs[1] if len(segs) > 1 else ""))
            prio.append(None)
    return prio, act, why

# --------------------------------------------------------------------
# Section Maps
# --------------------------------------------------------------------
SECTION_MAP_NO = {
    "sammendrag": "summary",
    "trender": "trends",
    "nøkkelpunkter": "trends",
    "hovedfunn": "insights",
    "innsikt": "insights",
    "muligheter": "opportunities",
    "risiko": "risks",
    "aktører / konkurrenter": "competitors",
    "aktorer / konkurrenter": "competitors",
    "nøkkeltall": "numbers",
    "nokkelstall": "numbers",
    "anbefalinger": "recommendations",
    "kilder": "sources",
}
SECTION_MAP_EN = {
    "executive summary": "summary",
    "key trends": "trends",
    "key points": "trends",
    "highlights": "trends",
    "findings": "insights",
    "market insights": "insights",
    "opportunities": "opportunities",
    "risks": "risks",
    "competitors": "competitors",
    "competitors / actors": "competitors",
    "key numbers": "numbers",
    "recommendations": "recommendations",
    "sources": "sources",
}
SECTION_KEYS = [
    "summary",
    "trends",
    "insights",
    "opportunities",
    "risks",
    "competitors",
    "numbers",
    "recommendations",
    "sources",
]

# --------------------------------------------------------------------
# Extract Outputs
# --------------------------------------------------------------------
def _dig_outputs(result: Any):
    data = result
    if isinstance(result, dict) and isinstance(result.get("result"), dict):
        data = result["result"]

    tasks_output = []
    if isinstance(data, dict):
        tasks_output = (
            data.get("tasks_output")
            or data.get("tasks")
            or []
        )

    # Include the final agent answer as a pseudo-task
    if isinstance(data, dict):
        final_answer = data.get("final_output") or data.get("raw") or data.get("text") or data.get("content")
        if isinstance(final_answer, str):
            tasks_output = tasks_output + [{"content": final_answer}]
        elif isinstance(final_answer, dict):
            tasks_output = tasks_output + [{"result": final_answer}]
    return data, tasks_output

def _brace_scan_json(text: str) -> List[Any]:
    objs, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                block = text[start:i + 1]
                try:
                    objs.append(json.loads(block))
                except Exception:
                    pass
                start = None
    return objs

# --------------------------------------------------------------------
# Markdown extraction (unified EN/NO)
# --------------------------------------------------------------------
def _extract_from_markdown(merged: Dict[str, Any], s: str) -> None:
    lines = [ln.rstrip() for ln in (s or "").splitlines()]
    if not lines:
        return

    def norm_header(h: str) -> Optional[str]:
        x = h.strip().lower().rstrip(":")
        return SECTION_MAP_NO.get(x) or SECTION_MAP_EN.get(x)

    current = None
    buf: List[str] = []

    def flush():
        nonlocal buf, current
        if not current or not buf:
            buf = []
            return
        key = current
        cleaned = [_drop_bullet(x) for x in buf]
        if key in ("trends", "insights", "opportunities", "risks", "sources"):
            merged[key].extend([x for x in cleaned if x])
        elif key == "competitors":
            for x in cleaned:
                a, b, c = _split3(x)
                merged["competitors"].append({"name": a, "position": b, "notes": c})
        elif key == "numbers":
            for x in cleaned:
                a, b, c = _split3(x)
                merged["numbers"].append({"metric": a, "value": b, "source": c})
        elif key == "recommendations":
            prio, act, why = _split_recommendation(cleaned)
            for i, (p, a, w) in enumerate(zip(prio, act, why), 1):
                merged["recommendations"].append({"priority": p or i, "action": a, "rationale": w})
        elif key == "summary":
            text = " ".join(cleaned).strip()
            if len(text) > len(merged["summary"]):
                merged["summary"] = text
        buf = []

    for raw in lines:
        ln = raw.strip()
        if not ln:
            continue

        # Markdown heading like "# Executive Summary"
        if ln.startswith("#"):
            h = ln.lstrip("# ").strip()
            canon = norm_header(h)
            if canon:
                flush()
                current = canon
                buf = []
                continue

        # Plain line that is exactly a section header (e.g., "Risks:")
        h2 = ln.lower().rstrip(":")
        canon = norm_header(h2)
        if canon:
            flush()
            current = canon
            buf = []
            continue

        # Accumulate content lines for the current section
        if current:
            buf.append(ln)

    flush()

# --------------------------------------------------------------------
# JSON Normalization / Merging
# --------------------------------------------------------------------
def _merge_research_block(merged: Dict[str, Any], research: Dict[str, Any]):
    # Trends
    tr = research.get("trends")
    if isinstance(tr, list):
        for t in tr:
            if isinstance(t, dict):
                title = _strip(t.get("title") or t.get("name"))
                why = _strip(t.get("why_it_matters") or t.get("detail") or t.get("summary"))
                ev = _strip(t.get("evidence"))
                line = f"{title} — {why}".strip(" —")
                if ev:
                    line += f" (evidence: {ev})"
                if line:
                    merged["trends"].append(line)

    # Numbers
    nums = research.get("numbers") or research.get("metrics")
    if isinstance(nums, list):
        for n in nums:
            if isinstance(n, dict):
                merged["numbers"].append(
                    {
                        "metric": _strip(n.get("metric") or n.get("name")),
                        "value": _strip(n.get("value") or n.get("val")),
                        "source": _strip(n.get("source") or n.get("url")),
                    }
                )

    # Competitors / actors
    comps = research.get("competitors") or research.get("actors")
    if isinstance(comps, list):
        for c in comps:
            if isinstance(c, dict):
                merged["competitors"].append(
                    {
                        "name": _strip(c.get("name")),
                        "position": _strip(c.get("position") or c.get("role") or ""),
                        "notes": _strip(c.get("notes") or c.get("summary") or ""),
                    }
                )

    # Simple list sections
    for k in ("insights", "opportunities", "risks", "sources"):
        for item in _coerce_list(research.get(k)):
            s = _strip(item)
            if s:
                merged[k].append(s)

    # Recommendations
    if isinstance(research.get("recommendations"), list):
        for r in research["recommendations"]:
            if isinstance(r, dict):
                merged["recommendations"].append(
                    {
                        "priority": r.get("priority"),
                        "action": _strip(r.get("action") or r.get("what")),
                        "rationale": _strip(r.get("rationale") or r.get("why")),
                    }
                )

def _merge_json_into(merged: Dict[str, Any], obj: Dict[str, Any]) -> None:
    if isinstance(obj.get("research"), dict):
        _merge_research_block(merged, obj["research"])

    if "summary" in obj:
        s = _strip(obj.get("summary"))
        if len(s) > len(merged["summary"]):
            merged["summary"] = s

    for key in ("trends", "insights", "opportunities", "risks", "sources"):
        for item in _coerce_list(obj.get(key)):
            s = _strip(item)
            if s:
                merged[key].append(s)

    for comp in _coerce_list(obj.get("competitors")):
        if isinstance(comp, dict):
            merged["competitors"].append(
                {"name": _strip(comp.get("name")), "position": _strip(comp.get("position")), "notes": _strip(comp.get("notes"))}
            )

    for n in _coerce_list(obj.get("numbers")):
        if isinstance(n, dict):
            merged["numbers"].append(
                {"metric": _strip(n.get("metric")), "value": _strip(n.get("value")), "source": _strip(n.get("source"))}
            )

    for r in _coerce_list(obj.get("recommendations")):
        if isinstance(r, dict):
            merged["recommendations"].append(
                {"priority": r.get("priority"), "action": _strip(r.get("action")), "rationale": _strip(r.get("rationale"))}
            )

# --------------------------------------------------------------------
# Main JSON/Markdown Extractor
# --------------------------------------------------------------------
def _extract_all_json_blocks(tasks_output, also_consider=None):
    merged = {k: ([] if k != "summary" else "") for k in SECTION_KEYS}
    candidates = []

    # Collect candidate strings
    for blk in tasks_output or []:
        if isinstance(blk, dict):
            for key in ("raw", "content", "text", "final_output", "result", "output", "message"):
                s = blk.get(key)
                if isinstance(s, str) and s.strip():
                    candidates.append(s)
                elif isinstance(s, (dict, list)):
                    candidates.extend(_collect_strings_deep(s))
        # artifacts—optional
        if isinstance(blk, dict) and isinstance(blk.get("artifacts"), list):
            for a in blk["artifacts"]:
                if isinstance(a, dict):
                    for k in ("content", "text", "raw", "result"):
                        v = a.get(k)
                        if isinstance(v, str):
                            candidates.append(v)
                        elif isinstance(v, (dict, list)):
                            candidates.extend(_collect_strings_deep(v))

    for extra in (also_consider or []):
        if isinstance(extra, str):
            candidates.append(extra)
        elif isinstance(extra, (dict, list)):
            candidates.extend(_collect_strings_deep(extra))

    # Fenced JSON blocks
    for s in list(candidates):
        for block in FENCE.findall(s):
            cleaned = _preclean_near_json(block)
            for obj in _brace_scan_json(cleaned):
                _merge_json_into(merged, obj)
            obj, _ = _safe_json_loads(cleaned)
            if obj:
                _merge_json_into(merged, obj)

    # Bare JSON bodies
    for s in list(candidates):
        ss = s.strip()
        if (ss.startswith("{") and ss.endswith("}")) or (ss.startswith("[") and ss.endswith("]")):
            obj, _ = _safe_json_loads(_preclean_near_json(ss))
            if obj:
                _merge_json_into(merged, obj)
            continue
        for obj in _brace_scan_json(ss):
            _merge_json_into(merged, obj)

    # Markdown extraction as last resort
    for s in candidates:
        _extract_from_markdown(merged, s)

    # URLs → sources
    for u in _find_urls("\n".join(candidates)):
        merged["sources"].append(u)

    return merged

# --------------------------------------------------------------------
# Slide builders
# --------------------------------------------------------------------
def _add_bullet_slide(prs, title, bullets, size=18):
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
        p.font.size = Pt(size)

def _add_table_slide(prs, title, headers, rows):
    slide = prs.slides.add_slide(prs.slide_layouts[5])  # Title Only
    slide.shapes.title.text = title
    left, top, width, height = Inches(0.6), Inches(1.6), Inches(9.0), Inches(1.0)
    n_rows = max(2, 1 + len(rows))
    n_cols = len(headers)
    table = slide.shapes.add_table(n_rows, n_cols, left, top, width, height).table

    # headers
    for j, h in enumerate(headers):
        cell = table.cell(0, j)
        cell.text = h
        for p in cell.text_frame.paragraphs:
            p.font.bold = True
            p.font.size = Pt(14)
            p.alignment = PP_ALIGN.LEFT

    # rows
    if rows:
        for i, r in enumerate(rows[: n_rows - 1], 1):
            for j in range(n_cols):
                table.cell(i, j).text = str(r[j]) if j < len(r) else ""
    else:
        table.cell(1, 0).text = "No structured data available."

# --------------------------------------------------------------------
# Top-level API
# --------------------------------------------------------------------
def create_multislide_pptx(result: Dict[str, Any], topic: str, file_path: str):
    """
    Safe PPT builder.
    Returns file_path on success.
    Returns {"error": "..."} on failure, never raises.
    """

    try:
        # -------------------------------------------------------
        # Extract data
        # -------------------------------------------------------
        data, tasks_output = _dig_outputs(result)

        also_consider = []
        if isinstance(data, dict):
            for k in ("summary", "final_output", "raw", "content", "text"):
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    also_consider.append(v)

            also_consider.extend(_collect_strings_deep(data)[:20])

        sections = _extract_all_json_blocks(tasks_output, also_consider)
        if not sections["summary"]:
            sections["summary"] = _strip(data.get("summary")) or "No summary available."

        # -------------------------------------------------------
        # Create PPT
        # -------------------------------------------------------
        prs = Presentation()

        # Title slide
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = "Multi‑Agent Insights Report"
        if len(slide.placeholders) > 1:
            slide.placeholders[1].text = topic

        # Executive Summary
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "Executive Summary"
        tf = slide.placeholders[1].text_frame
        tf.clear()
        tf.paragraphs[0].text = sections["summary"]

        # Other slides
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
            rec_lines.append(
                f"{prefix}{_strip(r.get('action'))} — Why: {_strip(r.get('rationale'))}"
            )
        _add_bullet_slide(prs, "Recommendations", rec_lines)

        _add_bullet_slide(prs, "Sources", sections["sources"], size=16)

        # -------------------------------------------------------
        # Save PPT (safe block!)
        # -------------------------------------------------------
        try:
            prs.save(file_path)
        except Exception as e:
            print("ERROR: Failed to save PPT file:", repr(e))
            import traceback
            traceback.print_exc()
            return {
                "error": "ppt_build_failed",
                "details": f"Could not save pptx: {type(e).__name__}: {e}"
            }

        return file_path

    except Exception as e:
        # Catch ANY unexpected builder exception
        print("ERROR inside create_multislide_pptx:", repr(e))
        import traceback
        traceback.print_exc()
        return {
            "error": "ppt_build_failed",
            "details": f"{type(e).__name__}: {e}"
        }
