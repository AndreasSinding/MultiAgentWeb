# -*- coding: utf-8 -*-
"""
ppt_builder.py — Robust, JSON-and-Markdown tolerant deck builder

- Works with CrewAI multi-agent outputs (JSON + Markdown)
- Defensive JSON parsing (no unguarded json.loads)
- Understands Research task trend dicts: title / evidence / why_it_matters
- Parses Norwegian AND English markdown headings
- Stable 10-slide deck:
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
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN


# --------------------------------------------------------------------
# JSON sanitization & safe parsing
# --------------------------------------------------------------------
def _preclean_near_json(s: str) -> str:
    """
    Clean markdown bullets, code fences, and stray formatting before JSON parsing.
    """
    if not isinstance(s, str):
        return ""
    s = s.strip()
    # Strip ```json ... ``` or ``` ... ```
    s = re.sub(r"```(?:json)?\s*([\s\S]*?)\s*```", r"\1", s, flags=re.I)
    # Remove leading "-" or "*" bullets
    lines = [re.sub(r"^\s*[-*]\s+", "", ln) for ln in s.splitlines()]
    return "\n".join(lines).strip()


def _safe_json_loads(s: str):
    """
    json.loads wrapper that never raises. Returns (obj, err).
    """
    try:
        return json.loads(s), None
    except Exception as e:
        return None, e


# --------------------------------------------------------------------
# Utility helpers
# --------------------------------------------------------------------
def _safe_filename(base: str) -> str:
    if not base:
        return "report"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_") or "report"


def _strip(x: Any) -> str:
    """Robust strip that safely handles non-strings (int, float, None)."""
    if x is None:
        return ""
    return str(x).strip()


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


# --------------------------------------------------------------------
# Section maps (NO + EN) and result shape helpers
# --------------------------------------------------------------------
SECTION_MAP_NO = {
    "sammendrag": "summary",
    "trender": "trends",
    "innsikt": "insights",
    "muligheter": "opportunities",
    "risiko": "risks",
    "aktører / konkurrenter": "competitors",
    "aktorer / konkurrenter": "competitors",  # ascii fallback
    "nøkkeltall": "numbers",
    "nokkelstall": "numbers",  # ascii fallback
    "anbefalinger": "recommendations",
    "kilder": "sources",
}

SECTION_MAP_EN = {
    "executive summary": "summary",
    "key trends": "trends",
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
    "summary", "trends", "insights", "opportunities", "risks",
    "competitors", "numbers", "recommendations", "sources"
]


def _dig_outputs(result: Any):
    """
    Accept both:
      - {"result": {..., "tasks_output": [...]}}
      - {..., "tasks_output": [...]}
    Return (data_dict, tasks_output_list)
    """
    data = result
    if isinstance(result, dict) and isinstance(result.get("result"), dict):
        data = result["result"]
    tasks_output = []
    if isinstance(data, dict):
        tasks_output = data.get("tasks_output") or data.get("tasks") or []
    return (data if isinstance(data, dict) else {}), tasks_output


def _collect_strings_deep(obj, limit=20000):
    """
    Walk any dict/list and collect string-like values that look relevant.
    Soft cap to avoid giant payloads.
    """
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

    # mild dedupe + cap
    seen, res, total = set(), [], 0
    for s in out:
        if s in seen:
            continue
        seen.add(s)
        res.append(s)
        total += len(s)
        if total > limit:
            break
    return res


# --------------------------------------------------------------------
# Extraction: JSON (safe) + Markdown (NO/EN)
# --------------------------------------------------------------------
def _extract_all_json_blocks(
    tasks_output: List[Dict[str, Any]],
    also_consider: List[Any] = None
) -> Dict[str, Any]:
    merged = {k: ([] if k != "summary" else "") for k in SECTION_KEYS}
    candidates: List[str] = []

    # Collect from task blocks
    for blk in tasks_output or []:
        if isinstance(blk, dict):
            for key in ("raw", "content", "text", "final_output", "result", "output", "message"):
                s = blk.get(key)
                if isinstance(s, str) and s.strip():
                    candidates.append(s)
                elif isinstance(s, (dict, list)):
                    candidates.extend(_collect_strings_deep(s))
            # Artifacts
            if isinstance(blk.get("artifacts"), list):
                for a in blk["artifacts"]:
                    if isinstance(a, dict):
                        for k in ("content", "text", "raw", "result"):
                            v = a.get(k)
                            if isinstance(v, str) and v.strip():
                                candidates.append(v)
                            elif isinstance(v, (dict, list)):
                                candidates.extend(_collect_strings_deep(v))

    # Add extra bodies
    for extra in (also_consider or []):
        if isinstance(extra, str) and extra.strip():
            candidates.append(extra)
        elif isinstance(extra, (dict, list)):
            candidates.extend(_collect_strings_deep(extra))

    # 1) Fenced JSON blocks: parse safely
    fence = re.compile(r"```(?:json)?(.*?)```", flags=re.S | re.I)
    for s in list(candidates):
        for block in fence.findall(s):
            cleaned = _preclean_near_json(block)
            ss = cleaned.strip()

            # brace scan never raises
            for obj in _brace_scan_json(ss):
                _merge_any_json_into(merged, obj)

            # try full parse on STRIPPED content; swallow errors
            if ss.startswith(("{", "[")):
                obj, _ = _safe_json_loads(ss)
                if obj is not None:
                    _merge_any_json_into(merged, obj)

    # 2) Bare/braced JSON: safe path
    for s in candidates:
        ss = (s or "").strip()
        if (ss.startswith("{") and ss.endswith("}")) or (ss.startswith("[") and ss.endswith("]")):
            obj, _ = _safe_json_loads(_preclean_near_json(ss))
            if obj is not None:
                _merge_any_json_into(merged, obj)
                continue
        for obj in _brace_scan_json(ss):
            _merge_any_json_into(merged, obj)

    # 3) Markdown extraction (NO + EN)
    for s in candidates:
        _extract_from_markdown_no(merged, s)
        _extract_from_markdown_en(merged, s)

    # 4) URLs anywhere -> sources
    for u in _find_urls("\n".join(candidates)):
        if u not in merged["sources"]:
            merged["sources"].append(u)

    return merged


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
    if {"name", "position"} <= keys:
        merged["competitors"].append(
            {"name": _strip(item.get("name")),
             "position": _strip(item.get("position")),
             "notes": _strip(item.get("notes"))}
        )
    elif {"metric", "value"} <= keys:
        merged["numbers"].append(
            {"metric": _strip(item.get("metric")),
             "value": _strip(item.get("value")),
             "source": _strip(item.get("source"))}
        )
    elif {"priority", "action"} <= keys:
        merged["recommendations"].append(
            {"priority": item.get("priority"),
             "action": _strip(item.get("action")),
             "rationale": _strip(item.get("rationale"))}
        )
    else:
        s = _strip("; ".join(f"{k}: {v}" for k, v in item.items()))
        if s and s not in merged["insights"]:
            merged["insights"].append(s)


def _brace_scan_json(text: str) -> List[Any]:
    """
    Scan for {...} blocks and attempt to parse each independently. Never raises.
    """
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
# Markdown extractors (NO + EN)
# --------------------------------------------------------------------
def _extract_from_markdown_no(merged: Dict[str, Any], s: str) -> None:
    lines = [ln.rstrip() for ln in (s or "").splitlines()]
    current = None
    buf: List[str] = []

    def flush():
        nonlocal buf, current
        if not current or not buf:
            buf = []
            return
        key = SECTION_MAP_NO.get(current, None)
        if not key:
            buf = []
            return

        if key in ("trends", "insights", "opportunities", "risks", "sources"):
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
        elif key == "summary":
            text = " ".join([_drop_bullet(x) for x in buf]).strip()
            if text and len(text) > len(merged["summary"]):
                merged["summary"] = text
        buf = []

    for ln in lines:
        ln_clean = ln.strip()
        # If the model produced a bullet before a header, e.g. "- # Sammendrag"
        if re.match(r'^(-|\*|•|\d+[.)])\s+#', ln_clean):
            ln_clean = re.sub(r'^(-|\*|•|\d+[.)])\s+', '', ln_clean)

        ln_lower = ln_clean.lower().rstrip(":")
        if ln_clean.startswith("#"):
            header = ln_clean.lstrip("# ").lower().rstrip(":")
            if header in SECTION_MAP_NO:
                flush(); current = header; buf = []; continue
        if ln_lower in SECTION_MAP_NO:
            flush(); current = ln_lower; buf = []; continue

        if current:
            if re.match(r'^(-|\*|•|\d+[.)])\s+', ln_clean) or ln_clean:
                buf.append(ln_clean)

    flush(); flush()


def _extract_from_markdown_en(merged: Dict[str, Any], s: str) -> None:
    lines = [ln.rstrip() for ln in (s or "").splitlines()]
    current = None
    buf: List[str] = []

    def flush():
        nonlocal buf, current
        if not current or not buf:
            buf = []
            return
        key = SECTION_MAP_EN.get(current, None)
        if not key:
            buf = []
            return

        if key in ("trends", "insights", "opportunities", "risks", "sources"):
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
        elif key == "summary":
            text = " ".join([_drop_bullet(x) for x in buf]).strip()
            if text and len(text) > len(merged["summary"]):
                merged["summary"] = text
        buf = []

    for ln in lines:
        ln_clean = ln.strip()
        if ln_clean.startswith("#"):
            header = ln_clean.lstrip("# ").lower().rstrip(":")
            if header in SECTION_MAP_EN:
                flush(); current = header; buf = []; continue
        if ln_clean.lower().rstrip(":") in SECTION_MAP_EN:
            flush(); current = ln_clean.lower().rstrip(":"); buf = []; continue

        if current:
            if re.match(r'^(-|\*|•|\d+[.)])\s+', ln_clean) or ln_clean:
                buf.append(ln_clean)

    flush(); flush()


def _drop_bullet(s: str) -> str:
    # -, *, •, "1.", "1)"
    return re.sub(r'^(-|\*|•|\d+[.)])\s+', '', s).strip()


def _find_urls(s: str) -> List[str]:
    return re.findall(r'(https?://[^\s\)]+)', s or '')


def _split3(s: str):
    parts = re.split(r'\s+[–\-;:]\s+', s, maxsplit=2)
    parts += ["", "", ""]
    return _strip(parts[0]), _strip(parts[1]), _strip(parts[2])


def _split_recommendation(items: List[str]):
    prio, act, why = [], [], []
    for it in items:
        m = re.match(r'^\[?\s*prioritet\s*(\d+)\s*\]?\s*(.+?)(?:\s+[—\-]\s+(.+))?$', it, flags=re.I)
        if m:
            prio.append(int(m.group(1)))
            act.append(_strip(m.group(2)))
            why.append(_strip(m.group(3) or ''))
        else:
            prio.append(None)
            segs = re.split(r'\s+[—\-]\s+', it, maxsplit=1)
            act.append(_strip(segs[0]))
            why.append(_strip(segs[1] if len(segs) > 1 else ''))
    return prio, act, why


# --------------------------------------------------------------------
# JSON normalization + merging (supports your YAML shapes)
# --------------------------------------------------------------------
def _merge_research_block(merged: Dict[str, Any], research: Dict[str, Any]) -> None:
    # trends: list of dicts from research.yaml: title, evidence, why_it_matters
    tr = research.get("trends")
    if isinstance(tr, list):
        for t in tr:
            if isinstance(t, dict):
                title = _strip(t.get("title") or t.get("name") or "")
                why = _strip(t.get("why_it_matters") or t.get("detail") or t.get("summary") or t.get("insight") or "")
                ev = _strip(t.get("evidence") or "")
                line = f"{title} — {why}".strip(" —")
                if ev and line:
                    line = f"{line} (evidence: {ev})"
                if line and line not in merged["trends"]:
                    merged["trends"].append(line)

    # numbers (metric/value/source)
    nums = research.get("numbers") or research.get("metrics")
    if isinstance(nums, list):
        for n in nums:
            if isinstance(n, dict):
                merged["numbers"].append({
                    "metric": _strip(n.get("metric") or n.get("name")),
                    "value": _strip(n.get("value") or n.get("val")),
                    "source": _strip(n.get("source") or n.get("url")),
                })

    # competitors
    comps = research.get("competitors") or research.get("actors")
    if isinstance(comps, list):
        for c in comps:
            if isinstance(c, dict):
                merged["competitors"].append({
                    "name": _strip(c.get("name")),
                    "position": _strip(c.get("position") or c.get("role") or ""),
                    "notes": _strip(c.get("notes") or c.get("summary") or ""),
                })

    # insights, opportunities, risks, sources (strings)
    for k in ("insights", "opportunities", "risks", "sources"):
        val = research.get(k)
        for item in _coerce_list(val):
            s = _strip(item)
            if s and s not in merged[k]:
                merged[k].append(s)

    # recommendations (dicts)
    if isinstance(research.get("recommendations"), list):
        for r in research["recommendations"]:
            if isinstance(r, dict):
                merged["recommendations"].append({
                    "priority": r.get("priority"),
                    "action": _strip(r.get("action") or r.get("what")),
                    "rationale": _strip(r.get("rationale") or r.get("why")),
                })


def _merge_json_into(merged: Dict[str, Any], obj: Dict[str, Any]) -> None:
    """Merge JSON dict from agent into main structure."""
    # nested 'research' object
    if isinstance(obj.get("research"), dict):
        _merge_research_block(merged, obj["research"])

    # Summary (prefer longest)
    if "summary" in obj:
        s = _strip(obj.get("summary"))
        if s and len(s) > len(merged["summary"]):
            merged["summary"] = s

    # Simple list/strings (and dict-based 'trends')
    for key in ("trends", "insights", "opportunities", "risks", "sources"):
        val = obj.get(key)
        if key == "trends" and isinstance(val, list) and all(isinstance(x, dict) for x in val):
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


# --------------------------------------------------------------------
# Slide helpers
# --------------------------------------------------------------------
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


# --------------------------------------------------------------------
# New: bullet normalization for soft/fuzzy de-duplication
# --------------------------------------------------------------------
def _normalize_bullet_text(s: str) -> str:
    """
    Normalize bullet-like lines so dedupe works but content remains distinct.
    - removes leading symbols (-, •, *)
    - collapses whitespace
    - normalizes colon spacing
    - lowercases for signature only
    """
    if not s:
        return ""
    s = str(s).strip()
    s = re.sub(r"^[-*•]+\s*", "", s)           # leading bullets
    s = re.sub(r"\s+", " ", s)                 # multiple spaces -> single
    s = re.sub(r"\s*:\s*", ": ", s)            # normalize "topic : text" / "topic:  text"
    return s.lower().strip()


def _clean_sections(sections):
    """Final pass to eliminate duplicates while preserving content."""
    for key, value in sections.items():
        if key == "summary":
            continue  # Keep longest summary

        # --- Mild dedupe for general text sections using normalization signature ---
        if key in ("trends", "insights", "opportunities", "risks"):
            cleaned = []
            seen = set()
            for v in value:
                original = _strip(v)
                normalized = _normalize_bullet_text(original)
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    cleaned.append(original)   # keep user's original formatting
            sections[key] = cleaned
            continue

        # --- recommendations: dedupe by action+rationale ---
        if key == "recommendations":
            norm = []
            seen = set()
            for r in value:
                action = _strip(r.get("action", "")).lower()
                rationale = _strip(r.get("rationale", "")).lower()
                sig = (action, rationale)
                if sig not in seen:
                    seen.add(sig)
                    norm.append(r)
            sections[key] = norm
            continue

        # --- competitors & numbers: structured dedupe ---
        if key in ("competitors", "numbers"):
            unique = []
            seen = set()
            for item in value:
                row_sig = tuple(
                    (k, _strip(item.get(k, "")).lower())
                    for k in sorted(item.keys())
                )
                if row_sig not in seen:
                    seen.add(row_sig)
                    unique.append({k: _strip(item.get(k, "")) for k in item})
            sections[key] = unique
            continue

        # --- sources: literal dedupe ---
        if key == "sources":
            deduped = []
            seen = set()
            for v in value:
                s = _strip(v)
                if s and s not in seen:
                    seen.add(s)
                    deduped.append(s)
            sections[key] = deduped
            continue

    return sections


# --------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------
def create_multislide_pptx(result: Dict[str, Any], topic: str, file_path: str) -> str:
    # robustly read pipeline output
    data, tasks_output = _dig_outputs(result)

    # consider many potential stringy fields
    also_consider = []
    if isinstance(data, dict):
        # common keys
        for k in ("summary", "final_output", "raw", "content", "text"):
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                also_consider.append(v)
        # and a small deep sweep
        also_consider.extend(_collect_strings_deep(data)[:20])

    sections = _extract_all_json_blocks(tasks_output, also_consider=also_consider)

    # ensure we always have a summary
    if not sections["summary"]:
        sections["summary"] = _strip(data.get("summary")) or "No summary available."

    # final cleanup pass (dedupe, normalization)
    sections = _clean_sections(sections)

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
    _add_table_slide(prs, "Competitors / Actors", ["Name", "Position", "Notes"], comp_rows)

    num_rows = [
        [_strip(n.get("metric")), _strip(n.get("value")), _strip(n.get("source"))]
        for n in sections["numbers"]
    ]
    _add_table_slide(prs, "Key Numbers", ["Metric", "Value", "Source"], num_rows)

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
