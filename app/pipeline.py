# app/pipeline.py
import os, json, threading, inspect
from typing import Dict, Any, Optional
from fastapi import HTTPException

BASE = os.path.dirname(os.path.dirname(__file__))  # adjust if needed

TOOLS_DIR      = os.getenv("TOOLS_DIR", "crew/tools")
AGENTS_DIR     = os.getenv("AGENTS_DIR", "crew/agents")
TASKS_DIR      = os.getenv("TASKS_DIR", "crew/tasks")
CREW_YAML_PATH = os.getenv("CREW_YAML_PATH", "crew/crews/market_insights.yaml")
LLM_YAML_PATH  = os.getenv("LLM_YAML_PATH", "config/llm.yaml")

CREW_STATE: Dict[str, Any] = {"ready": False, "error": None, "crew": None, "llm": None}

def build_llm_and_crew_once() -> Dict[str, Any]:
    if CREW_STATE["ready"] and CREW_STATE["crew"] is not None:
        return CREW_STATE
    try:
        from app.loader import load_llm, load_tools, load_agents, load_tasks, load_crew
        llm    = load_llm(LLM_YAML_PATH)
        tools  = load_tools(TOOLS_DIR)
        agents = load_agents(AGENTS_DIR, llm, tools)
        tasks  = load_tasks(TASKS_DIR, agents)
        crew   = load_crew(CREW_YAML_PATH, agents, tasks)
        CREW_STATE.update({"llm": llm, "crew": crew, "ready": True, "error": None})
    except Exception as e:
        CREW_STATE.update({"ready": False, "error": f"{type(e).__name__}: {e}"})
        print("Crew init failed:", e)
    return CREW_STATE

def warm_async():
    def _warm():
        try:
            build_llm_and_crew_once()
        except Exception as e:
            CREW_STATE.update({"ready": False, "error": f"{type(e).__name__}: {e}"})
    threading.Thread(target=_warm, daemon=True).start()

def ensure_keys():
    required = ["GROQ_API_KEY"]  # add OPENAI_API_KEY, etc.
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing environment variables: {', '.join(missing)}")

def run_crew_pipeline(topic: str) -> dict:
    import json, os
    from typing import Any, Iterable
    ensure_keys()
    state = build_llm_and_crew_once()

    if not state["ready"] or state["crew"] is None:
        raise HTTPException(status_code=500, detail=f"Crew not ready: {state['error']}")

    crew = state["crew"]
    raw_result = crew.kickoff({"topic": topic})

    # ---------- helpers ----------
    def _as_list(x: Any) -> Iterable:
        if x is None:
            return []
        if isinstance(x, (list, tuple)):
            return x
        return [x]

    def _to_text(x: Any) -> str:
        """Extract text from any object (dict, custom object, str)."""
        if x is None:
            return ""
        if isinstance(x, str):
            return x.strip()

        # Common containers: dict
        if isinstance(x, dict):
            for key in ("content", "raw", "text", "value", "output"):
                v = x.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        else:
            # Custom objects like CrewOutput(...). Try common attributes.
            for key in ("content", "raw", "text", "value", "output"):
                if hasattr(x, key):
                    v = getattr(x, key)
                    if isinstance(v, str) and v.strip():
                        return v.strip()

        # Last resorts
        try:
            return json.dumps(x, ensure_ascii=False)
        except Exception:
            return str(x)

    def _extract_text_blocks(r: Any) -> list[str]:
        """
        Normalize arbitrary crew output to a list[str] of text chunks.
        Accepts:
          - str
          - dict with tasks_output (items may be dicts or custom objects)
          - dict with raw/content
          - list/tuple of mixed items
          - any custom object with .raw/.content etc.
        """
        blocks: list[str] = []

        # 1) If top-level has tasks_output
        if isinstance(r, dict) and "tasks_output" in r:
            for item in _as_list(r.get("tasks_output", [])):
                txt = _to_text(item)
                if txt:
                    blocks.append(txt)

        # 2) If top-level has raw/content/text/value/output
        if not blocks and isinstance(r, dict):
            txt = _to_text(r)
            if txt:
                blocks.append(txt)

        # 3) If plain string
        if not blocks and isinstance(r, str):
            if r.strip():
                blocks.append(r.strip())

        # 4) If list/tuple at top level
        if not blocks and isinstance(r, (list, tuple)):
            for el in r:
                txt = _to_text(el)
                if txt:
                    blocks.append(txt)

        # 5) If custom object
        if not blocks:
            txt = _to_text(r)
            if txt:
                blocks.append(txt)

        # ensure at least one block
        return blocks or [""]

    text_blocks = _extract_text_blocks(raw_result)

    # ---------- summary (use LLM if available, fallback otherwise) ----------
    llm = state.get("llm")
    combined_text = "\n\n".join(text_blocks)[:8000]  # keep prompt reasonable

    summary_text = ""
    if llm:
        prompt = f"""Summarize the findings BELOW in 5–7 concise bullet points.
Avoid extra headings or sections—just bullets.

CONTENT START
{combined_text}
CONTENT END
"""
        try:
            sr = llm(prompt)
            summary_text = sr if isinstance(sr, str) else str(sr)
        except Exception as e:
            summary_text = f"- Summary generation failed ({type(e).__name__}); using fallback.\n"

    if not summary_text.strip():
        bullets = []
        for blk in text_blocks[:7]:
            first_line = (blk or "").strip().splitlines()[0] if blk else ""
            if first_line:
                bullets.append(f"- {first_line[:200]}")
        summary_text = "\n".join(bullets) if bullets else "- No content available."

    # ---------- build normalized output ----------
    tasks_output = [{"content": tb} for tb in text_blocks if tb]

    enriched = {
        "summary": summary_text.strip(),
        "tasks_output": tasks_output,
    }

    # ---------- save JSON safely ----------
    runs_dir = os.path.join(BASE, "runs")
    os.makedirs(runs_dir, exist_ok=True)
    outfile = os.path.join(runs_dir, "latest_output.json")
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    return enriched
